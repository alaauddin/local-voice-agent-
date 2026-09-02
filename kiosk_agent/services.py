import uuid

from django.db import close_old_connections, transaction

from .models import ChaletConfig, KioskAuditLog, KioskMessage
from .tasks import run_concierge_task


class AgentBusyError(Exception):
    pass


def enqueue_message(content: str) -> tuple[uuid.UUID, uuid.UUID]:
    close_old_connections()
    try:
        with transaction.atomic():
            config = ChaletConfig.objects.select_for_update().get_or_create(pk=ChaletConfig.SINGLETON_PK)[0]
            active = KioskMessage.objects.filter(
                stay_id=config.current_stay_id,
                role=KioskMessage.Role.USER,
                status__in=(KioskMessage.Status.QUEUED, KioskMessage.Status.STREAMING),
            ).exists()
            if active:
                raise AgentBusyError("A concierge response is already in progress.")
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
