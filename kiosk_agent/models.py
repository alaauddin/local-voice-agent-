import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ChaletConfig(models.Model):
    """The one local chalet identity and its concierge configuration."""

    SINGLETON_PK = 1
    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_PK, editable=False)
    chalet_name = models.CharField(max_length=120, default="منتجع الغروب")
    chalet_number = models.CharField(max_length=30, default="101")
    persona_name = models.CharField(max_length=80, default="غروب")
    welcome_message = models.TextField(
        blank=True,
        default="قل «يا غروب» واطلب ما تحتاجه، وسأبقى معك طوال المحادثة.",
    )
    property_facts = models.JSONField(default=dict, blank=True)
    enabled_services = models.JSONField(default=list, blank=True)
    emergency_contact = models.CharField(max_length=120, blank=True)
    llm_model = models.CharField(max_length=100, blank=True)
    saas_integration_url = models.URLField(max_length=500, blank=True, help_text="Full SaaS endpoint URL, e.g. https://tenant.raddadoman.com/api/kiosk/requests/")
    saas_integration_token = models.CharField(max_length=500, blank=True, help_text="X-Kiosk-Token / X-API-Key for SaaS")
    saas_tenant_subdomain = models.CharField(max_length=63, blank=True, help_text="Tenant subdomain if SaaS URL is public schema")
    saas_enabled = models.BooleanField(default=False)
    saas_timeout_seconds = models.FloatField(default=5.0)
    current_stay_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.pk not in (None, self.SINGLETON_PK):
            raise ValidationError("Only one ChaletConfig row is allowed.")

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    def rotate_stay(self):
        self.current_stay_id = uuid.uuid4()
        self.save(update_fields=["current_stay_id", "updated_at"])

    def __str__(self):
        return f"{self.chalet_name} ({self.chalet_number})"


class KioskMessage(models.Model):
    class Role(models.TextChoices):
        SYSTEM = "system", "System"
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        STREAMING = "streaming", "Streaming"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    stay_id = models.UUIDField(db_index=True)
    request_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMPLETE)
    tool_name = models.CharField(max_length=100, blank=True)
    tool_call_id = models.CharField(max_length=160, blank=True)
    event_id = models.CharField(max_length=200, null=True, blank=True)
    sequence = models.PositiveBigIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("stay_id", "created_at")),
            models.Index(
                fields=("stay_id", "request_id", "role"),
                name="kiosk_agent_stay_requ_role_idx",
            ),
            models.Index(
                fields=("stay_id", "status", "role"),
                name="kiosk_agent_stay_stat_role_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("stay_id", "event_id"),
                condition=Q(event_id__isnull=False),
                name="unique_stay_realtime_event",
            ),
            models.UniqueConstraint(
                fields=("stay_id", "tool_call_id"),
                condition=~Q(tool_call_id=""),
                name="unique_stay_tool_call",
            ),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:60]}"


class KioskAuditLog(models.Model):
    class Event(models.TextChoices):
        CHAT_QUEUED = "chat_queued", "Chat queued"
        AGENT_STARTED = "agent_started", "Agent started"
        TOOL_CALLED = "tool_called", "Tool called"
        AGENT_COMPLETED = "agent_completed", "Agent completed"
        AGENT_FAILED = "agent_failed", "Agent failed"
        STAY_RESET = "stay_reset", "Stay reset"
        REMOTE_PRESSED = "remote_pressed", "Remote pressed"
        REMOTE_FAILED = "remote_failed", "Remote failed"

    stay_id = models.UUIDField(db_index=True)
    request_id = models.UUIDField(null=True, blank=True, db_index=True)
    event = models.CharField(max_length=40, choices=Event.choices)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.event} at {self.created_at}"


class RealtimeSession(models.Model):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        RESET = "reset", "Reset"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stay_id = models.UUIDField(db_index=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    expires_at = models.DateTimeField(db_index=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("stay_id", "state"),
                name="kiosk_agent_stay_state_rt_idx",
            )
        ]

    def __str__(self):
        return f"{self.id} ({self.state})"


