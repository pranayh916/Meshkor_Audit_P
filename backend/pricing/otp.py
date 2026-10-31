"""Small RFC 6238 TOTP implementation for administrator authenticator apps."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def code_at(secret: str, timestamp: int | float | None = None) -> tuple[str, int]:
    timestamp = time.time() if timestamp is None else timestamp
    step = int(timestamp // 30)
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}", step


def verify_code(secret: str, supplied: str, timestamp: int | float | None = None) -> int | None:
    value = str(supplied or "").strip()
    if len(value) != 6 or not value.isdigit():
        return None
    now = time.time() if timestamp is None else timestamp
    for delta in (-1, 0, 1):
        expected, step = code_at(secret, now + delta * 30)
        if hmac.compare_digest(expected, value):
            return step
    return None


def provisioning_uri(secret: str, username: str, issuer: str = "Infusion Audit") -> str:
    label = quote(f"{issuer}:{username}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            "&algorithm=SHA1&digits=6&period=30")


def encrypt_secret(secret: str) -> str:
    key = getattr(settings, "TOTP_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured("Set TOTP_ENCRYPTION_KEY before enabling authenticator OTP.")
    try:
        return Fernet(key.encode("ascii")).encrypt(secret.encode("ascii")).decode("ascii")
    except (ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured("TOTP_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def decrypt_secret(stored: str) -> str:
    """Decrypt current records and allow legacy Base32 seeds to be re-encrypted."""
    if not stored.startswith("gAAAA"):
        return stored
    key = getattr(settings, "TOTP_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured("Set the original TOTP_ENCRYPTION_KEY to verify authenticator codes.")
    try:
        return Fernet(key.encode("ascii")).decrypt(stored.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise ImproperlyConfigured("Unable to decrypt the saved authenticator seed; check TOTP_ENCRYPTION_KEY.") from exc
