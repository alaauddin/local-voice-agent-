import uuid
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .models import ChaletConfig, KioskAuditLog, KioskMessage
from .tasks import run_concierge_task


class AgentBusyError(Exception):
    pass


def enqueue_message(content: str) -> tuple[uuid.UUID, uuid.UUID]:
    close_old_connections()
    try:
        with transaction.atomic():
            config = ChaletConfig.objects.select_for_update().get_or_create(pk=ChaletConfig.SINGLETON_PK)[0]
            active_messages = KioskMessage.objects.filter(
                stay_id=config.current_stay_id,
                role=KioskMessage.Role.USER,
                status__in=(KioskMessage.Status.QUEUED, KioskMessage.Status.STREAMING),
            )
            completed_request_ids = KioskMessage.objects.filter(
                stay_id=config.current_stay_id,
                role=KioskMessage.Role.ASSISTANT,
                status=KioskMessage.Status.COMPLETE,
            ).values("request_id")
            active_messages.filter(request_id__in=completed_request_ids).update(
                status=KioskMessage.Status.COMPLETE
            )
            completed_audit_ids = KioskAuditLog.objects.filter(
                stay_id=config.current_stay_id,
                event=KioskAuditLog.Event.AGENT_COMPLETED,
            ).values("request_id")
            active_messages.filter(request_id__in=completed_audit_ids).update(
                status=KioskMessage.Status.COMPLETE
            )
            stale_before = timezone.now() - timedelta(
                seconds=settings.KIOSK_STALE_REQUEST_SECONDS
            )
            active_messages.filter(created_at__lt=stale_before).update(
                status=KioskMessage.Status.FAILED,
                metadata={"failure": "stale_request_recovered"},
            )
            active = active_messages.exists()
            if active:
                raise AgentBusyError("الطلب السابق قيد المعالجة، يرجى الانتظار لحظة.")
            request_id = uuid.uuid4()
            KioskMessage.objects.create(
                stay_id=config.current_stay_id,
                request_id=request_id,
                role=KioskMessage.Role.USER,
                content=content,
                status=KioskMessage.Status.QUEUED,
            )
            KioskAuditLog.objects.create(
                stay_id=config.current_stay_id,
                request_id=request_id,
                event=KioskAuditLog.Event.CHAT_QUEUED,
            )
            stay_id = config.current_stay_id
        transaction.on_commit(lambda: run_concierge_task.delay(str(stay_id), str(request_id)))
        return request_id, stay_id
    finally:
        close_old_connections()