class StaffRequest(models.Model):
    class DeliveryStatus(models.TextChoices):
        DISABLED = "disabled", "Disabled"
        QUEUED = "queued", "Queued"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    stay_id = models.UUIDField(db_index=True)
    request_id = models.UUIDField(db_index=True)
    service = models.CharField(max_length=40)
    details = models.TextField(max_length=1000)
    urgency = models.CharField(max_length=12)
    local_reference = models.CharField(max_length=32, unique=True, blank=True)
    delivery_status = models.CharField(
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.DISABLED,
    )
    external_reference = models.CharField(max_length=160, blank=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.local_reference or f"Staff request {self.pk}"


class RemoteTemplate(models.Model):
    class Category(models.TextChoices):
        AC = "ac", "AC"
        FAN = "fan", "Fan"
        LIGHTS = "lights", "Lights"
        OTHER = "other", "Other"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class RemoteTemplateButton(models.Model):
    template = models.ForeignKey(
        RemoteTemplate,
        on_delete=models.CASCADE,
        related_name="buttons",
    )
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=80)
    icon = models.CharField(max_length=40, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    row = models.PositiveSmallIntegerField(default=0)
    column = models.PositiveSmallIntegerField(default=0)
    requires_confirmation = models.BooleanField(default=False)

    class Meta:
        ordering = ("sort_order", "row", "column", "id")
        constraints = [
            models.UniqueConstraint(fields=("template", "key"), name="uniq_template_button_key"),
            models.UniqueConstraint(
                fields=("template", "row", "column"),
                name="uniq_template_button_position",
            ),
        ]

    def __str__(self):
        return f"{self.template.slug}:{self.key}"


class RemoteControl(models.Model):
    class DeviceType(models.TextChoices):
        RAW = "raw", "Raw IR"
        AC = "ac", "Air conditioner"

    class Brand(models.TextChoices):
        GREE = "gree", "Gree"
        HAIER = "haier", "Haier"
        MIDEA = "midea", "Midea"
        HISENSE = "hisense", "Hisense"

    class Protocol(models.TextChoices):
        GREE = "gree", "Gree"
        HAIER_AC = "haier_ac", "Haier AC"
        HAIER_AC_YRW02 = "haier_ac_yrw02", "Haier AC YR-W02"
        HAIER_AC160 = "haier_ac160", "Haier AC 160-bit"
        HAIER_AC176 = "haier_ac176", "Haier AC 176-bit"
        MIDEA = "midea", "Midea"
        KELON168 = "kelon168", "Kelon 168-bit (Hisense)"

    class ProtocolModel(models.TextChoices):
        DEFAULT = "default", "Default"
        GREE_YAW1F = "yaw1f", "Gree YAW1F"
        GREE_YBOFB = "ybofb", "Gree YBOFB"
        GREE_YX1FSF = "yx1fsf", "Gree YX1FSF"
        HAIER_V9014557_A = "v9014557_a", "Haier V9014557 A"
        HAIER_V9014557_B = "v9014557_b", "Haier V9014557 B"
        HISENSE_DG11R201 = "dg11r2-01", "Hisense/Kelon DG11R2-01"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    location = models.CharField(max_length=120, blank=True)
    device_name = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Must match DEVICE_NAME reported by the ESP32 /identity endpoint.",
    )
    device_ip = models.GenericIPAddressField(
        protocol="IPv4",
        blank=True,
        null=True,
        help_text="Current IP discovered by the Sync device IPs admin action.",
    )
    device_last_seen_at = models.DateTimeField(null=True, blank=True, editable=False)
    device_type = models.CharField(
        max_length=20,
        choices=DeviceType.choices,
        default=DeviceType.RAW,
    )
    brand = models.CharField(max_length=50, choices=Brand.choices, blank=True)
    protocol = models.CharField(max_length=50, choices=Protocol.choices, blank=True)
    protocol_model = models.CharField(
        max_length=50,
        choices=ProtocolModel.choices,
        blank=True,
    )
    template = models.ForeignKey(
        RemoteTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="remotes",
    )
    template_slug = models.SlugField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    voice_enabled = models.BooleanField(
        default=False,
        help_text="Allow voice tools to press buttons on this remote.",
    )
    guest_visible = models.BooleanField(
        default=True,
        help_text="Show this remote on the kiosk guest panel.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("device_name",),
                condition=models.Q(device_type="ac") & ~models.Q(device_name=""),
                name="uniq_ac_remote_device_name",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def configured_count(self) -> int:
        return sum(button.is_configured for button in self.buttons.filter(is_active=True))

    @property
    def active_button_count(self) -> int:
        return self.buttons.filter(is_active=True).count()


class ACState(models.Model):
    class Mode(models.TextChoices):
        AUTO = "auto", "Auto"
        COOL = "cool", "Cool"
        HEAT = "heat", "Heat"
        DRY = "dry", "Dry"
        FAN = "fan", "Fan"

    class Fan(models.TextChoices):
        AUTO = "auto", "Auto"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    device = models.OneToOneField(
        RemoteControl,
        on_delete=models.CASCADE,
        related_name="ac_state",
    )
    power = models.BooleanField(default=False)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.COOL)
    temperature = models.PositiveSmallIntegerField(default=24)
    fan = models.CharField(max_length=20, choices=Fan.choices, default=Fan.AUTO)
    swing_vertical = models.BooleanField(default=False)
    swing_horizontal = models.BooleanField(default=False)
    turbo = models.BooleanField(default=False)
    sleep = models.BooleanField(default=False)
    eco = models.BooleanField(default=False)
    quiet = models.BooleanField(default=False)
    light = models.BooleanField(default=False)
    x_fan = models.BooleanField(default=False)
    state_version = models.PositiveBigIntegerField(default=0)
    esp32_updated_at = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AC state: {self.device.name}"


