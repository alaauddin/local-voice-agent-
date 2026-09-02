from django.contrib import admin

from .models import ChaletConfig, KioskAuditLog, KioskMessage


@admin.register(ChaletConfig)
class ChaletConfigAdmin(admin.ModelAdmin):
    readonly_fields = ("current_stay_id", "updated_at")
    fieldsets = (
        (None, {"fields": ("chalet_name", "chalet_number", "persona_name", "welcome_message")}),
        ("Content", {"fields": ("property_facts", "enabled_services", "emergency_contact", "llm_model")}),
        ("SaaS Integration", {"fields": ("saas_enabled", "saas_integration_url", "saas_integration_token", "saas_tenant_subdomain", "saas_timeout_seconds")}),
        ("System", {"fields": ("is_active", "current_stay_id", "updated_at")}),
    )

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
