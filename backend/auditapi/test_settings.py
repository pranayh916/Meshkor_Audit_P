"""Isolated settings for automated tests; the app itself continues to use PostgreSQL."""
from .settings import *  # noqa: F403

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": ":memory:",
}}

# API tests create temporary users repeatedly; avoid production-strength hashing cost here.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
