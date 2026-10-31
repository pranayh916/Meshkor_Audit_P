import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from pricing.otp import code_at, new_secret, provisioning_uri, verify_code


@pytest.fixture
def admin_client(db, built):
    user = get_user_model().objects.create_superuser(
        username="otp-test-admin", email="otp-test@example.invalid", password="test-only-password"
    )
    client = Client()
    client.force_login(user)
    return client


def test_totp_code_window_and_provisioning_uri():
    secret = new_secret()
    code, step = code_at(secret, timestamp=1_800_000_000)
    assert len(secret) == 32
    assert len(code) == 6 and verify_code(secret, code, timestamp=1_800_000_000) == step
    assert verify_code(secret, "abc123", timestamp=1_800_000_000) is None
    assert provisioning_uri(secret, "audit-admin").startswith("otpauth://totp/")


@override_settings(TOTP_ENCRYPTION_KEY="F5wrMMH6I5kTnhPaaWqFvxLQmNY4J5kmWh0-e4jxQYc=")
def test_admin_authenticator_is_required_after_password_and_code_cannot_replay(admin_client):
    setup = admin_client.post("/api/v1/auth/otp/setup/", "{}", content_type="application/json")
    assert setup.status_code == 200
    secret = setup.json()["secret"]

    confirm_code, _ = code_at(secret)
    confirmed = admin_client.post("/api/v1/auth/otp/confirm/", {"code": confirm_code})
    assert confirmed.status_code == 200
    recovery_codes = confirmed.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert admin_client.get("/api/v1/auth/otp/").json()["enabled"] is True

    user = get_user_model().objects.get(username="otp-test-admin")
    from pricing.models import AdminOTPDevice
    assert AdminOTPDevice.objects.get(user=user).secret.startswith("gAAAA")
    fresh_client = Client()
    password_response = fresh_client.post("/api/v1/auth/login/", {
        "username": user.username, "password": "test-only-password",
    }, content_type="application/json")
    assert password_response.status_code == 200
    assert password_response.json()["otp_required"] is True

    next_code, next_step = code_at(secret, time.time() + 30)
    assert next_step > verify_code(secret, confirm_code)
    challenge = password_response.json()["challenge"]
    verified = fresh_client.post("/api/v1/auth/otp/complete/", {
        "challenge": challenge, "code": next_code,
    }, content_type="application/json")
    assert verified.status_code == 200
    assert verified.json()["access"]
    replay = fresh_client.post("/api/v1/auth/otp/complete/", {
        "challenge": challenge, "code": next_code,
    }, content_type="application/json")
    assert replay.status_code == 401

    recovery_client = Client()
    recovery_challenge = recovery_client.post("/api/v1/auth/login/", {
        "username": user.username, "password": "test-only-password",
    }, content_type="application/json").json()["challenge"]
    recovered = recovery_client.post("/api/v1/auth/otp/complete/", {
        "challenge": recovery_challenge, "recovery_code": recovery_codes[0],
    }, content_type="application/json")
    assert recovered.status_code == 200
    duplicate_recovery = Client().post("/api/v1/auth/otp/complete/", {
        "challenge": recovery_challenge, "recovery_code": recovery_codes[0],
    }, content_type="application/json")
    assert duplicate_recovery.status_code == 401
