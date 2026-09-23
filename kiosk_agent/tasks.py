import logging
from time import monotonic

from asgiref.sync import async_to_sync, sync_to_async
from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from openai import AsyncOpenAI

from .core.agent_engine import publish, run_agent
from .core.voice import generate_and_publish_tts
from .integrations.saas import forward_request_to_saas
from .models import ChaletConfig, KioskAuditLog, KioskMessage, StaffRequest

logger = logging.getLogger(__name__)


def _mark_request_complete(stay_id: str, request_id: str) -> None:
    KioskMessage.objects.filter(
        stay_id=stay_id,
        request_id=request_id,
        role=KioskMessage.Role.USER,
        status__in=(KioskMessage.Status.QUEUED, KioskMessage.Status.STREAMING),
    ).update(status=KioskMessage.Status.COMPLETE)


async def _run_concierge_with_voice(stay_id: str, request_id: str) -> None:
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY) as client:
        started = monotonic()
        response_text = await run_agent(stay_id=stay_id, request_id=request_id, client=client)
        logger.info("Concierge model time for %s: %.2fs", request_id, monotonic() - started)
        await sync_to_async(_mark_request_complete, thread_sensitive=True)(stay_id, request_id)
        if response_text:
            speech_started = monotonic()
            await generate_and_publish_tts(
                text=response_text,
                stay_id=stay_id,
                request_id=request_id,
                client=client,
            )
            logger.info("Concierge speech time for %s: %.2fs", request_id, monotonic() - speech_started)


@shared_task(name="kiosk_agent.welcome_tts")
def welcome_tts_task(stay_id: str, request_id: str) -> None:
    """Speak the initial greeting with the configured backend voice."""
    close_old_connections()
    try:
        config = ChaletConfig.load()
        if str(config.current_stay_id) != stay_id:
            return
        greeting = f"أهلاً وسهلاً، أنا {config.persona_name}، معك. تفضل."
        async_to_sync(generate_and_publish_tts)(
            text=greeting, stay_id=stay_id, request_id=request_id
        )
    except Exception:
        async_to_sync(publish)(
            stay_id, "tts_fallback", request_id,
            text="أهلاً وسهلاً، أنا معك. تفضل.", nonce=request_id,
        )
        raise
    finally:
        close_old_connections()


@shared_task(bind=True, autoretry_for=(), max_retries=3, name="kiosk_agent.run_concierge")
def run_concierge_task(self, stay_id: str, request_id: str) -> None:
    close_old_connections()
    request = KioskMessage.objects.filter(
        stay_id=stay_id,
        request_id=request_id,
        role=KioskMessage.Role.USER,
    )
    status = request.values_list("status", flat=True).first()
    if status is None:
        logger.warning(
            "Request %s is not visible to the worker yet; retrying",
            request_id,
        )
        close_old_connections()
        raise self.retry(countdown=1)
    if status != KioskMessage.Status.QUEUED:
        close_old_connections()
        return
    try:
        claimed = request.filter(status=KioskMessage.Status.QUEUED).update(
            status=KioskMessage.Status.STREAMING
        )
        if not claimed:
            return
        KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.AGENT_STARTED,
            details={"celery_task_id": self.request.id},
        )
        async_to_sync(_run_concierge_with_voice)(stay_id, request_id)
        KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.AGENT_COMPLETED,
        )
    except Exception as exc:
        KioskMessage.objects.filter(
            stay_id=stay_id,
            request_id=request_id,
            role=KioskMessage.Role.USER,
            status__in=(KioskMessage.Status.QUEUED, KioskMessage.Status.STREAMING),
        ).update(status=KioskMessage.Status.FAILED)
        KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.AGENT_FAILED,
            details={"error_type": type(exc).__name__, "message": str(exc)[:500]},
        )
        async_to_sync(publish)(stay_id, "error", request_id, message="The concierge is temporarily unavailable.")
        raise
    finally:
        close_old_connections()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    name="kiosk_agent.forward_staff_request",
)
def forward_staff_request_task(self, staff_request_id: int) -> None:
    close_old_connections()
    try:
        request = StaffRequest.objects.get(pk=staff_request_id)
        config = ChaletConfig.load()
        request.delivery_attempts += 1
        result = async_to_sync(forward_request_to_saas)(
            config=config,
            service=request.service,
            details=request.details,
            urgency=request.urgency,
            stay_id=str(request.stay_id),
            request_id=str(request.request_id),
            local_reference=request.local_reference,
        )
        if result.get("forwarded"):
            response = result.get("response") or {}
            request.delivery_status = StaffRequest.DeliveryStatus.DELIVERED
            request.external_reference = str(response.get("id") or "")[:160]
            request.last_error = ""
            request.save(
                update_fields=(
                    "delivery_attempts",
                    "delivery_status",
                    "external_reference",
                    "last_error",
                    "updated_at",
                )
            )
            return
        reason = result.get("reason") or result.get("error") or "forwarding_failed"
        if reason == "disabled_or_no_url":
            request.delivery_status = StaffRequest.DeliveryStatus.DISABLED
            request.last_error = ""
            request.save(
                update_fields=(
                    "delivery_attempts",
                    "delivery_status",
                    "last_error",
                    "updated_at",
                )
            )
            return
        request.delivery_status = StaffRequest.DeliveryStatus.FAILED
        request.last_error = str(reason)[:500]
        request.save(
            update_fields=(
                "delivery_attempts",
                "delivery_status",
                "last_error",
                "updated_at",
            )
        )
        status_code = result.get("status_code")
        if isinstance(status_code, int) and 400 <= status_code < 500:
            return
        raise RuntimeError(request.last_error)
    finally:
        close_old_connections()
