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
        fields = "__all__"

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


class RemoteButtonInline(admin.TabularInline):
    model = RemoteButton
    form = RemoteButtonForm
    extra = 0
    fields = (
        "key",
        "label",
        "icon",
        "row",
        "column",
        "sort_order",
        "command_url",
        "ir_id",
        "frequency",
        "raw",
        "is_active",
        "requires_confirmation",
        "resolved_endpoint",
        "test_link",
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


@admin.register(RemoteControl)
class RemoteControlAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "location",
        "device_name",
        "device_ip",
        "configured_badge",
        "is_active",
        "guest_visible",
        "voice_enabled",
        "sort_order",
        "updated_at",
    )
    list_filter = ("is_active", "guest_visible", "voice_enabled")
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
    inlines = (RemoteButtonInline,)
    change_list_template = "admin/kiosk_agent/remotecontrol/change_list.html"
    actions = ("sync_device_ips",)

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
