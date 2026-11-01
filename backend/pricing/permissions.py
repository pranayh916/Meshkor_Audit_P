from rest_framework.permissions import BasePermission


ADMIN_GROUP = "Admin"
VIEWER_GROUP = "Viewer"
# Kept as an import alias for older modules. It is not a separate role.
ANALYST_GROUP = ADMIN_GROUP


def has_any_role(user, roles: set[str]) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def _log_read(request):
    if request.method != "GET" or not request.user.is_authenticated:
        return
    from .models import AuditEvent

    path = request.path
    downloadable = any(marker in path for marker in ("/exports/", "/pdf", ".csv", ".xlsx"))
    AuditEvent.objects.create(
        actor=request.user,
        action="report_downloaded" if downloadable else "data_viewed",
        entity_type="api_resource",
        entity_id=path[:120],
        details={"method": "GET", "path": path[:500]},
    )


class CanView(BasePermission):
    message = "Sign in with an Admin or Viewer account."

    def has_permission(self, request, view):
        allowed = has_any_role(request.user, {ADMIN_GROUP, VIEWER_GROUP})
        if allowed:
            _log_read(request)
        return allowed


class CanAnalyze(BasePermission):
    message = "This action requires the Admin role."

    def has_permission(self, request, view):
        allowed = has_any_role(request.user, {ADMIN_GROUP})
        if allowed:
            _log_read(request)
        return allowed


class CanAdminister(BasePermission):
    message = "This action requires the Admin role."

    def has_permission(self, request, view):
        allowed = has_any_role(request.user, {ADMIN_GROUP})
        if allowed:
            _log_read(request)
        return allowed