class RemoteButton(models.Model):
    remote = models.ForeignKey(
        RemoteControl,
        on_delete=models.CASCADE,
        related_name="buttons",
    )
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=80)
    icon = models.CharField(max_length=40, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    row = models.PositiveSmallIntegerField(default=0)
    column = models.PositiveSmallIntegerField(default=0)
    command_url = models.CharField(
        max_length=500,
        blank=True,
        help_text="IR controller endpoint, for example http://192.168.1.102/ir.",
    )
    ir_id = models.PositiveIntegerField(
        default=1,
        help_text="Controller/device id sent in the JSON payload.",
    )
    frequency = models.PositiveSmallIntegerField(
        default=38,
        help_text="IR carrier frequency in kHz.",
    )
    raw = models.JSONField(
        default=list,
        blank=True,
        help_text="Raw IR pulse timings as a JSON array of positive integers.",
    )
    is_active = models.BooleanField(default=True)
    requires_confirmation = models.BooleanField(default=False)

    class Meta:
        ordering = ("sort_order", "row", "column", "id")
        constraints = [
            models.UniqueConstraint(fields=("remote", "key"), name="uniq_remote_button_key"),
            models.UniqueConstraint(
                fields=("remote", "row", "column"),
                name="uniq_remote_button_position",
            ),
        ]

    def __str__(self):
        return f"{self.remote.slug}:{self.key}"

    @property
    def is_configured(self) -> bool:
        return bool(self.target_command_url and self.raw)

    @property
    def target_command_url(self) -> str:
        """Prefer the endpoint discovered for the remote's stable DEVICE_NAME."""
        if self.remote.device_name and self.remote.device_ip:
            return f"http://{self.remote.device_ip}/ir"
        return (self.command_url or "").strip()

    @property
    def command_payload(self) -> dict:
        return {
            "id": self.ir_id,
            "frequency": self.frequency,
            "raw": self.raw,
        }

    def clean(self):
        from kiosk_agent.remote_control import validate_command_url, validate_ir_command

        super().clean()
        if self.command_url.strip():
            validate_command_url(self.command_url)
        if self.raw:
            validate_ir_command(self.ir_id, self.frequency, self.raw)
