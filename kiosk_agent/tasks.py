from asgiref.sync import async_to_sync
from celery import shared_task
from django.db import close_old_connections

from .core.agent_engine import publish, run_agent
from .core.voice import generate_and_publish_tts
from .models import KioskAuditLog, KioskMessage


@shared_task(bind=True, autoretry_for=(), max_retries=0, name="kiosk_agent.run_concierge")
def run_concierge_task(self, stay_id: str, request_id: str) -> None:
    close_old_connections()
    try:
        KioskMessage.objects.filter(
            stay_id=stay_id,
            request_id=request_id,
            role=KioskMessage.Role.USER,
            status=KioskMessage.Status.QUEUED,
        ).update(status=KioskMessage.Status.STREAMING)
        KioskAuditLog.objects.create(
            stay_id=stay_id,
            request_id=request_id,
            event=KioskAuditLog.Event.AGENT_STARTED,
            details={"celery_task_id": self.request.id},
        )
        response_text = async_to_sync(run_agent)(stay_id=stay_id, request_id=request_id)
        KioskMessage.objects.filter(
            stay_id=stay_id,
            request_id=request_id,
            role=KioskMessage.Role.USER,
            status=KioskMessage.Status.STREAMING,
        ).update(status=KioskMessage.Status.COMPLETE)
        if response_text:
            async_to_sync(generate_and_publish_tts)(
                text=response_text,
                stay_id=stay_id,
                request_id=request_id,
            )
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
            status=KioskMessage.Status.QUEUED,
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
