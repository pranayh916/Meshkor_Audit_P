"""API tests: Django test client against the pipeline output built from TEST data."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"


@pytest.fixture
def client(built, db):
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditapi.settings")
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.test import Client
    user = get_user_model().objects.create_superuser(
        username="audit-test-admin", email="audit-test@example.invalid", password="test-only-password"
    )
    test_client = Client()
    test_client.force_login(user)
    return test_client


def test_meta(client):
    r = client.get("/api/meta").json()
    assert r["asp_quarters"] == ["2026Q3", "2026Q4"]
    assert r["hospitals"] == 4
    assert {s["status"] for s in r["statuses"]} >= {"ok", "unit_unresolved"}


def test_unified_health_endpoint(client):
    response = client.get("/api/health/")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"api": "ok", "database": "ok", "parquet": "ok"}


def test_backend_get_route_matrix_returns_expected_success(client):
    paths = [
        "/api/v1/dashboard/summary/",
        "/api/v1/dashboard/price-trends/",
        "/api/v1/sources/",
        "/api/v1/sources/jobs/",
        "/api/v1/reference/",
        "/api/v1/reference/asp/",
        "/api/v1/drug-scope/",
        "/api/v1/unit-validations/",
        "/api/v1/settings/",
        "/api/v1/audit-logs/",
        "/api/v1/hospital-files/",
        "/api/v1/hospitals/",
        "/api/v1/drugs/",
        "/api/v1/comparisons/",
        "/api/v1/comparisons.csv",
        "/api/v1/comparisons.xlsx",
        "/api/v1/quality/",
        "/api/v1/reports/",
        "/api/v1/reports/market.pdf",
        "/api/v1/auth/otp/",
    ]
    failures = []
    for path in paths:
        response = client.get(path)
        if response.status_code != 200:
                failures.append(f"{path}: {response.status_code} {response.content[:300]!r}")
    assert not failures, "; ".join(failures)


def test_protected_analytics_require_authentication(client):
    from django.test import Client

    anonymous = Client()
    for path in ("/api/v1/dashboard/summary/", "/api/v1/comparisons/",
                 "/api/v1/sources/", "/api/v1/audit-logs/"):
        assert anonymous.get(path).status_code == 401


def test_two_role_model_keeps_viewer_out_of_admin_operations(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client
    from pricing.permissions import VIEWER_GROUP

    viewer = get_user_model().objects.create_user(
        username="viewer-only", password="long-test-password-123", is_active=True
    )
    viewer.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    viewer_client = Client()
    viewer_client.force_login(viewer)
    assert viewer_client.get("/api/v1/dashboard/summary/").status_code == 200
    assert viewer_client.get("/api/v1/sources/").status_code == 403
    assert viewer_client.get("/api/v1/sources/jobs/").status_code == 403


def test_staff_flag_alone_does_not_grant_application_admin(client):
    from django.contrib.auth import get_user_model
    from django.test import Client

    staff = get_user_model().objects.create_user(
        username="staff-no-role", password="long-test-password-123", is_active=True,
        is_staff=True,
    )
    staff_client = Client()
    staff_client.force_login(staff)
    assert staff_client.get("/api/v1/dashboard/summary/").status_code == 403


def test_root_superuser_is_protected_in_django_admin(client):
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    from pricing.admin import ProtectedRootAdmin

    model = get_user_model()
    root = model.objects.create_superuser(
        username="root-admin-test", email="root-admin@example.invalid",
        password="test-only-root-password",
    )
    request = RequestFactory().get("/admin/auth/user/")
    request.user = model.objects.get(username="audit-test-admin")
    model_admin = ProtectedRootAdmin(model, admin.site)
    assert model_admin.has_delete_permission(request, root) is False
    assert "is_superuser" in model_admin.get_readonly_fields(request, root)
    assert "username" in model_admin.get_readonly_fields(request, root)


def test_root_admin_command_keeps_one_root_and_preserves_other_accounts(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import check_password
    from django.contrib.auth.models import Group
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from pricing.permissions import ADMIN_GROUP, VIEWER_GROUP

    User = get_user_model()
    root = User.objects.create_superuser(
        username="chosen-root", email="chosen-root@example.invalid", password="root-password-test"
    )
    old_admin = User.objects.create_superuser(
        username="old-admin", email="old-admin@example.invalid", password="old-admin-password-test"
    )
    old_admin.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    call_command("configure_root_admin", username="chosen-root", verbosity=0)

    root.refresh_from_db()
    old_admin.refresh_from_db()
    assert User.objects.filter(is_superuser=True).count() == 1
    assert root.is_superuser and root.is_active and root.is_staff
    assert not old_admin.is_superuser and old_admin.is_active and old_admin.is_staff
    assert old_admin.groups.filter(name=ADMIN_GROUP).exists()
    assert not old_admin.groups.filter(name=VIEWER_GROUP).exists()
    assert check_password("old-admin-password-test", old_admin.password)

    with pytest.raises(CommandError):
        call_command("configure_root_admin", username="missing-account", verbosity=0)


def test_initialize_roles_creates_only_admin_and_viewer_and_user_management_permissions(client):
    from django.contrib.auth.models import Group
    from django.core.management import call_command
    from pricing.permissions import ADMIN_GROUP, VIEWER_GROUP

    call_command("initialize_roles", verbosity=0)
    admin_group = Group.objects.get(name=ADMIN_GROUP)
    assert Group.objects.filter(name__in=(ADMIN_GROUP, VIEWER_GROUP)).count() == 2
    assert set(admin_group.permissions.values_list("codename", flat=True)) >= {
        "add_user", "change_user", "view_user", "add_group", "change_group", "view_group",
    }


def test_password_login_issues_jwt_and_session_can_refresh(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client

    user = get_user_model().objects.create_user(
        username="jwt-viewer", password="long-test-password-123", is_active=True
    )
    from pricing.permissions import VIEWER_GROUP
    user.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    fresh_client = Client()
    response = fresh_client.post("/api/v1/auth/login/", {
        "username": "jwt-viewer", "password": "long-test-password-123",
    }, content_type="application/json")
    assert response.status_code == 200
    token = response.json()["access"]
    assert response.json()["token_type"] == "Bearer"
    assert fresh_client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {token}").json()["authenticated"]

    # The HttpOnly Django session is the refresh credential and survives a page reload.
    refresh = fresh_client.post("/api/v1/auth/refresh/", "{}", content_type="application/json")
    assert refresh.status_code == 200
    assert refresh.json()["access"]

    token_only = Client()
    rejected = token_only.post("/api/v1/auth/refresh/", "{}", content_type="application/json",
                               HTTP_AUTHORIZATION=f"Bearer {token}")
    assert rejected.status_code in {401, 403}


def test_password_login_requires_csrf_for_browser_sessions(client):
    from django.test import Client

    protected = Client(enforce_csrf_checks=True)
    csrf_response = protected.get("/api/v1/auth/csrf/")
    token = csrf_response.cookies["csrftoken"].value
    credentials = {"username": "audit-test-admin", "password": "test-only-password"}
    assert protected.post("/api/v1/auth/login/", credentials).status_code == 403
    accepted = protected.post("/api/v1/auth/login/", credentials, HTTP_X_CSRFTOKEN=token)
    assert accepted.status_code == 200


def test_invalid_bearer_token_is_rejected(client):
    response = client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION="Bearer not-a-jwt")
    assert response.status_code == 401


def test_drugs_headline_uses_ok_rows_only(client):
    rows = {d["hcpcs"]: d for d in client.get("/api/drugs").json()}
    assert set(rows) == {"J9271", "J9299", "J2350", "J1745", "J0897"}
    k = rows["J9271"]
    assert k["asp_payment_limit"] == 60.0 and k["asp_quarter"] == "2026Q4"
    # negotiated_dollar ok rows for J9271: 3.0 (tall), 4.1667 (NDC), 3.0, 2.0 (wide), 2.0 (json)
    assert k["rates"] == 5
    assert k["median_markup"] == pytest.approx(3.0)
    assert rows["J2350"]["rates"] == 0 and rows["J2350"]["review_rows"] == 1
    assert rows["J9299"]["median_markup"] is None


def test_drug_detail(client):
    d = client.get("/api/drugs/J9271").json()
    assert [a["quarter"] for a in d["asp"]] == ["2026Q3", "2026Q4"]
    assert len(d["hospitals"]) == 3
    assert client.get("/api/drugs/J0000").status_code == 404


def test_rates_filter_and_sort(client):
    r = client.get("/api/rates", {"hcpcs": "J9271", "price_type": "negotiated_dollar",
                                  "status": "ok", "sort": "markup_multiple"}).json()
    assert r["total"] == 5
    m = [x["markup_multiple"] for x in r["rows"]]
    assert m == sorted(m, reverse=True)
    # unsafe sort value falls back to markup_multiple
    assert client.get("/api/rates", {"sort": "1; DROP TABLE x"}).status_code == 200
    assert client.get("/api/rates", {"limit": "many"}).status_code == 400


def test_invalid_pagination_is_a_client_error(client):
    assert client.get("/api/v1/reference/asp/", {"limit": "many"}).status_code == 400
    assert client.get("/api/v1/reference/asp/", {"offset": "many"}).status_code == 400
    assert client.get("/api/v1/sources/jobs/", {"limit": "many"}).status_code == 400
    assert client.get("/api/v1/reports/", {"limit": "many"}).status_code == 400
    assert client.get("/api/v1/audit-logs/", {"limit": "many"}).status_code == 400


def test_csv_export(client):
    r = client.get("/api/rates.csv", {"hcpcs": "J1745"})
    assert r.status_code == 200
    body = r.content.decode()
    assert body.startswith("# Infusion Drug Markup Audit export")
    assert "source_sha256" in body


def test_excel_comparison_export_is_a_real_workbook(client):
    response = client.get("/api/v1/comparisons.xlsx")
    assert response.status_code == 200
    content = b"".join(response.streaming_content)
    assert content.startswith(b"PK")
    assert response["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert int(response["X-Export-Records"]) > 0


def test_hospital_detail_and_quality(client):
    hs = client.get("/api/hospitals").json()
    key = hs[0]["hospital_key"]
    d = client.get(f"/api/hospitals/{key}").json()
    assert d["hospital_key"] == key and d["drugs"]
    assert len(client.get("/api/quality").json()) == 4


def test_hospital_inventory_includes_files_without_comparison_rows(client, built):
    import polars as pl

    path = built / "data/hpt/norm/hpt_file_quality.parquet"
    quality = pl.read_parquet(path)
    extra = {name: None for name in quality.columns}
    extra.update({"system": "test_system", "source_file": "data/raw/hospital_mrf/test_system/empty/empty.csv",
                  "source_member": "empty.csv", "source_sha256": "f" * 64,
                  "hospital_name": "Zero Row Test Hospital", "locations": "test location",
                  "items_scanned": 10, "format": "csv_tall", "error": None,
                  "file_last_updated": "2026-10-21", "cms_version": "2.2.0",
                  "drug_rows": 0, "hcpcs_found": ""})
    pl.concat([quality, pl.DataFrame([extra], schema=quality.schema)], how="vertical").write_parquet(path)

    rows = client.get("/api/hospitals").json()
    unmatched = next(row for row in rows if row["hospital_label"] == "Zero Row Test Hospital")
    assert unmatched["file_status"] == "no_selected_drug_rows"
    assert unmatched["rates"] == unmatched["drugs_priced"] == 0
    detail = client.get(f"/api/hospitals/{unmatched['hospital_key']}").json()
    assert detail["n_rows"] == 0 and detail["drugs"] == []


def test_hospital_upload_preserves_parser_metadata_path(client, built):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post("/api/v1/sources/upload/", {
        "source_key": "hospital_mrf", "system": "Test System", "snapshot_date": "2026-10-21",
        "file": SimpleUploadedFile("test_hospital_prices.json", b"{}", content_type="application/json"),
    })
    assert response.status_code == 201, response.json()
    from pathlib import Path
    path = Path(response.json()["relative_path"])
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    assert path.is_file()
    assert path.parent == built / "data/raw_essential_inputs/hospital_mrf/test_system/2026-10-21"
    assert "test_hospital_prices" in path.name


def test_zip_upload_rejects_member_path_traversal(client):
    from io import BytesIO
    import zipfile
    from django.core.files.uploadedfile import SimpleUploadedFile

    content = BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("../outside.csv", "not safe")
    response = client.post("/api/v1/sources/upload/", {
        "source_key": "cms_asp",
        "file": SimpleUploadedFile("asp_prices.zip", content.getvalue(), content_type="application/zip"),
    })
    assert response.status_code == 400
    assert "unsafe member path" in response.json()["error"]


def test_viewer_cannot_read_source_inventory_or_job_logs(built, db):
    import os
    import sys
    from pathlib import Path
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auditapi.settings")
    import django
    django.setup()
    user = get_user_model().objects.create_user(username="audit-readonly", password="readonly-pass")
    from pricing.permissions import VIEWER_GROUP
    user.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    viewer = Client()
    viewer.force_login(user)
    assert viewer.get("/api/v1/sources/").status_code == 403
    assert viewer.get("/api/v1/sources/jobs/").status_code == 403


def test_refresh_job_starts_worker_automatically(client, monkeypatch):
    import pricing.views

    calls = []
    monkeypatch.setattr(pricing.views.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    response = client.post("/api/v1/sources/jobs/", {"job_type": "refresh_data"},
                           content_type="application/json")
    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "queued"
    assert calls and calls[0][0][0][2:] == ["process_jobs", "--once"]


def test_saved_comparison_is_available_as_archived_snapshot_when_source_is_missing(built):
    import json
    from pricing.data import require_current_scope

    info = json.loads((built / "data/mart/run_info.json").read_text(encoding="utf-8"))
    source = Path(info["drug_selection_source_file"])
    if not source.is_absolute():
        source = Path(__file__).resolve().parents[1] / source
    source.unlink()
    assert require_current_scope() == "archived_snapshot"


def test_reference_catalog_and_paged_table(client):
    response = client.get("/api/v1/reference/")
    assert response.status_code == 200
    catalog = {item["key"]: item for item in response.json()}
    assert catalog["asp"]["status"] == "loaded"
    assert catalog["asp"]["rows"] == 11
    assert catalog["crosswalk"]["status"] == "loaded"
    assert catalog["ndc-products"]["status"] == "missing"
    page = client.get("/api/v1/reference/asp/", {"quarter": "2026Q4", "limit": 2}).json()
    assert page["status"] == "loaded" and page["total"] == 6
    assert len(page["rows"]) == 2


def test_drug_scope_and_settings_are_data_backed(client):
    scope = client.get("/api/v1/drug-scope/").json()
    assert scope["status"] == "selected"
    assert scope["selected_count"] == 5
    assert len(scope["source_sha256"]) == 64
    settings = client.get("/api/v1/settings/").json()
    assert settings["report"]["target_drug_count"] == 20
    assert settings["hospital_taxonomy"]["state_code"] == "OH"


def test_analyst_unit_review_is_bound_to_current_scope(client, tmp_path):
    ok = client.post("/api/v1/drug-scope/J9271/review/", {
        "status": "validated", "billing_qty": "1", "billing_unit": "MG",
        "notes": "Checked against the CMS dosage field.",
    }, content_type="application/json")
    assert ok.status_code == 200
    assert ok.json()["status"] == "validated"
    bad = client.post("/api/v1/drug-scope/J9271/review/", {
        "status": "validated", "billing_qty": "10", "billing_unit": "MG",
        "notes": "Wrong unit.",
    }, content_type="application/json")
    assert bad.status_code == 400
    assert "CMS ASP dosage" in bad.json()["error"]
