from django.contrib import admin

from .models import (
    ChaletConfig,
    KioskAuditLog,
    KioskMessage,
    RealtimeSession,
    StaffRequest,
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
