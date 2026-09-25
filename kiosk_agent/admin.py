from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify

from .device_discovery import DeviceDiscoveryError, discover_identity_devices
from .models import (
    ACState,
    ChaletConfig,
    KioskAuditLog,
    KioskMessage,
    RealtimeSession,
    RemoteButton,
    RemoteControl,
    RemoteTemplate,
    RemoteTemplateButton,
    StaffRequest,
)
from .remote_control import (
    RemoteCommandError,
    press_remote_button,
    validate_command_url,
    validate_ir_command,
)


@admin.register(ChaletConfig)
class ChaletConfigAdmin(admin.ModelAdmin):
    list_display = ("chalet_name", "chalet_number", "persona_name", "is_active", "saas_status", "updated_at")
    readonly_fields = ("current_stay_id", "updated_at", "saas_status")
    fieldsets = (
        (None, {"fields": ("chalet_name", "chalet_number", "persona_name", "welcome_message")}),
        ("Content", {"fields": ("property_facts", "enabled_services", "emergency_contact", "llm_model")}),
        (
            "SaaS Integration — Wazen-Saia",
            {
                "description": "Forward every request_property_staff tool call to SaaS /api/kiosk/requests/. Leave token empty for local AllowAny; set tenant subdomain only if SaaS uses public schema routing (X-Tenant header).",
                "fields": ("saas_status", "saas_enabled", "saas_integration_url", "saas_integration_token", "saas_tenant_subdomain", "saas_timeout_seconds"),
            },
        ),
        ("System", {"fields": ("is_active", "current_stay_id", "updated_at")}),
    )

    @admin.display(description="SaaS", boolean=True)
    def saas_status(self, obj):
        return bool(obj.saas_enabled and obj.saas_integration_url)

    def has_add_permission(self, request):
        return not ChaletConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KioskMessage)
class KioskMessageAdmin(admin.ModelAdmin):
    list_display = ("role", "status", "request_id", "stay_id", "created_at")
    list_filter = ("role", "status")
    search_fields = ("content", "request_id")
    readonly_fields = ("created_at",)


