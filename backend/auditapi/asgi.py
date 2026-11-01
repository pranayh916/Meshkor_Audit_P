"""Django's native ASGI application, served by Uvicorn."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditapi.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()
