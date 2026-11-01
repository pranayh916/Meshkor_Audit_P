"""Isolated settings for automated tests; operational records use SQLite."""
from .settings import *  # noqa: F403

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": ":memory:",
}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# API tests create temporary users repeatedly; avoid production-strength hashing cost here.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