@admin.register(KioskAuditLog)
class KioskAuditLogAdmin(admin.ModelAdmin):
    list_display = ("event", "request_id", "stay_id", "created_at")
    list_filter = ("event",)
    readonly_fields = ("stay_id", "request_id", "event", "details", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(RealtimeSession)
class RealtimeSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "stay_id", "state", "last_activity_at", "expires_at")
    list_filter = ("state",)
    readonly_fields = (
        "id",
        "stay_id",
        "state",
        "created_at",
        "last_activity_at",
        "expires_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(StaffRequest)
class StaffRequestAdmin(admin.ModelAdmin):
    list_display = (
        "local_reference",
        "service",
        "urgency",
        "delivery_status",
        "delivery_attempts",
        "created_at",
    )
    list_filter = ("service", "urgency", "delivery_status")
    search_fields = ("local_reference", "details", "request_id")
    readonly_fields = (
        "stay_id",
        "request_id",
        "local_reference",
        "delivery_attempts",
        "created_at",
        "updated_at",
    )


class RemoteTemplateButtonInline(admin.TabularInline):
    model = RemoteTemplateButton
    extra = 1
    fields = ("key", "label", "icon", "row", "column", "sort_order", "requires_confirmation")


@admin.register(RemoteTemplate)
class RemoteTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "category", "is_active", "button_count", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (RemoteTemplateButtonInline,)

    @admin.display(description="Buttons")
    def button_count(self, obj):
        return obj.buttons.count()


class RemoteButtonForm(forms.ModelForm):
    class Meta:
        model = RemoteButton
        fields = (
            "remote",
            "key",
            "label",
            "icon",
            "sort_order",
            "row",
            "column",
            "command_url",
            "ir_id",
            "frequency",
            "raw",
            "is_active",
            "requires_confirmation",
        )
        widgets = {
            "command_url": forms.TextInput(attrs={"placeholder": "http://controller-ip/ir"}),
            "raw": forms.Textarea(attrs={"rows": 4, "placeholder": "[9000, 4500, 560, ...]"}),
        }

    def clean_command_url(self):
        value = (self.cleaned_data.get("command_url") or "").strip()
        if value:
            validate_command_url(value)
        return value

    def clean(self):
        cleaned_data = super().clean()
        raw = cleaned_data.get("raw")
        if raw:
            try:
                validate_ir_command(
                    cleaned_data.get("ir_id"),
                    cleaned_data.get("frequency"),
                    raw,
                )
            except ValidationError as exc:
                self.add_error("raw", exc)
        return cleaned_data


class RemoteButtonInline(admin.StackedInline):
    model = RemoteButton
    form = RemoteButtonForm
    extra = 1
    verbose_name_plural = "RAW remote buttons"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("label", "key", "icon"),
                    ("is_active", "requires_confirmation"),
                ),
            },
        ),
        (
            "IR command",
            {
                "fields": (
                    "command_url",
                    ("ir_id", "frequency"),
                    "raw",
                    ("resolved_endpoint", "test_link"),
                ),
            },
        ),
        (
            "Button position",
            {
                "fields": (("row", "column", "sort_order"),),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("resolved_endpoint", "test_link")

    @admin.display(description="Resolved endpoint")
    def resolved_endpoint(self, obj):
        return obj.target_command_url if obj.pk else "—"

    @admin.display(description="Test")
    def test_link(self, obj):
        if not obj.pk or not obj.is_configured:
            return "—"
        url = reverse("admin:kiosk_agent_remotebutton_test", args=[obj.pk])
        return format_html('<a class="button" href="{}">Test</a>', url)


class AddRemoteFromTemplateForm(forms.Form):
    template = forms.ModelChoiceField(
        queryset=RemoteTemplate.objects.filter(is_active=True),
        label="Template",
    )
    name = forms.CharField(max_length=120)
    slug = forms.SlugField(max_length=120, required=False)
    location = forms.CharField(max_length=120, required=False)
    device_name = forms.CharField(
        max_length=120,
        required=False,
        help_text="Exact DEVICE_NAME configured on the ESP32.",
    )
    guest_visible = forms.BooleanField(required=False, initial=True)
    voice_enabled = forms.BooleanField(required=False, initial=False)


class RemoteControlAdminForm(forms.ModelForm):
    class Meta:
        model = RemoteControl
        fields = (
            "name",
            "slug",
            "location",
            "device_name",
            "device_ip",
            "device_type",
            "brand",
            "protocol",
            "protocol_model",
            "template",
            "template_slug",
            "is_active",
            "voice_enabled",
            "guest_visible",
            "sort_order",
        )
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Living Room AC"}),
            "location": forms.TextInput(attrs={"placeholder": "e.g. Living room"}),
            "device_name": forms.TextInput(attrs={"placeholder": "ESP32 IR Controller"}),
        }
        help_texts = {
            "device_type": "Choose Air conditioner for state-based Gree, Haier, Midea, or Hisense control. Choose Raw IR for TVs, fans, and learned remotes.",
            "brand": "The appliance brand. This does not replace the protocol selection.",
            "protocol": "The exact IR protocol the selected ESP32 should transmit.",
            "protocol_model": "Use Default unless you know the remote/model variant.",
            "guest_visible": "Show this remote to guests on the kiosk.",
            "voice_enabled": "Allow voice commands to control this remote.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["device_name"].initial = "ESP32 IR Controller"
            self.fields["protocol_model"].initial = RemoteControl.ProtocolModel.DEFAULT

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("device_type") != RemoteControl.DeviceType.AC:
            cleaned_data["brand"] = ""
            cleaned_data["protocol"] = ""
            cleaned_data["protocol_model"] = ""
            return cleaned_data

        required = {
            "brand": "Choose the AC brand.",
            "protocol": "Choose the exact AC protocol.",
            "protocol_model": "Choose Default or the matching model variant.",
            "device_name": "Enter the ESP32 DEVICE_NAME used for discovery and synchronization.",
        }
        for field, message in required.items():
            if cleaned_data.get(field) in (None, ""):
                self.add_error(field, message)
        return cleaned_data


class ACStateInline(admin.StackedInline):
    model = ACState
    extra = 0
    max_num = 1
    verbose_name_plural = "Last state confirmed by the ESP32"
    fieldsets = (
        (
            "Main controls",
            {"fields": (("power", "mode", "temperature", "fan"),)},
        ),
        (
            "Extra features",
            {
                "fields": (
                    ("swing_vertical", "swing_horizontal"),
                    ("turbo", "sleep", "eco", "quiet"),
                    ("light", "x_fan"),
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Synchronization",
            {
                "fields": (("state_version", "esp32_updated_at", "updated_at"),),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("state_version", "esp32_updated_at", "updated_at")


@admin.register(RemoteControl)
class RemoteControlAdmin(admin.ModelAdmin):
    form = RemoteControlAdminForm
    list_display = (
        "name",
        "device_kind",
        "location",
        "brand_and_protocol",
        "controller_status",
        "setup_status",
        "is_active",
        "guest_visible",
        "sort_order",
        "updated_at",
    )
    list_filter = ("device_type", "brand", "is_active", "guest_visible", "voice_enabled")
    search_fields = ("name", "slug", "location", "device_name", "device_ip")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = (
        "template",
        "template_slug",
        "device_ip",
        "device_last_seen_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Remote details",
            {
                "fields": (
                    ("name", "slug"),
                    ("location", "device_type"),
                ),
                "description": "Start with a friendly name and choose how this appliance is controlled.",
            },
        ),
        (
            "ESP32 controller",
            {
                "fields": (
                    "device_name",
                    ("device_ip", "device_last_seen_at"),
                ),
                "description": "DEVICE_NAME links this remote to the ESP32. Use the list action “Sync selected device IPs” after saving.",
            },
        ),
        (
            "Air-conditioner configuration",
            {
                "fields": (
                    ("brand", "protocol"),
                    "protocol_model",
                ),
                "classes": ("ac-config",),
                "description": "Only used for Air conditioner remotes. Django sends this configuration to the ESP32 selected by DEVICE_NAME.",
            },
        ),
        (
            "Availability",
            {
                "fields": (
                    ("is_active", "guest_visible", "voice_enabled"),
                    "sort_order",
                ),
            },
        ),
        (
            "Template and history",
            {
                "fields": (
                    ("template", "template_slug"),
                    ("created_at", "updated_at"),
                ),
                "classes": ("collapse",),
            },
        ),
    )
    change_list_template = "admin/kiosk_agent/remotecontrol/change_list.html"
    change_form_template = "admin/kiosk_agent/remotecontrol/change_form.html"
    actions = ("sync_device_ips",)

    def get_inlines(self, request, obj):
        if obj is None:
            return ()
        if obj.device_type == RemoteControl.DeviceType.AC:
            return (ACStateInline,)
        return (RemoteButtonInline,)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.device_type == RemoteControl.DeviceType.AC:
            ACState.objects.get_or_create(device=obj)

    def response_add(self, request, obj, post_url_continue=None):
        if "_addanother" in request.POST:
            return super().response_add(request, obj, post_url_continue)
        self.message_user(
            request,
            "Remote created. Complete its AC state or RAW buttons below.",
            level=messages.SUCCESS,
        )
        return HttpResponseRedirect(
            reverse("admin:kiosk_agent_remotecontrol_change", args=[obj.pk])
        )

    @admin.display(description="Type", ordering="device_type")
    def device_kind(self, obj):
        return obj.get_device_type_display()

    @admin.display(description="AC protocol")
    def brand_and_protocol(self, obj):
        if obj.device_type != RemoteControl.DeviceType.AC:
            return "Raw IR"
        brand = obj.get_brand_display() or "—"
        protocol = obj.get_protocol_display() or "—"
        return f"{brand} / {protocol}"

    @admin.display(description="Controller")
    def controller_status(self, obj):
        if obj.device_ip:
            return format_html('<span class="status-ready">● {}</span>', obj.device_ip)
        return format_html('<span class="status-warning">● IP not synced</span>')

    @admin.display(description="Setup")
    def setup_status(self, obj):
        if obj.device_type == RemoteControl.DeviceType.AC:
            ready = all((obj.brand, obj.protocol, obj.protocol_model, obj.device_name))
            label = "Ready" if ready else "Needs AC setup"
        else:
            ready = obj.configured_count > 0
            label = f"{obj.configured_count}/{obj.active_button_count} buttons"
        css_class = "status-ready" if ready else "status-warning"
        return format_html('<span class="{}">{}</span>', css_class, label)

    @admin.display(description="Configured")
    def configured_badge(self, obj):
        total = obj.active_button_count
        done = obj.configured_count
        return f"{done}/{total}"

    @admin.action(description="Sync selected device IPs by DEVICE_NAME")
    def sync_device_ips(self, request, queryset):
        try:
            devices = discover_identity_devices()
        except DeviceDiscoveryError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return

        devices_by_name = {}
        for device in devices:
            key = device["name"].strip().casefold()
            devices_by_name.setdefault(key, []).append(device)

        synced = 0
        missing = []
        ambiguous = []
        now = timezone.now()

        with transaction.atomic():
            for remote in queryset:
                key = remote.device_name.strip().casefold()
                if not key:
                    missing.append(f"{remote.name} (DEVICE_NAME is blank)")
                    continue

                matches = devices_by_name.get(key, [])
                if not matches:
                    missing.append(remote.device_name)
                    continue
                if len(matches) > 1:
                    ambiguous.append(remote.device_name)
                    continue

                remote.device_ip = matches[0]["ip"]
                remote.device_last_seen_at = now
                remote.save(update_fields=("device_ip", "device_last_seen_at", "updated_at"))
                synced += 1

        if synced:
            self.message_user(
                request,
                f"Synced {synced} remote control device IP(s).",
                level=messages.SUCCESS,
            )
        if missing:
            self.message_user(
                request,
                "Not found: " + ", ".join(missing),
                level=messages.WARNING,
            )
        if ambiguous:
            self.message_user(
                request,
                "Duplicate DEVICE_NAME responses: " + ", ".join(ambiguous),
                level=messages.ERROR,
            )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "add-from-template/",
                self.admin_site.admin_view(self.add_from_template_view),
                name="kiosk_agent_remotecontrol_add_from_template",
            ),
        ]
        return custom + urls

    def add_from_template_view(self, request):
        if not self.has_add_permission(request):
            return HttpResponseForbidden("Permission denied.")
        if request.method == "POST":
            form = AddRemoteFromTemplateForm(request.POST)
            if form.is_valid():
                template = form.cleaned_data["template"]
                name = form.cleaned_data["name"]
                slug = form.cleaned_data["slug"] or slugify(name)
                if not slug:
                    form.add_error("slug", "Could not generate a slug from the name.")
                elif RemoteControl.objects.filter(slug=slug).exists():
                    form.add_error("slug", "A remote with this slug already exists.")
                else:
                    with transaction.atomic():
                        remote = RemoteControl.objects.create(
                            name=name,
                            slug=slug,
                            location=form.cleaned_data["location"],
                            device_name=form.cleaned_data["device_name"],
                            template=template,
                            template_slug=template.slug,
                            guest_visible=form.cleaned_data["guest_visible"],
                            voice_enabled=form.cleaned_data["voice_enabled"],
                        )
                        RemoteButton.objects.bulk_create([
                            RemoteButton(
                                remote=remote,
                                key=btn.key,
                                label=btn.label,
                                icon=btn.icon,
                                sort_order=btn.sort_order,
                                row=btn.row,
                                column=btn.column,
                                requires_confirmation=btn.requires_confirmation,
                                command_url="",
                                is_active=True,
                            )
                            for btn in template.buttons.all()
                        ])
                    self.message_user(
                        request,
                        f"Created remote “{remote.name}” with {remote.buttons.count()} buttons. Add IR commands next.",
                        messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse("admin:kiosk_agent_remotecontrol_change", args=[remote.pk])
                    )
        else:
            form = AddRemoteFromTemplateForm(initial={"guest_visible": True})
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "form": form,
            "title": "Add remote from template",
        }
        return render(request, "admin/kiosk_agent/remotecontrol/add_from_template.html", context)


@admin.register(RemoteButton)
class RemoteButtonAdmin(admin.ModelAdmin):
    list_display = ("label", "remote", "key", "is_configured_display", "is_active", "requires_confirmation")
    list_filter = ("is_active", "requires_confirmation", "remote")
    search_fields = ("label", "key", "remote__name")
    form = RemoteButtonForm

    @admin.display(description="Configured", boolean=True)
    def is_configured_display(self, obj):
        return obj.is_configured

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:button_id>/test/",
                self.admin_site.admin_view(self.test_button_view),
                name="kiosk_agent_remotebutton_test",
            ),
        ]
        return custom + urls

    def test_button_view(self, request, button_id):
        button = get_object_or_404(RemoteButton.objects.select_related("remote"), pk=button_id)
        if not self.has_change_permission(request, button):
            return HttpResponseForbidden("Permission denied.")
        if request.method == "POST":
            try:
                result = press_remote_button(button.pk, source="admin")
                self.message_user(
                    request,
                    f"Success for “{button.remote.name} / {button.label}”"
                    + (f" (target {result.get('target')})" if result.get("target") else ""),
                    messages.SUCCESS,
                )
            except RemoteCommandError as exc:
                self.message_user(
                    request,
                    f"Failed: {exc.message} ({exc.code})",
                    messages.ERROR,
                )
            return HttpResponseRedirect(
                reverse("admin:kiosk_agent_remotecontrol_change", args=[button.remote_id])
            )
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "button": button,
            "title": f"Test button: {button.label}",
        }
        return render(request, "admin/kiosk_agent/remotebutton/test_confirm.html", context)
