import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone as datetime_timezone

import jwt

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ImproperlyConfigured
from django.core.cache import cache
from django.core import signing
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

from .models import AdminOTPDevice, AuditEvent, ReportRecord
from .otp import decrypt_secret, encrypt_secret, new_secret, provisioning_uri, verify_code
from .permissions import ADMIN_GROUP, VIEWER_GROUP, CanAdminister, has_any_role


def _role_names(user):
    if user.is_superuser:
        return [ADMIN_GROUP]
    return sorted(user.groups.filter(name__in=(ADMIN_GROUP, VIEWER_GROUP))
                  .values_list("name", flat=True))


def _user_payload(user):
    return {
        "id": user.pk,
        "username": user.get_username(),
        "display_name": user.get_full_name() or user.get_username(),
        "email": user.email,
        "roles": _role_names(user),
    }


def _access_token(user):
    now = datetime.now(datetime_timezone.utc)
    return jwt.encode({
        "sub": str(user.pk),
        "iat": now,
        "exp": now + timedelta(seconds=settings.JWT_ACCESS_TOKEN_SECONDS),
        "type": "access",
    }, settings.SECRET_KEY, algorithm="HS256")


def _attempt_key(username, ip):
    raw = f"{username.casefold()}|{ip}".encode("utf-8")
    return "login-fail:" + hashlib.sha256(raw).hexdigest()


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf(request):
    return Response({"csrfToken": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def login_view(request):
    username = str(request.data.get("username", "")).strip()
    password = request.data.get("password", "")
    ip = request.META.get("REMOTE_ADDR", "unknown")
    key = _attempt_key(username, ip)
    now = time.time()
    stored_attempt = cache.get(key, 0)
    if isinstance(stored_attempt, dict):
        failures = int(stored_attempt.get("count", 0))
        expires_at = float(stored_attempt.get("expires_at", now))
    else:
        failures = int(stored_attempt or 0)
        expires_at = now + settings.LOGIN_WINDOW_SECONDS
    if failures >= settings.LOGIN_MAX_FAILURES:
        retry_after = max(1, int(expires_at - now))
        return Response({"error": "Too many failed sign-in attempts. Wait for the cooldown to expire, then try again.",
                         "retry_after_seconds": retry_after}, status=429)

    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        if failures == 0:
            expires_at = now + settings.LOGIN_WINDOW_SECONDS
        failures += 1
        cache.set(key, {"count": failures, "expires_at": expires_at},
                  timeout=max(1, int(expires_at - now)))
        AuditEvent.objects.create(action="login_failed", entity_type="user", entity_id=username[:120])
        return Response({"error": "Invalid username or password."}, status=401)
    if not has_any_role(user, {ADMIN_GROUP, VIEWER_GROUP}):
        return Response({"error": "This account has no application role."}, status=403)

    cache.delete(key)
    device = AdminOTPDevice.objects.filter(user=user, enabled=True).first()
    if not device:
        challenge = signing.dumps({"user_id": user.pk, "purpose": "enroll"}, salt="user-otp-login")
        AuditEvent.objects.create(actor=user, action="otp_enrollment_required", entity_type="user",
                                  entity_id=str(user.pk))
        return Response({"otp_setup_required": True, "challenge": challenge, "expires_in": 600})
    if device:
        challenge = signing.dumps({"user_id": user.pk, "purpose": "login"}, salt="user-otp-login")
        AuditEvent.objects.create(actor=user, action="otp_challenge_issued", entity_type="user",
                                  entity_id=str(user.pk))
        return Response({"otp_required": True, "challenge": challenge, "expires_in": 300})

    login(request, user)
    AuditEvent.objects.create(actor=user, action="login_succeeded", entity_type="user", entity_id=str(user.pk))
    return Response({"user": _user_payload(user), "access": _access_token(user),
                     "token_type": "Bearer", "expires_in": settings.JWT_ACCESS_TOKEN_SECONDS})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_otp_status(request):
    device = AdminOTPDevice.objects.filter(user=request.user).first()
    return Response({"enabled": bool(device and device.enabled),
                     "setup_pending": bool(device and not device.enabled),
                     "recovery_codes_remaining": len(device.recovery_code_hashes) if device else 0})


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def admin_otp_setup(request):
    user = request.user if request.user.is_authenticated else _challenge_user(
        request.data.get("challenge"), "enroll")
    if not user:
        return Response({"error": "This authenticator setup challenge expired. Sign in again."}, status=401)
    if not has_any_role(user, {ADMIN_GROUP, VIEWER_GROUP}):
        return Response({"error": "This account has no application role."}, status=403)
    device = AdminOTPDevice.objects.filter(user=user).first()
    if device and device.enabled:
        return Response({"error": "Authenticator OTP is already enabled for this account."}, status=409)
    secret = new_secret()
    try:
        stored_secret = encrypt_secret(secret)
    except ImproperlyConfigured as exc:
        return Response({"error": str(exc)}, status=503)
    if device:
        device.secret = stored_secret
        device.last_used_step = -1
        device.recovery_code_hashes = []
        device.save(update_fields=["secret", "last_used_step", "recovery_code_hashes", "updated_at"])
    else:
        AdminOTPDevice.objects.create(user=user, secret=stored_secret)
    AuditEvent.objects.create(actor=user, action="otp_setup_started",
                              entity_type="user", entity_id=str(user.pk))
    return Response({"secret": secret,
                     "otpauth_url": provisioning_uri(secret, user.get_username())})


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
@transaction.atomic
def admin_otp_confirm(request):
    user = request.user if request.user.is_authenticated else _challenge_user(
        request.data.get("challenge"), "enroll")
    if not user:
        return Response({"error": "This authenticator setup challenge expired. Sign in again."}, status=401)
    challenge = str(request.data.get("challenge", ""))
    ip = request.META.get("REMOTE_ADDR", "unknown")
    attempt_key = "otp-enroll-fail:" + hashlib.sha256(
        f"{challenge or user.pk}|{ip}".encode("utf-8")).hexdigest()
    failures = cache.get(attempt_key, 0)
    if failures >= min(settings.LOGIN_MAX_FAILURES, 5):
        return Response({"error": "Too many invalid authenticator setup codes. Sign in again to retry."}, status=429)
    device = AdminOTPDevice.objects.select_for_update().filter(user=user, enabled=False).first()
    if not device:
        return Response({"error": "Start authenticator setup first."}, status=409)
    step = verify_code(decrypt_secret(device.secret), request.data.get("code"))
    if step is None:
        cache.set(attempt_key, failures + 1, 300)
        AuditEvent.objects.create(actor=user, action="otp_verification_failed",
                                  entity_type="user", entity_id=str(user.pk))
        return Response({"error": "That code is invalid or expired. Try the latest code from your authenticator."}, status=400)
    recovery_codes = [secrets.token_hex(6).upper() for _ in range(10)]
    device.enabled = True
    device.last_used_step = step
    device.recovery_code_hashes = [make_password(code) for code in recovery_codes]
    device.save(update_fields=["enabled", "last_used_step", "recovery_code_hashes", "updated_at"])
    cache.delete(attempt_key)
    AuditEvent.objects.create(actor=user, action="otp_enabled",
                              entity_type="user", entity_id=str(user.pk))
    response = {"enabled": True, "recovery_codes": recovery_codes}
    if not request.user.is_authenticated:
        login(request, user)
        response.update({"user": _user_payload(user), "access": _access_token(user),
                         "token_type": "Bearer", "expires_in": settings.JWT_ACCESS_TOKEN_SECONDS})
        AuditEvent.objects.create(actor=user, action="login_succeeded", entity_type="user",
                                  entity_id=str(user.pk), details={"otp": "enrollment"})
    return Response(response)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def admin_otp_disable(request):
    return Response({"error": "Authenticator OTP is required for every account and cannot be disabled."}, status=403)


def _challenge_user(challenge, purpose):
    try:
        payload = signing.loads(str(challenge or ""), salt="user-otp-login", max_age=600)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if payload.get("purpose") != purpose:
        return None
    return get_user_model().objects.filter(pk=payload.get("user_id"), is_active=True).first()


@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def complete_otp_login(request):
    challenge = str(request.data.get("challenge", ""))
    ip = request.META.get("REMOTE_ADDR", "unknown")
    attempt_key = "otp-login-fail:" + hashlib.sha256(f"{challenge}|{ip}".encode("utf-8")).hexdigest()
    failures = cache.get(attempt_key, 0)
    if failures >= min(settings.LOGIN_MAX_FAILURES, 5):
        return Response({"error": "Too many invalid OTP attempts. Sign in again to retry."}, status=429)
    try:
        payload = signing.loads(challenge, salt="user-otp-login", max_age=300)
    except (signing.BadSignature, signing.SignatureExpired):
        return Response({"error": "This sign-in challenge expired. Enter your password again."}, status=401)
    if payload.get("purpose") != "login":
        return Response({"error": "This sign-in challenge is invalid. Enter your password again."}, status=401)
    user = get_user_model().objects.filter(pk=payload.get("user_id"), is_active=True).first()
    if not user:
        return Response({"error": "This authenticator sign-in is no longer valid. Enter your password again."}, status=401)
    with transaction.atomic():
        device = AdminOTPDevice.objects.select_for_update().filter(user=user, enabled=True).first()
        if not device:
            return Response({"error": "This authenticator sign-in is no longer valid. Enter your password again."}, status=401)
        step = verify_code(decrypt_secret(device.secret), request.data.get("code"))
        recovery_hash_index = None
        supplied_recovery = str(request.data.get("recovery_code", "")).strip().upper()
        if step is None and supplied_recovery:
            for i, password_hash in enumerate(device.recovery_code_hashes):
                if check_password(supplied_recovery, password_hash):
                    recovery_hash_index = i
                    break
        if (step is None and recovery_hash_index is None) or (step is not None and step <= device.last_used_step):
            cache.set(attempt_key, failures + 1, 300)
            AuditEvent.objects.create(actor=user, action="otp_verification_failed", entity_type="user",
                                      entity_id=str(user.pk))
            return Response({"error": "That code is invalid, expired, or already used."}, status=401)
        if recovery_hash_index is not None:
            hashes = list(device.recovery_code_hashes)
            hashes.pop(recovery_hash_index)
            device.recovery_code_hashes = hashes
            device.save(update_fields=["recovery_code_hashes", "updated_at"])
            auth_method = "recovery_code"
        else:
            device.last_used_step = step
            device.save(update_fields=["last_used_step", "updated_at"])
            auth_method = "totp"
    cache.delete(attempt_key)
    login(request, user)
    AuditEvent.objects.create(actor=user, action="login_succeeded", entity_type="user",
                              entity_id=str(user.pk), details={"otp": auth_method})
    return Response({"user": _user_payload(user), "access": _access_token(user),
                     "token_type": "Bearer", "expires_in": settings.JWT_ACCESS_TOKEN_SECONDS})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def refresh_access(request):
    """Issue a short-lived JWT using the existing HttpOnly Django login session."""
    return Response({"access": _access_token(request.user), "token_type": "Bearer",
                     "expires_in": settings.JWT_ACCESS_TOKEN_SECONDS})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    user = request.user
    AuditEvent.objects.create(actor=user, action="logout", entity_type="user", entity_id=str(user.pk))
    logout(request)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    if not request.user.is_authenticated:
        return Response({"authenticated": False})
    return Response({"authenticated": True, "user": _user_payload(request.user)})


def signoff_status():
    from . import data

    try:
        source_hash = data.comparison_sha256()
        info = data.run_info()
    except data.DataMissing:
        return {"signed": False, "generated_at": timezone.now().isoformat(), "source_hash": ""}
    report = ReportRecord.objects.filter(source_hash=source_hash, status="approved").first()
    return {
        "signed": report is not None,
        "generated_at": info.get("generated_at", timezone.now().isoformat()),
        "source_hash": source_hash,
        "approved_by": report.approved_by.get_username() if report and report.approved_by else None,
        "approved_at": report.approved_at.isoformat() if report and report.approved_at else None,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def signoff(request):
    from . import data

    if not has_any_role(request.user, {ADMIN_GROUP}):
        return Response({"error": "Only an Admin can approve reports."}, status=403)
    try:
        info = data.run_info()
        source_hash = data.comparison_sha256()
    except data.DataMissing as exc:
        return Response({"error": str(exc)}, status=503)
    report, _ = ReportRecord.objects.update_or_create(
        source_hash=source_hash,
        defaults={
            "name": f"Ohio infusion markup report {info.get('generated_at', '')[:10]}",
            "report_type": "ohio_market",
            "status": "approved",
            "approved_by": request.user,
            "approved_at": timezone.now(),
            "metadata": {"pipeline_generated_at": info.get("generated_at"), "drugs": info.get("drugs", [])},
        },
    )
    AuditEvent.objects.create(actor=request.user, action="report_approved", entity_type="report",
                              entity_id=str(report.pk), details={"source_hash": source_hash})
    return Response({"ok": True, "report_id": report.pk, **signoff_status()})
