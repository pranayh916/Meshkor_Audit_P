from django.contrib import admin
from django.urls import include, path
from pricing.views import health

urlpatterns = [
    path("admin/", admin.site.urls, name="django_admin_console"),
    path("api/system/health-check/", health, name="unversioned_api_system_health_check"),
    path("api/health/", health, name="legacy_api_health_check"),
    path("api/v1/", include("pricing.v1_urls")),
    path("api/", include("pricing.urls")),
]
