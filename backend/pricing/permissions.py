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


class CanView(BasePermission):
    message = "Sign in with an Admin or Viewer account."

    def has_permission(self, request, view):
        return has_any_role(request.user, {ADMIN_GROUP, VIEWER_GROUP})


class CanAnalyze(BasePermission):
    message = "This action requires the Admin role."

    def has_permission(self, request, view):
        return has_any_role(request.user, {ADMIN_GROUP})


class CanAdminister(BasePermission):
    message = "This action requires the Admin role."

    def has_permission(self, request, view):
        return has_any_role(request.user, {ADMIN_GROUP})
