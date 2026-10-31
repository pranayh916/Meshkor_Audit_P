from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AuditEvent, ProcessingJob, ReportRecord, SourceFile


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class ProtectedRootAdmin(UserAdmin):
    """Keep system-owner superuser accounts from routine staff changes."""
    actions = tuple(action for action in UserAdmin.actions if action != "delete_selected")

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.is_superuser:
            fields.extend(field for field in (
                "username", "is_active", "is_staff", "is_superuser", "groups",
                "user_permissions",
            ) if field not in fields)
        return fields


@admin.register(SourceFile)
class SourceFileAdmin(admin.ModelAdmin):
    list_display = ("source_key", "relative_path", "status", "reporting_period", "sha256", "created_at")
    list_filter = ("source_key", "status")
    search_fields = ("relative_path", "sha256", "source_url")
    readonly_fields = ("created_at",)


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("job_type", "status", "progress", "requested_by", "created_at")
    list_filter = ("job_type", "status")
    readonly_fields = ("created_at", "started_at", "finished_at")


@admin.register(ReportRecord)
class ReportRecordAdmin(admin.ModelAdmin):
    list_display = ("name", "report_type", "status", "generated_at", "approved_by", "approved_at")
    list_filter = ("report_type", "status")
    readonly_fields = ("generated_at",)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "entity_type", "entity_id", "created_at")
    list_filter = ("action", "entity_type")
    search_fields = ("entity_id", "actor__username")
    readonly_fields = ("actor", "action", "entity_type", "entity_id", "details", "created_at")
