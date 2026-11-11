"""API tests: Django test client against the pipeline output built from TEST data."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def mfa_force_login(client, user):
    """Create explicit server-side MFA evidence for tests unrelated to sign-in."""
    from pricing.mfa import mark_mfa_verified
    from pricing.models import AdminOTPDevice

    device, _ = AdminOTPDevice.objects.get_or_create(
        user=user, defaults={"secret": "test-only-mfa-device", "enabled": True},
    )
    if not device.enabled:
        device.enabled = True
        device.save(update_fields=["enabled", "updated_at"])
    client.force_login(user)
    session = client.session
    mark_mfa_verified(session, user, device)
    session.save()
    return client


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
    return mfa_force_login(test_client, user)


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


@pytest.mark.django_db
def test_reviewer_can_see_current_draft_needed_for_report_release(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client
    from pricing import data
    from pricing.models import ReportRecord
    from pricing.permissions import REVIEWER_GROUP

    builder = get_user_model().objects.get(username="audit-test-admin")
    report = ReportRecord.objects.create(
        name="Current test report", status="generated", built_by=builder,
        source_hash=data.comparison_sha256(), config_hash=data.config_sha256(),
    )
    reviewer = get_user_model().objects.create_user(
        username="release-reviewer", password="test-only-password", is_active=True
    )
    reviewer.groups.add(Group.objects.get_or_create(name=REVIEWER_GROUP)[0])
    reviewer_client = Client()
    mfa_force_login(reviewer_client, reviewer)

    response = reviewer_client.get("/api/v1/reports/")
    assert response.status_code == 200, response.content
    assert response.json()[0]["id"] == report.pk
    assert response.json()[0]["status"] == "generated"
    assert response.json()[0]["built_by"] == builder.username
    assert "metadata" not in response.json()[0]


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
    mfa_force_login(viewer_client, viewer)
    assert viewer_client.get("/api/v1/dashboard/summary/").status_code == 403
    assert viewer_client.get("/api/v1/sources/").status_code == 403
    assert viewer_client.get("/api/v1/sources/jobs/").status_code == 403
    assert viewer_client.get("/api/v1/drug-selection-scope/").status_code == 403
    assert viewer_client.get("/api/v1/user-accounts/").status_code == 403


def test_staff_flag_alone_does_not_grant_application_admin(client):
    from django.contrib.auth import get_user_model
    from django.test import Client

    staff = get_user_model().objects.create_user(
        username="staff-no-role", password="long-test-password-123", is_active=True,
        is_staff=True,
    )
    staff_client = Client()
    mfa_force_login(staff_client, staff)
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


@pytest.mark.django_db
def test_four_role_backend_permission_matrix():
    from types import SimpleNamespace
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from pricing.permissions import (
        APPLICATION_ROLES, CanAdminister, CanAnalyze, CanReview, CanView,
        ADMIN_GROUP, VIEWER_GROUP,
    )

    User = get_user_model()
    for role in APPLICATION_ROLES:
        Group.objects.get_or_create(name=role)
    expected = {
        "SUPER_ADMIN": (True, True, True, True),
        "ANALYST": (True, True, False, False),
        "REVIEWER": (True, False, False, True),
        "CLIENT": (False, False, False, False),
    }
    for index, (role, decisions) in enumerate(expected.items()):
        user = User.objects.create_user(username=f"role-{index}", password="role-test-password")
        role_group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(role_group)
        request = SimpleNamespace(user=user, method="POST", path="/api/role-check/")
        actual = tuple(permission().has_permission(request, None) for permission in
                       (CanView, CanAnalyze, CanAdminister, CanReview))
        assert actual == decisions

    legacy_admin = User.objects.create_user(username="legacy-admin", password="legacy-test-password")
    legacy_admin.groups.add(Group.objects.get_or_create(name=ADMIN_GROUP)[0])
    legacy_viewer = User.objects.create_user(username="legacy-viewer", password="legacy-test-password")
    legacy_viewer.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    admin_request = SimpleNamespace(user=legacy_admin, method="POST", path="/api/role-check/")
    viewer_request = SimpleNamespace(user=legacy_viewer, method="GET", path="/api/v1/plan-audits/")
    assert CanAdminister().has_permission(admin_request, None)
    assert CanView().has_permission(viewer_request, None)
    assert not CanAnalyze().has_permission(viewer_request, None)

    client_user = User.objects.create_user(username="scoped-client", password="client-test-password")
    client_user.groups.add(Group.objects.get(name="CLIENT"))
    client_plan_request = SimpleNamespace(user=client_user, method="GET", path="/api/v1/plan-audits/")
    client_market_request = SimpleNamespace(user=client_user, method="GET", path="/api/v1/hospitals/")
    client_claims_request = SimpleNamespace(user=client_user, method="GET", path="/api/v1/claims/")
    client_imports_request = SimpleNamespace(user=client_user, method="GET", path="/api/v1/plan-audits/imports/")
    client_org_users_request = SimpleNamespace(user=client_user, method="GET", path="/api/v1/organizations/1/users/")
    client_published_results_request = SimpleNamespace(
        user=client_user, method="GET", path="/api/v1/plan-audits/1/results/")
    assert CanView().has_permission(client_plan_request, None)
    assert CanView().has_permission(client_market_request, None)
    assert not CanView().has_permission(client_claims_request, None)
    assert not CanView().has_permission(client_imports_request, None)
    assert not CanView().has_permission(client_org_users_request, None)
    assert CanView().has_permission(client_published_results_request, None)


@pytest.mark.django_db
def test_mk26_platform_writes_and_mk29_reviewer_import_inventory_are_denied(client, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from rest_framework.test import APIRequestFactory, force_authenticate
    from pricing.permissions import APPLICATION_ROLES
    from pricing import plan_audit_imports, views

    factory = APIRequestFactory()
    monkeypatch.setattr(views, "_start_processing_worker", lambda job: False)
    for role in APPLICATION_ROLES:
        user = get_user_model().objects.create_user(
            username=f"mk26-{role.lower()}", password="test-only-password")
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        request = factory.post("/api/v1/data-sources/processing-jobs/",
                               {"job_type": "refresh_data"}, format="json")
        force_authenticate(request, user=user)
        response = views.processing_jobs(request)
        assert response.status_code == (503 if role == "SUPER_ADMIN" else 403)

        upload = factory.post("/api/v1/data-sources/upload/", {}, format="multipart")
        force_authenticate(upload, user=user)
        assert views.source_upload(upload).status_code == (400 if role == "SUPER_ADMIN" else 403)

        imports = factory.get("/api/v1/plan-audits/imports/")
        force_authenticate(imports, user=user)
        result = plan_audit_imports.plan_summary_imports(imports)
        assert result.status_code == (200 if role in {"SUPER_ADMIN", "ANALYST"} else 403)


@pytest.mark.django_db
def test_import_inventory_and_audit_creation_use_accepted_tenant_scoped_imports(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from rest_framework.test import APIRequestFactory, force_authenticate
    from pricing.models import (ClaimsSummaryImport, Plan, PlanAudit,
                                PlanOrganization, PlanOrganizationAccess)
    from pricing import plan_audit_imports

    User = get_user_model()
    admin = User.objects.get(username="audit-test-admin")
    analyst = User.objects.create_user(username="mk30-import-analyst", password="test-password")
    analyst.groups.add(Group.objects.get_or_create(name="ANALYST")[0])
    reviewer = User.objects.create_user(username="mk30-import-reviewer", password="test-password")
    reviewer.groups.add(Group.objects.get_or_create(name="REVIEWER")[0])
    client_user = User.objects.create_user(username="mk30-import-client", password="test-password")
    client_user.groups.add(Group.objects.get_or_create(name="CLIENT")[0])

    organization = PlanOrganization.objects.create(
        organization_name="MK30 Assigned Import Org", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Assigned plan",
                               plan_reference="MK30-ASSIGNED")
    foreign_org = PlanOrganization.objects.create(
        organization_name="MK30 Foreign Import Org", organization_type="employer")
    foreign_plan = Plan.objects.create(organization=foreign_org, plan_name="Foreign plan",
                                       plan_reference="MK30-FOREIGN")
    PlanOrganizationAccess.objects.create(organization=organization, user=analyst, granted_by=admin)

    accepted = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="accepted-synthetic.csv",
        file_hash="a" * 64, schema_version="test-v1", import_status="accepted",
        source_period="2026Q4")
    rejected = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="rejected-synthetic.csv",
        file_hash="b" * 64, schema_version="test-v1", import_status="rejected")
    foreign = ClaimsSummaryImport.objects.create(
        organization=foreign_org, plan=foreign_plan, source_file_name="foreign-synthetic.csv",
        file_hash="c" * 64, schema_version="test-v1", import_status="accepted")

    factory = APIRequestFactory()

    admin_list = client.get(f"/api/v1/plan-audits/imports/?plan_id={plan.pk}")
    assert admin_list.status_code == 200
    assert {item["id"] for item in admin_list.json()["results"]} == {accepted.pk, rejected.pk}

    def call(user, method, view, path, data=None, **kwargs):
        request = (factory.get(path) if method == "GET" else
                   factory.post(path, data, format="json"))
        force_authenticate(request, user=user)
        return view(request, **kwargs)

    analyst_list = call(analyst, "GET", plan_audit_imports.plan_summary_imports,
                        "/api/v1/plan-audits/imports/")
    assert analyst_list.status_code == 200
    assert {item["id"] for item in analyst_list.data["results"]} == {accepted.pk, rejected.pk}
    assert foreign.pk not in {item["id"] for item in analyst_list.data["results"]}
    assert call(reviewer, "GET", plan_audit_imports.plan_summary_imports,
                "/api/v1/plan-audits/imports/").status_code == 403
    assert call(client_user, "GET", plan_audit_imports.plan_summary_imports,
                "/api/v1/plan-audits/imports/").status_code == 403

    from pricing.plan_audit_imports import create_plan_audit
    accepted_response = call(analyst, "POST", create_plan_audit, "/api/v1/plan-audits/create/", {
        "organization_id": organization.pk, "plan_id": plan.pk,
        "summary_import_id": accepted.pk, "audit_name": "Accepted synthetic audit",
    })
    assert accepted_response.status_code == 201, accepted_response.data
    created = PlanAudit.objects.get(pk=accepted_response.data["id"])
    assert created.summary_import_id == accepted.pk

    for bad_import in (rejected, foreign):
        response = call(analyst, "POST", create_plan_audit, "/api/v1/plan-audits/create/", {
            "organization_id": organization.pk, "plan_id": plan.pk,
            "summary_import_id": bad_import.pk, "audit_name": "Invalid synthetic audit",
        })
        assert response.status_code == 400

    assert call(reviewer, "POST", create_plan_audit, "/api/v1/plan-audits/create/", {}).status_code == 403
    assert call(client_user, "POST", create_plan_audit, "/api/v1/plan-audits/create/", {}).status_code == 403


@pytest.mark.django_db
def test_a10_import_and_audit_lists_paginate_all_records_with_stable_navigation(client):
    from pricing.models import ClaimsSummaryImport, Plan, PlanAudit, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="A10 Pagination Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Pagination Plan",
                               plan_reference="A10-PAGINATION-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="pagination.csv",
        file_hash="a10" * 21 + "a", schema_version="1.0", import_status="accepted")
    ClaimsSummaryImport.objects.bulk_create([
        ClaimsSummaryImport(organization=organization, plan=plan,
            source_file_name=f"import-{index}.csv", file_hash=f"{index:064x}",
            schema_version="1.0", import_status="rejected")
        for index in range(204)
    ])
    PlanAudit.objects.bulk_create([
        PlanAudit(organization=organization, plan=plan, summary_import=summary_import,
            audit_name=f"Audit {index}", reporting_period="2026Q1")
        for index in range(205)
    ])

    def collect(path):
        first = client.get(f"{path}?plan_id={plan.pk}&page_size=50")
        assert first.status_code == 200
        payload = first.json()
        assert payload["count"] == 205
        assert payload["page"] == 1
        assert payload["previous"] is None and payload["next"] == 2
        records = list(payload["results"])
        while payload["next"] is not None:
            payload = client.get(
                f"{path}?plan_id={plan.pk}&page_size=50&page={payload['next']}"
            ).json()
            records.extend(payload["results"])
        assert payload["next"] is None
        assert payload["previous"] == 4
        assert len(records) == len({item["id"] for item in records}) == 205
        return records

    assert len(collect("/api/v1/plan-audits/imports/")) == 205
    assert len(collect("/api/v1/plan-audits/")) == 205
    assert client.get(f"/api/v1/plan-audits/?plan_id={plan.pk}&page=0").status_code == 400


def test_a09_provider_grouped_interval_validation_preserves_overlap_rules_and_scales():
    from datetime import date, timedelta
    from time import perf_counter
    from types import SimpleNamespace
    from pricing.plan_audit_setup import _conflicting_roster_entries, _conflicting_roster_rows

    def interval(provider, status, start, end=None):
        return SimpleNamespace(provider_npi=provider, network_status=status,
                               effective_start=start, effective_end=end)

    rows = [
        interval("provider-a", "in_network", date(2026, 1, 1), date(2026, 1, 10)),
        interval("provider-a", "in_network", date(2026, 1, 5), date(2026, 1, 20)),
        interval("provider-a", "out_of_network", date(2026, 1, 10)),
        interval("provider-b", "in_network", date(2026, 1, 1)),
        interval("provider-b", "out_of_network", date(2027, 1, 1)),
    ]
    assert _conflicting_roster_rows(rows) == [2, 3, 4, 5, 6]
    assert _conflicting_roster_entries([rows[2], rows[4]], [rows[0], rows[3]]) == [2, 3]

    large_rows = [interval("provider-large", "in_network" if index % 2 else "out_of_network",
                           date(2000, 1, 1) + timedelta(days=index),
                           date(2000, 1, 1) + timedelta(days=index))
                  for index in range(5000)]
    started = perf_counter()
    assert _conflicting_roster_rows(large_rows) == []
    assert _conflicting_roster_entries(large_rows, large_rows) == []
    assert perf_counter() - started < 3.0


@pytest.mark.django_db
def test_a11_strict_summary_csv_rejects_malformed_and_invalid_utf8_but_accepts_valid(client):
    import hashlib
    import json
    from django.core.files.uploadedfile import SimpleUploadedFile
    from pricing.models import ClaimsSummaryImport, Plan, PlanOrganization
    from pricing.plan_audit_imports import APPROVED_FIELDS

    organization = PlanOrganization.objects.create(
        organization_name="A11 CSV Validation Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="CSV Plan",
                               plan_reference="A11-CSV-PLAN")
    period = "2026-01-01/2026-12-31"
    header = ",".join(APPROVED_FIELDS)
    valid_row = ("A11-CSV-PLAN,J9271,1000000004,2026Q1,outpatient_hospital,1,10,10,11-50,"
                 f"{period},2026-01-01T00:00:00+00:00,1.0")

    def submit(content, filename="claims_summary.csv"):
        manifest = {
            "file": filename, "sha256": hashlib.sha256(content).hexdigest(),
            "raw_claims_included": False, "member_identifiers_included": False,
            "small_cell_suppression_threshold": 11,
            "complementary_suppression_applied": True,
            "schema_version": "1.0", "approved_fields": APPROVED_FIELDS,
            "aggregate_rows": 1,
            "source_provenance": {"source_sha256": "a" * 64, "source_format": "csv",
                "input_records": 1, "plan_reference": plan.plan_reference,
                "source_period": period},
        }
        return client.post("/api/v1/plan-audits/import-summary/", {
            "organization_id": organization.pk, "plan_id": plan.pk,
            "file": SimpleUploadedFile(filename, content, content_type="text/csv"),
            "manifest": SimpleUploadedFile("manifest.json", json.dumps(manifest).encode("utf-8"),
                                            content_type="application/json"),
        })

    accepted = submit(f"{header}\n{valid_row}\n".encode())
    assert accepted.status_code == 201, accepted.content
    malformed = submit(f'{header}\n"A11-CSV-PLAN,J9271,1000000002'.encode())
    assert malformed.status_code == 400
    assert any("Malformed CSV syntax" in error["reason"]
               for error in malformed.json()["validation_summary"]["errors"])
    invalid_utf8 = submit(b"\xff\xfe\xfa")
    assert invalid_utf8.status_code == 400
    assert invalid_utf8.json()["import_status"] == "rejected"
    assert ClaimsSummaryImport.objects.filter(plan=plan, import_status="rejected").count() == 2


@pytest.mark.django_db
def test_mk25_paginated_serializers_check_client_visibility_once(client, monkeypatch):
    from types import SimpleNamespace
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from rest_framework.test import APIRequestFactory, force_authenticate
    from pricing.permissions import APPLICATION_ROLES
    from pricing import plan_audit_run

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def exclude(self, **kwargs):
            return self

        def order_by(self, *fields):
            return self

        def count(self):
            return len(self.rows)

        def __getitem__(self, item):
            return self.rows[item]

    factory = APIRequestFactory()
    audit = SimpleNamespace(pk=1)
    monkeypatch.setattr(plan_audit_run, "get_visible_audit", lambda user, audit_id: audit)
    monkeypatch.setattr(plan_audit_run, "current_audit_run", lambda _audit: object())
    monkeypatch.setattr(plan_audit_run, "run_results", lambda _run: active_rows[0])

    for role in APPLICATION_ROLES:
        user = get_user_model().objects.create_user(
            username=f"mk25-{role.lower()}", password="test-only-password")
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        client_only = role == "CLIENT"
        checks = []
        monkeypatch.setattr(plan_audit_run, "is_client_only",
                            lambda _user, value=client_only: checks.append(value) or value)
        for endpoint, route_name, values in (
            (plan_audit_run.hospital_comparison, "hospital-comparison", {
                "hospital_price_per_unit": "12", "hospital_markup_multiple": "2",
                "plan_to_hospital_price_multiple": "1.5",
            }),
            (plan_audit_run.asp_benchmark, "asp-benchmark", {
                "asp_payment_limit": "6", "allowed_markup_multiple": "2",
                "paid_markup_multiple": "1.5",
            }),
        ):
            query_counts = []
            for size in (1, 50):
                checks.clear()
                row = SimpleNamespace(
                    hcpcs_code="J1234", site_npi="1000000001", quarter="2026Q1",
                    service_setting="outpatient", plan_allowed_price_per_unit="12",
                    plan_paid_price_per_unit="9", data_quality_status="VALID",
                    source_references={"private": "synthetic"}, **values)
                active_rows = [Rows([row] * size)]
                request = factory.get(f"/api/v1/plan-audits/1/{route_name}/")
                force_authenticate(request, user=user)
                with CaptureQueriesContext(connection) as queries:
                    response = endpoint(request, audit_id=1)
                query_counts.append(len(queries))
                assert response.status_code == 200, (role, endpoint.__name__, response.data)
                assert len(checks) == 1
                result = response.data["results"][0]
                assert ("source_references" in result) is (not client_only)
            assert query_counts[0] == query_counts[1]


@pytest.mark.django_db
def test_mk28_client_market_exports_are_limited_to_released_canonical_csv(client, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from rest_framework.test import APIRequestFactory
    from pricing.permissions import APPLICATION_ROLES, CanAdminister
    from pricing import views

    release = {"drug_codes": ["J1234"]}
    monkeypatch.setattr(views, "_comparison_column_names", lambda: set(views.RATE_COLUMNS))
    factory = APIRequestFactory()

    for role in APPLICATION_ROLES:
        user = get_user_model().objects.create_user(
            username=f"mk28-{role.lower()}", password="test-only-password")
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        monkeypatch.setattr(views, "_viewer_release_payload",
                            lambda _request, client=(role == "CLIENT"):
                            (release, None) if client else (None, None))

        def authorized(path):
            request = factory.get(path)
            request.user = user
            return views._authorized_rate_filters(request)[3]

        legacy = authorized("/api/v1/comparisons.csv")
        modern = authorized("/api/v1/hospital-drug-price-comparisons/exports/csv/")
        if role == "CLIENT":
            assert legacy.status_code == 403
            assert isinstance(modern, list)
            assert not {"source_file", "source_member", "source_sha256"}.intersection(modern)
        else:
            assert isinstance(legacy, list)
            assert isinstance(modern, list)

        xlsx_request = factory.get("/api/v1/hospital-drug-price-comparisons/exports/excel/")
        xlsx_request.user = user
        assert CanAdminister().has_permission(xlsx_request, None) is (role == "SUPER_ADMIN")


@pytest.mark.django_db
def test_viewer_login_requires_totp_enrollment_and_second_factor(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client, override_settings
    from pricing.otp import code_at

    user = get_user_model().objects.create_user(
        username="jwt-viewer", password="long-test-password-123", is_active=True
    )
    from pricing.permissions import VIEWER_GROUP
    user.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    fresh_client = Client()
    with override_settings(TOTP_ENCRYPTION_KEY="F5wrMMH6I5kTnhPaaWqFvxLQmNY4J5kmWh0-e4jxQYc="):
        response = fresh_client.post("/api/v1/authentication/sign-in/", {
            "username": "jwt-viewer", "password": "long-test-password-123",
        }, content_type="application/json")
        assert response.status_code == 200
        assert response.json()["otp_setup_required"] is True
        assert "access" not in response.json()
        challenge = response.json()["challenge"]
        setup = fresh_client.post("/api/v1/authentication/totp/setup/", {
            "challenge": challenge,
        }, content_type="application/json")
        assert setup.status_code == 200
        assert "no-store" in setup.headers.get("Cache-Control", "")
        code, _ = code_at(setup.json()["secret"])
        confirmation = fresh_client.post("/api/v1/authentication/totp/confirmation/", {
            "challenge": challenge, "code": code,
        }, content_type="application/json")
        assert confirmation.status_code == 200
        assert confirmation.json()["user"]["roles"] == [VIEWER_GROUP]
        assert len(confirmation.json()["recovery_codes"]) == 10

        next_client = Client()
        password_response = next_client.post("/api/v1/authentication/sign-in/", {
            "username": "jwt-viewer", "password": "long-test-password-123",
        }, content_type="application/json")
        assert password_response.json()["otp_required"] is True
        verified = next_client.post("/api/v1/authentication/totp/sign-in-verification/", {
            "challenge": password_response.json()["challenge"],
            "recovery_code": confirmation.json()["recovery_codes"][0],
        }, content_type="application/json")
        assert verified.status_code == 200
        assert "no-store" in verified.headers.get("Cache-Control", "")
        current_user = next_client.get(
            "/api/v1/authentication/current-user/",
            HTTP_AUTHORIZATION=f"Bearer {verified.json()['access']}")
        assert current_user.json()["authenticated"]


@pytest.mark.django_db
def test_admin_can_reset_viewer_password_and_viewer_must_enroll_totp(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import check_password
    from django.contrib.auth.models import Group
    from django.test import Client
    from pricing.permissions import VIEWER_GROUP

    viewer = get_user_model().objects.create_user(
        username="resettable-viewer", password="old-viewer-password-123", is_active=True
    )
    viewer.groups.add(Group.objects.get_or_create(name=VIEWER_GROUP)[0])
    new_password = "new-viewer-password-456"
    response = client.post(
        f"/api/v1/user-accounts/{viewer.pk}/management/",
        {"password": new_password}, content_type="application/json",
    )
    assert response.status_code == 200
    viewer.refresh_from_db()
    assert check_password(new_password, viewer.password)

    signed_in = Client().post("/api/v1/authentication/sign-in/", {
        "username": viewer.username, "password": new_password,
    }, content_type="application/json")
    assert signed_in.status_code == 200
    assert signed_in.json()["otp_setup_required"] is True


@pytest.mark.django_db
def test_admin_login_requires_totp_enrollment_before_session_refresh(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client, override_settings
    from pricing.otp import code_at
    from pricing.permissions import ADMIN_GROUP

    user = get_user_model().objects.create_user(
        username="jwt-admin", password="long-test-password-123", is_active=True
    )
    user.groups.add(Group.objects.get_or_create(name=ADMIN_GROUP)[0])
    fresh_client = Client()
    with override_settings(TOTP_ENCRYPTION_KEY="F5wrMMH6I5kTnhPaaWqFvxLQmNY4J5kmWh0-e4jxQYc="):
        response = fresh_client.post("/api/v1/authentication/sign-in/", {
            "username": "jwt-admin", "password": "long-test-password-123",
        }, content_type="application/json")
        assert response.status_code == 200
        assert response.json()["otp_setup_required"] is True
        challenge = response.json()["challenge"]

        setup = fresh_client.post("/api/v1/authentication/totp/setup/", {
            "challenge": challenge,
        }, content_type="application/json")
        assert setup.status_code == 200
        assert "no-store" in setup.headers.get("Cache-Control", "")
        assert setup.json()["otpauth_url"].startswith("otpauth://totp/")
        code, _ = code_at(setup.json()["secret"])
        confirmation = fresh_client.post("/api/v1/authentication/totp/confirmation/", {
            "challenge": challenge, "code": code,
        }, content_type="application/json")
        assert confirmation.status_code == 200
        assert "no-store" in confirmation.headers.get("Cache-Control", "")
        token = confirmation.json()["access"]
        assert confirmation.json()["token_type"] == "Bearer"
        current_user = fresh_client.get(
            "/api/v1/authentication/current-user/", HTTP_AUTHORIZATION=f"Bearer {token}")
        assert current_user.json()["authenticated"]

        # The HttpOnly Django session is the refresh credential and survives a page reload.
        refresh = fresh_client.post("/api/v1/authentication/access-token/refresh/", "{}",
                                    content_type="application/json")
        assert refresh.status_code == 200
        assert refresh.json()["access"]

        token_only = Client()
        rejected = token_only.post("/api/v1/authentication/access-token/refresh/", "{}",
                                   content_type="application/json",
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


@pytest.mark.parametrize("legacy_schema", [False, True], ids=["canonical", "legacy"])
def test_medicare_part_b_drugs_support_both_asp_schemas(
    client, tmp_path, monkeypatch, legacy_schema
):
    import polars as pl
    from pricing import data

    if legacy_schema:
        paths = data.files()
        legacy_path = tmp_path / "legacy_asp.parquet"
        pl.read_parquet(paths["asp"]).rename({
            "quarter": "period",
            "dosage_text": "dosage",
            "short_description": "description",
        }).write_parquet(legacy_path)
        paths["asp"] = legacy_path
        monkeypatch.setattr(data, "files", lambda: paths)

    response = client.get("/api/v1/medicare-part-b-drugs/")
    assert response.status_code == 200, response.content

    drugs = {row["hcpcs"]: row for row in response.json()}
    assert set(drugs) == {"J9271", "J9299", "J2350", "J1745", "J0897"}
    expected_limits = {
        "J9271": 60.0, "J9299": 30.0, "J2350": 100.0,
        "J1745": 40.0, "J0897": 20.0,
    }
    for code, payment_limit in expected_limits.items():
        assert drugs[code]["asp_quarter"] == "2026Q4"
        assert drugs[code]["asp_payment_limit"] == payment_limit
        assert drugs[code]["asp_dosage"] == ("10 MG" if code == "J1745" else "1 MG")

    catalog = client.get("/api/v1/reference/").json()
    asp_catalog = next(item for item in catalog if item["key"] == "asp")
    assert asp_catalog["periods"] == ["2026Q3", "2026Q4"]
    asp_page = client.get("/api/v1/reference/asp/", {"quarter": "2026Q4", "limit": 20})
    assert asp_page.status_code == 200
    assert asp_page.json()["total"] == 6

    detail = client.get("/api/v1/medicare-part-b-drugs/J9271/")
    assert detail.status_code == 200, detail.content
    assert [row["quarter"] for row in detail.json()["asp"]] == ["2026Q3", "2026Q4"]
    assert detail.json()["asp"][-1]["dosage_text"] == "1 MG"
    assert detail.json()["asp"][-1]["payment_limit"] == 60.0
    assert detail.json()["asp"][-1]["short_description"] == "Inj pembrolizumab"


def test_medicare_part_b_drugs_reject_unauthorized_users():
    from django.test import Client as DjangoClient

    response = DjangoClient().get("/api/v1/medicare-part-b-drugs/")
    assert response.status_code in {401, 403}


def test_rates_filter_and_sort(client):
    paged = client.get("/api/v1/hospital-drug-price-comparisons/", {
        "sort": "markup_multiple", "order": "desc", "limit": 50, "offset": 0,
    })
    assert paged.status_code == 200, paged.content
    paged_result = paged.json()
    paged_rows = paged_result["rows"]
    assert len(paged_rows) == min(paged_result["total"], 50)
    paged_markups = [row["markup_multiple"] for row in paged_rows if row["markup_multiple"] is not None]
    assert paged_markups == sorted(paged_markups, reverse=True)
    assert all(row["markup_multiple"] is None for row in paged_rows[len(paged_markups):])

    r = client.get("/api/rates", {"hcpcs": "J9271", "price_type": "negotiated_dollar",
                                  "status": "ok", "sort": "markup_multiple"}).json()
    assert r["total"] == 5
    m = [x["markup_multiple"] for x in r["rows"]]
    assert m == sorted(m, reverse=True)
    # unsafe sort value falls back to markup_multiple
    assert client.get("/api/rates", {"sort": "1; DROP TABLE x"}).status_code == 200
    assert client.get("/api/rates", {"limit": "many"}).status_code == 400


def test_production_comparison_parquet_supports_rate_projection(monkeypatch):
    """Guard the real snapshot against DuckDB projected-column reader regressions."""
    from decimal import Decimal
    from pricing import data

    comparison = BACKEND.parent / "data" / "mart" / "comparison.parquet"
    monkeypatch.setattr(data, "files", lambda: {"comparison": comparison})
    monkeypatch.setattr(data, "require_current_scope", lambda: "verified_source")

    rows = data.query(
        "SELECT hospital_key, price_per_billing_unit, asp_payment_limit, markup_multiple FROM {cmp} "
        "ORDER BY markup_multiple DESC NULLS LAST LIMIT 50 OFFSET 0",
        cmp="comparison",
    )
    assert len(rows) == 50
    priced = [row for row in rows if row["markup_multiple"] is not None]
    assert priced
    multiples = [Decimal(str(row["markup_multiple"])) for row in priced]
    assert multiples == sorted(multiples, reverse=True)
    for row in priced:
        calculated = Decimal(str(row["price_per_billing_unit"])) / Decimal(str(row["asp_payment_limit"]))
        assert abs(calculated - Decimal(str(row["markup_multiple"]))) < Decimal("1e-18")


def test_comparison_payer_filter_options_come_from_parquet(client):
    options = client.get("/api/v1/hospital-drug-price-comparisons/filter-options/")
    rows = client.get("/api/v1/hospital-drug-price-comparisons/", {"limit": 1000})
    assert options.status_code == 200, options.content
    assert rows.status_code == 200, rows.content
    actual = sorted({row["payer_group"] for row in rows.json()["rows"] if row.get("payer_group")})
    assert options.json()["payer_groups"] == actual


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
    mfa_force_login(viewer, user)
    assert viewer.get("/api/v1/sources/").status_code == 403
    assert viewer.get("/api/v1/sources/jobs/").status_code == 403


def test_refresh_job_starts_worker_automatically(client, monkeypatch):
    from contextlib import contextmanager
    import pipeline.snapshots
    import pricing.views

    calls = []
    monkeypatch.setattr(pricing.views.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    response = client.post("/api/v1/sources/jobs/", {"job_type": "refresh_data"},
                           content_type="application/json")
    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "queued"
    assert calls and calls[0][0][0][2:] == ["process_jobs", "--once"]
    @contextmanager
    def active_worker_lock(_project, *, blocking=True):
        yield False

    monkeypatch.setattr(pipeline.snapshots, "pipeline_mutex", active_worker_lock)
    duplicate = client.post("/api/v1/sources/jobs/", {"job_type": "market_report"},
                            content_type="application/json")
    assert duplicate.status_code == 409
    assert len(calls) == 1


def test_stale_processing_job_restarts_only_when_pipeline_lock_is_free(client, monkeypatch):
    from contextlib import contextmanager
    import pipeline.snapshots
    import pricing.views
    from django.utils import timezone
    from pricing.models import ProcessingJob

    job = ProcessingJob.objects.create(job_type="refresh_data", status="running",
                                       started_at=timezone.now())
    calls = []
    monkeypatch.setattr(pricing.views.subprocess, "Popen",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    state = {"available": False}

    @contextmanager
    def fake_pipeline_mutex(_project, *, blocking=True):
        assert blocking is False
        yield state["available"]

    monkeypatch.setattr(pipeline.snapshots, "pipeline_mutex", fake_pipeline_mutex)
    path = "/api/v1/sources/jobs/"
    payload = {"job_type": "refresh_data"}
    busy = client.post(path, payload, content_type="application/json")
    assert busy.status_code == 409
    assert busy.json()["id"] == job.pk
    assert calls == []

    state["available"] = True
    recovered = client.post(path, payload, content_type="application/json")
    assert recovered.status_code == 202
    assert recovered.json()["id"] == job.pk
    assert recovered.json()["recovery_scheduled"] is True
    assert len(calls) == 1
    assert ProcessingJob.objects.count() == 1


def test_plan_audit_hospital_and_asp_lists_are_paged(client, monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace
    import pricing.plan_audit_run as audit_run

    rows = [SimpleNamespace(
        hcpcs_code="J9271", site_npi=f"{index:010d}", quarter="2026Q1",
        service_setting="outpatient", plan_allowed_price_per_unit=Decimal("100"),
        hospital_price_per_unit=Decimal("125"), hospital_markup_multiple=Decimal("1.25"),
        plan_to_hospital_price_multiple=Decimal("0.8"), data_quality_status="VALID",
        source_references={}, plan_paid_price_per_unit=Decimal("90"),
        asp_payment_limit=Decimal("80"), allowed_markup_multiple=Decimal("1.25"),
        paid_markup_multiple=Decimal("1.125"),
    ) for index in range(2005)]

    class QueryRows:
        def __init__(self, items):
            self.items = items

        def exclude(self, **_kwargs):
            return self

        def order_by(self, *_fields):
            return self

        def count(self):
            return len(self.items)

        def __getitem__(self, selection):
            return self.items[selection]

    monkeypatch.setattr(audit_run, "get_visible_audit", lambda *_args: object())
    monkeypatch.setattr(audit_run, "current_audit_run", lambda *_args: object())
    monkeypatch.setattr(audit_run, "run_results", lambda *_args: QueryRows(rows))

    for endpoint in ("hospital-comparison", "asp-benchmark"):
        first_page = client.get(f"/api/v1/plan-audits/1/{endpoint}/?limit=200&offset=0")
        assert first_page.status_code == 200
        assert first_page.json()["count"] == 2005
        assert len(first_page.json()["results"]) == 200
        assert first_page.json()["next_offset"] == 200
        assert first_page.json()["previous_offset"] is None

        last_page = client.get(f"/api/v1/plan-audits/1/{endpoint}/?limit=200&offset=2000")
        assert last_page.status_code == 200
        assert len(last_page.json()["results"]) == 5
        assert last_page.json()["next_offset"] is None
        assert last_page.json()["previous_offset"] == 1800


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
        "clinical_reviewer_name": "Test External Pharmacist",
        "notes": "Checked against the CMS dosage field.",
    }, content_type="application/json")
    assert ok.status_code == 200
    assert ok.json()["status"] == "validated"
    bad = client.post("/api/v1/drug-scope/J9271/review/", {
        "status": "validated", "billing_qty": "10", "billing_unit": "MG",
        "clinical_reviewer_name": "Test External Pharmacist", "notes": "Wrong unit.",
    }, content_type="application/json")
    assert bad.status_code == 400
    assert "CMS ASP dosage" in bad.json()["error"]


def test_claims_explorer_rejects_unauthenticated():
    from django.test import Client as DjangoClient

    response = DjangoClient().get("/api/v1/claims/")
    assert response.status_code in {401, 403}

    detail = DjangoClient().get("/api/v1/claims/CLM12345/")
    assert detail.status_code in {401, 403}


def test_claims_explorer_list_and_filtering(client):
    from pricing.models import ClaimsExplorerDataset, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="Claims Explorer Test Org", organization_type="employer",
    )
    dataset_id = "desynpuf_outpatient_claims_sample_1"
    inpatient_id = "desynpuf_inpatient_claims_sample_1"
    registration = client.post("/api/v1/claims/datasets/", {
        "organization_id": organization.pk, "dataset_identifier": dataset_id,
    }, content_type="application/json")
    assert registration.status_code == 201, registration.content
    assert registration.json()["created"] is True
    ClaimsExplorerDataset.objects.create(
        organization=organization, dataset_identifier=inpatient_id,
    )
    catalog = client.get("/api/v1/claims/datasets/", {"organization_id": organization.pk})
    assert catalog.status_code == 200
    assert {item["dataset_identifier"] for item in catalog.json()["datasets"]} == {
        dataset_id, inpatient_id,
    }
    assert len(catalog.json()["available_datasets"]) >= 2
    assert "normalized" not in str(catalog.json())

    missing_scope = client.get("/api/v1/claims/")
    assert missing_scope.status_code == 400
    response = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": dataset_id, "page_size": 10,
    })
    assert response.status_code == 200, response.content
    data = response.json()
    assert data["dataset"] == dataset_id
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert "data_disclaimer" in data
    assert "total" in data
    assert "columns" in data
    assert "rows" in data
    assert len(data["rows"]) <= 10
    assert data["rows"]
    assert "source_lineage" not in data["rows"][0]
    assert "beneficiary_id" not in data["rows"][0]
    assert "normalized" not in str(data)

    claim_id = data["rows"][0]["claim_id"]
    detail_res = client.get(f"/api/v1/claims/{claim_id}/", {
        "organization_id": organization.pk, "dataset": dataset_id,
    })
    assert detail_res.status_code == 200, detail_res.content
    assert detail_res.json()["dataset"] == dataset_id
    assert detail_res.json()["claim"]["claim_id"] == claim_id
    assert "source_lineage" not in detail_res.json()["claim"]
    assert "beneficiary_id" not in detail_res.json()["claim"]
    assert all("source_lineage" not in line for line in detail_res.json()["lines"])

    inpatient_res = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": inpatient_id, "page_size": 5,
    })
    assert inpatient_res.status_code == 200
    assert inpatient_res.json()["dataset"] == inpatient_id

    bad_dataset = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": "invalid_dataset",
    })
    assert bad_dataset.status_code == 400

    unregistered = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": "unknown_dataset",
    })
    assert unregistered.status_code == 400

    hcpcs_res = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": dataset_id, "hcpcs": "J9271", "page_size": 5,
    })
    assert hcpcs_res.status_code == 200

    provider_res = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": dataset_id, "provider": "PRV", "page_size": 5,
    })
    assert provider_res.status_code == 200

    date_res = client.get("/api/v1/claims/", {
        "organization_id": organization.pk,
        "dataset": dataset_id,
        "service_date_from": "2008-01-01",
        "service_date_to": "2010-12-31",
        "page_size": 5,
    })
    assert date_res.status_code == 200
    sql_injection = client.get("/api/v1/claims/", {
        "organization_id": organization.pk, "dataset": dataset_id, "hcpcs": "J0000' OR 1=1 --",
    })
    assert sql_injection.status_code == 400


def test_organization_and_plan_lifecycle(client):
    from django.test import Client as DjangoClient

    # Unauthenticated rejected
    unauth = DjangoClient().get("/api/v1/organizations/")
    assert unauth.status_code in {401, 403}

    # Admin creates organization
    org_res = client.post("/api/v1/organizations/", {
        "organization_name": "Test Employer Health Plan",
        "organization_type": "employer",
    }, content_type="application/json")
    assert org_res.status_code == 201, org_res.content
    org_id = org_res.json()["id"]

    # Organization listed
    list_res = client.get("/api/v1/organizations/")
    assert list_res.status_code == 200
    assert any(o["id"] == org_id for o in list_res.json())

    # Admin creates plan within organization
    plan_res = client.post("/api/v1/plans/", {
        "organization_id": org_id,
        "plan_name": "Standard PPO",
        "plan_reference": "PLAN-PPO-001",
        "effective_start": "2024-01-01",
    }, content_type="application/json")
    assert plan_res.status_code == 201, plan_res.content
    plan_id = plan_res.json()["id"]

    # Plan listed for organization
    plans_list = client.get("/api/v1/plans/", {"organization_id": org_id})
    assert plans_list.status_code == 200
    assert any(p["id"] == plan_id for p in plans_list.json())


@pytest.mark.django_db
def test_super_admin_status_management_preserves_history_and_blocks_inactive_org_access(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client as DjangoClient
    from pricing.models import (AuditEvent, ClaimsSummaryImport, Plan, PlanAudit,
                                PlanOrganization, PlanOrganizationAccess)

    organization = PlanOrganization.objects.create(
        organization_name="Status Management Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Status Plan",
                               plan_reference="STATUS-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="aggregate.csv",
        file_hash="a" * 64, schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="History remains", reporting_period="2026Q4")

    ordinary_clients = []
    for role in ("ANALYST", "REVIEWER", "CLIENT"):
        user = get_user_model().objects.create_user(username=f"status-{role.lower()}", password="test")
        role_group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(role_group)
        PlanOrganizationAccess.objects.create(organization=organization, user=user)
        ordinary_clients.append(mfa_force_login(DjangoClient(), user))

    organization_update = client.patch(
        f"/api/v1/organizations/{organization.pk}/status/", {"status": "inactive"},
        content_type="application/json")
    assert organization_update.status_code == 200, organization_update.content
    assert organization_update.json()["status"] == "inactive"
    assert organization.pk in [row["id"] for row in client.get("/api/v1/organizations/").json()]
    assert plan.pk in [row["id"] for row in client.get("/api/v1/plans/").json()]

    for role_client in ordinary_clients:
        for path in (f"/api/v1/plans/{plan.pk}/",
                     f"/api/v1/plan-audits/imports/{summary_import.pk}/",
                     f"/api/v1/plan-audits/{audit.pk}/"):
            assert role_client.get(path).status_code in {403, 404}

    denied = ordinary_clients[0].patch(
        f"/api/v1/organizations/{organization.pk}/status/", {"status": "active"},
        content_type="application/json")
    assert denied.status_code == 403
    invalid = client.patch(
        f"/api/v1/organizations/{organization.pk}/status/", {"status": "unknown"},
        content_type="application/json")
    assert invalid.status_code == 400

    plan_deactivation = client.patch(
        f"/api/v1/plans/{plan.pk}/", {"status": "inactive"}, content_type="application/json")
    assert plan_deactivation.status_code == 200
    plan_reactivation = client.patch(
        f"/api/v1/plans/{plan.pk}/", {"status": "active"}, content_type="application/json")
    assert plan_reactivation.status_code == 400
    assert Plan.objects.get(pk=plan.pk).status == "inactive"

    reactivated = client.patch(
        f"/api/v1/organizations/{organization.pk}/status/", {"status": "active"},
        content_type="application/json")
    assert reactivated.status_code == 200
    plan_reactivated = client.patch(
        f"/api/v1/plans/{plan.pk}/", {"status": "active"}, content_type="application/json")
    assert plan_reactivated.status_code == 200
    assert all(role_client.get(f"/api/v1/plans/{plan.pk}/").status_code == 200
               for role_client in ordinary_clients)
    assert PlanAudit.objects.filter(pk=audit.pk).exists()
    assert ClaimsSummaryImport.objects.filter(pk=summary_import.pk).exists()
    status_events = AuditEvent.objects.filter(action__in=(
        "plan_organization_status_changed", "plan_status_changed"))
    assert status_events.count() == 4
    assert all("previous_status" in event.details and "new_status" in event.details
               and "timestamp" in event.details for event in status_events)


@pytest.mark.django_db
def test_a05_rejected_import_hash_can_be_retried_but_accepted_hash_is_unique():
    from django.db import IntegrityError, transaction
    from pricing.models import ClaimsSummaryImport, Plan, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="A05 Retry Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="A05 Plan",
                               plan_reference="A05-RETRY-PLAN")
    digest = "a" * 64
    rejected = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="retry.csv",
        file_hash=digest, schema_version="1.0", import_status="rejected")

    accepted = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="retry.csv",
        file_hash=digest, schema_version="1.0", import_status="accepted")
    assert ClaimsSummaryImport.objects.filter(pk=rejected.pk, import_status="rejected").exists()
    assert ClaimsSummaryImport.objects.filter(pk=accepted.pk, import_status="accepted").exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        ClaimsSummaryImport.objects.create(
            organization=organization, plan=plan, source_file_name="duplicate.csv",
            file_hash=digest, schema_version="1.0", import_status="accepted")


@pytest.mark.django_db
def test_a08_expired_run_lease_recovers_and_live_lease_blocks_new_run(client, monkeypatch):
    from datetime import timedelta
    from django.contrib.auth import get_user_model
    from django.conf import settings
    from django.utils import timezone
    from pricing.models import (ClaimsSummaryImport, Plan, PlanAudit, PlanAuditRun,
                                PlanOrganization)
    from pricing import plan_audit_run

    organization = PlanOrganization.objects.create(
        organization_name="A08 Recovery Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="A08 Plan",
                               plan_reference="A08-RECOVERY-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="a08.csv",
        file_hash="a08" * 21 + "a", schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="Recovery", reporting_period="2026Q4",
        status="running", current_version=1)
    now = timezone.now()
    run = PlanAuditRun.objects.create(
        plan_audit=audit, version=1, calculation_status="running",
        publication_status="pending", summary_import=summary_import,
        started_at=now, heartbeat_at=now, worker_id="active-worker")
    monkeypatch.setattr(plan_audit_run, "run_plan_audit", lambda *_args, **_kwargs: {
        "quality_status_counts": {}, "result_rows": 0, "savings_opportunities": 0,
    })
    monkeypatch.setattr(settings, "PLAN_AUDIT_RUN_LEASE_SECONDS", 30, raising=False)

    in_progress = client.post(f"/api/v1/plan-audits/{audit.pk}/run/")
    assert in_progress.status_code == 409
    run.refresh_from_db()
    assert run.calculation_status == "running"

    run.heartbeat_at = now - timedelta(seconds=31)
    run.save(update_fields=["heartbeat_at"])
    recovered = client.post(f"/api/v1/plan-audits/{audit.pk}/run/")
    assert recovered.status_code == 200, recovered.content
    run.refresh_from_db()
    audit.refresh_from_db()
    assert run.calculation_status == "failed"
    assert run.publication_status == "failed"
    assert audit.current_version == 2
    assert PlanAuditRun.objects.filter(plan_audit=audit, version=2,
                                       calculation_status="completed").exists()


@pytest.mark.django_db(transaction=True)
def test_a08_simultaneous_run_requests_allow_only_one_active_worker(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import sqlite3
    from django.contrib.auth import get_user_model
    from django.conf import settings
    from django.db import close_old_connections, connection
    from django.test import Client as DjangoClient
    from pricing.models import ClaimsSummaryImport, Plan, PlanAudit, PlanAuditRun, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="A08 Concurrency Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Concurrent Plan",
                               plan_reference="A08-CONCURRENCY-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="concurrent.csv",
        file_hash="c08" * 21 + "c", schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="Concurrent", reporting_period="2026Q4")
    user = get_user_model().objects.get(is_superuser=True)
    first_client = mfa_force_login(DjangoClient(), user)
    second_client = mfa_force_login(DjangoClient(), user)
    started, release = Event(), Event()

    def paused_calculation(_audit, run, heartbeat=None):
        assert not connection.in_atomic_block
        heartbeat()
        independent = sqlite3.connect(settings.DATABASES["default"]["NAME"])
        try:
            visible = independent.execute(
                "SELECT heartbeat_at FROM pricing_planauditrun WHERE id = ?", [run.pk]).fetchone()
        finally:
            independent.close()
        assert visible and visible[0]
        started.set()
        if not release.wait(10):
            raise TimeoutError("The concurrency fixture was not released.")
        return {"quality_status_counts": {}, "result_rows": 0, "savings_opportunities": 0}

    monkeypatch.setattr("pricing.plan_audit_run.run_plan_audit", paused_calculation)

    def first_request():
        close_old_connections()
        try:
            return first_client.post(
                f"/api/v1/plan-audits/{audit.pk}/run/").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(first_request)
        assert started.wait(10), "The first run did not reach its calculation phase."
        second_response = second_client.post(
            f"/api/v1/plan-audits/{audit.pk}/run/")
        release.set()
        first_status = first.result(timeout=15)

    assert first_status == 200
    assert second_response.status_code == 409
    assert PlanAuditRun.objects.filter(plan_audit=audit, calculation_status="running").count() == 0
    assert PlanAuditRun.objects.filter(plan_audit=audit).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a08_simultaneous_start_race_preserves_the_winning_run(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from django.contrib.auth import get_user_model
    from django.db import close_old_connections, connection
    from django.test import Client as DjangoClient
    from pricing.models import ClaimsSummaryImport, Plan, PlanAudit, PlanAuditRun, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="A08 Start Race Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Start Race Plan",
                               plan_reference="A08-START-RACE-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="start-race.csv",
        file_hash="d08" * 21 + "d", schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="Start race", reporting_period="2026Q4")
    user = get_user_model().objects.get(is_superuser=True)
    clients = [mfa_force_login(DjangoClient(), user) for _ in range(2)]
    ready, started, release = Barrier(2), Event(), Event()

    def paused_calculation(*_args, **_kwargs):
        started.set()
        if not release.wait(10):
            raise TimeoutError("The concurrent start fixture was not released.")
        return {"quality_status_counts": {}, "result_rows": 0, "savings_opportunities": 0}

    monkeypatch.setattr("pricing.plan_audit_run.run_plan_audit", paused_calculation)

    def run_request(test_client):
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return test_client.post(f"/api/v1/plan-audits/{audit.pk}/run/").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_request, item) for item in clients]
        # Keep the winning calculation active while its competitor attempts reservation.
        assert started.wait(10), "The winning request did not reach its calculation phase."
        release.set()
        responses = sorted(future.result(timeout=20) for future in futures)

    audit.refresh_from_db()
    assert audit.status in {"completed", "needs_review"}, (
        f"A losing concurrent start must not mark the audit failed; got {audit.status!r}."
    )
    assert responses == [200, 409]
    assert PlanAuditRun.objects.filter(plan_audit=audit, calculation_status="completed").count() == 1
    assert PlanAuditRun.objects.filter(plan_audit=audit, calculation_status="running").count() == 0


@pytest.mark.django_db(transaction=True)
def test_a08_stale_worker_cannot_complete_or_fail_after_owner_changes(client, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.db import close_old_connections, connection
    from django.test import Client as DjangoClient
    from pricing.models import ClaimsSummaryImport, Plan, PlanAudit, PlanAuditRun, PlanOrganization

    organization = PlanOrganization.objects.create(
        organization_name="A08 Stale Owner Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Stale Owner Plan",
                               plan_reference="A08-STALE-OWNER-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="stale-owner.csv",
        file_hash="e08" * 21 + "e", schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="Stale owner", reporting_period="2026Q4")
    user = get_user_model().objects.get(is_superuser=True)
    from pricing import plan_audit_run

    def lose_owner(_audit, _run, heartbeat=None):
        PlanAudit.objects.filter(pk=audit.pk).update(run_owner_token="replacement-owner")
        heartbeat()

    monkeypatch.setattr(plan_audit_run, "run_plan_audit", lose_owner)
    response = mfa_force_login(DjangoClient(), user).post(f"/api/v1/plan-audits/{audit.pk}/run/")
    audit.refresh_from_db()
    run = PlanAuditRun.objects.get(plan_audit=audit)
    assert response.status_code == 409
    assert audit.run_owner_token == "replacement-owner"
    assert run.calculation_status == "running"
    assert run.publication_status == "pending"


@pytest.mark.django_db(transaction=True)
def test_a08_concurrent_failure_is_recorded_only_by_the_owner(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.contrib.auth import get_user_model
    from django.db import close_old_connections
    from django.test import Client as DjangoClient
    from pricing.models import (AuditEvent, ClaimsSummaryImport, Plan, PlanAudit,
                                PlanAuditRun, PlanOrganization)

    organization = PlanOrganization.objects.create(
        organization_name="A08 Failure Race Test", organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Failure Race Plan",
                               plan_reference="A08-FAILURE-RACE-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="failure-race.csv",
        file_hash="f08" * 21 + "f", schema_version="1.0", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan,
        summary_import=summary_import, audit_name="Failure race", reporting_period="2026Q4")
    user = get_user_model().objects.get(is_superuser=True)
    first_client, second_client = [mfa_force_login(DjangoClient(), user) for _ in range(2)]
    started, release = Event(), Event()

    def failing_calculation(*_args, **_kwargs):
        started.set()
        if not release.wait(10):
            raise TimeoutError("The concurrent failure fixture was not released.")
        raise RuntimeError("controlled concurrent failure")

    monkeypatch.setattr("pricing.plan_audit_run.run_plan_audit", failing_calculation)

    def first_request():
        close_old_connections()
        try:
            return first_client.post(f"/api/v1/plan-audits/{audit.pk}/run/").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(first_request)
        assert started.wait(10), "The first run did not reach its calculation phase."
        competing_status = second_client.post(f"/api/v1/plan-audits/{audit.pk}/run/").status_code
        release.set()
        first_status = first.result(timeout=15)

    audit.refresh_from_db()
    run = PlanAuditRun.objects.get(plan_audit=audit)
    assert (first_status, competing_status) == (500, 409)
    assert audit.status == "failed"
    assert not audit.run_owner_token
    assert run.calculation_status == "failed"
    assert run.publication_status == "failed"
    assert AuditEvent.objects.filter(action="plan_audit_run_failed", entity_id=str(audit.pk)).count() == 1


@pytest.mark.django_db
def test_admin_account_role_and_organization_access_workflow(client):
    """Exercise the Admin UI's account and tenant-access API contracts together."""
    from django.contrib.auth import get_user_model
    from django.test import Client as DjangoClient

    password = "Meshkor-Test-Account-2026!"
    created_accounts = {}
    for role in ("ANALYST", "REVIEWER", "CLIENT"):
        response = client.post("/api/v1/user-accounts/", {
            "username": f"phase2-{role.lower()}", "role": role, "password": password,
        }, content_type="application/json")
        assert response.status_code == 201, response.content
        created_accounts[role] = response.json()["id"]

    listed = client.get("/api/v1/user-accounts/")
    assert listed.status_code == 200
    for role, user_id in created_accounts.items():
        account = next(item for item in listed.json() if item["id"] == user_id)
        assert account["roles"] == [role]
        assert account["is_active"] is True

    # A role change and deactivation are persisted by the same endpoint the UI calls.
    role_update = client.post(f"/api/v1/user-accounts/{created_accounts['ANALYST']}/management/", {
        "role": "ANALYST", "is_active": True,
    }, content_type="application/json")
    assert role_update.status_code == 200
    assert role_update.json()["roles"] == ["ANALYST"]
    disable = client.post(f"/api/v1/user-accounts/{created_accounts['CLIENT']}/management/", {
        "role": "CLIENT", "is_active": False,
    }, content_type="application/json")
    assert disable.status_code == 200
    assert disable.json()["is_active"] is False
    client_user = get_user_model().objects.get(pk=created_accounts["CLIENT"])
    assert client_user.is_active is False

    organization = client.post("/api/v1/organizations/", {
        "organization_name": "Phase 2 Workflow Test Employer", "organization_type": "employer",
    }, content_type="application/json")
    assert organization.status_code == 201, organization.content
    organization_id = organization.json()["id"]
    plan = client.post("/api/v1/plans/", {
        "organization_id": organization_id, "plan_name": "Synthetic Test Plan",
        "plan_reference": "PHASE2-WORKFLOW-TEST", "effective_start": "2026-01-01",
    }, content_type="application/json")
    assert plan.status_code == 201, plan.content

    for role, user_id in created_accounts.items():
        grant = client.post(f"/api/v1/organizations/{organization_id}/users/", {"user_id": user_id},
                            content_type="application/json")
        assert grant.status_code == (400 if role == "CLIENT" else 201), grant.content
        if role != "CLIENT":
            user = get_user_model().objects.get(pk=user_id)
            role_client = mfa_force_login(DjangoClient(), user)
            assert any(item["id"] == organization_id
                       for item in role_client.get("/api/v1/organizations/").json())
            assert any(item["id"] == plan.json()["id"]
                       for item in role_client.get("/api/v1/plans/", {"organization_id": organization_id}).json())

    # Re-enable the Client through the Admin action, grant access, then revoke it.
    enable = client.post(f"/api/v1/user-accounts/{created_accounts['CLIENT']}/management/", {
        "role": "CLIENT", "is_active": True,
    }, content_type="application/json")
    assert enable.status_code == 200
    assert client.post(f"/api/v1/organizations/{organization_id}/users/",
                       {"user_id": created_accounts["CLIENT"]}, content_type="application/json").status_code == 201
    client_account = get_user_model().objects.get(pk=created_accounts["CLIENT"])
    role_client = mfa_force_login(DjangoClient(), client_account)
    assert any(item["id"] == organization_id for item in role_client.get("/api/v1/organizations/").json())
    revoke = client.delete(
        f"/api/v1/organizations/{organization_id}/users/{created_accounts['CLIENT']}/")
    assert revoke.status_code == 204
    assert role_client.get("/api/v1/organizations/").json() == []
    assert role_client.get("/api/v1/plans/", {"organization_id": organization_id}).json() == []


def test_claims_explorer_organization_scoping_and_privacy(client, db):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client as DjangoClient
    from pricing.models import ClaimsExplorerDataset, PlanOrganization, PlanOrganizationAccess

    # Create two organizations
    org1 = PlanOrganization.objects.create(organization_name="Scoped Org Alpha", organization_type="employer")
    org2 = PlanOrganization.objects.create(organization_name="Scoped Org Beta", organization_type="employer")

    # Analyst role group
    analyst_group, _ = Group.objects.get_or_create(name="ANALYST")
    user = get_user_model().objects.create_user(username="scoped-analyst", password="test-password")
    user.groups.add(analyst_group)

    analyst_client = DjangoClient()
    mfa_force_login(analyst_client, user)

    # User with no organization access assigned gets 403
    res_no_org = analyst_client.get("/api/v1/claims/")
    assert res_no_org.status_code == 400

    # Grant user access to Org 1 only
    PlanOrganizationAccess.objects.create(organization=org1, user=user)

    unauthorized_registration = analyst_client.post("/api/v1/claims/datasets/", {
        "organization_id": org1.pk,
        "dataset_identifier": "desynpuf_inpatient_claims_sample_1",
    }, content_type="application/json")
    assert unauthorized_registration.status_code == 403

    reviewer_group, _ = Group.objects.get_or_create(name="REVIEWER")
    reviewer_user = get_user_model().objects.create_user(username="claims-reviewer", password="test-password")
    reviewer_user.groups.add(reviewer_group)
    PlanOrganizationAccess.objects.create(organization=org1, user=reviewer_user)
    reviewer_client = DjangoClient()
    mfa_force_login(reviewer_client, reviewer_user)
    assert reviewer_client.get("/api/v1/claims/datasets/", {"organization_id": org1.pk}).status_code == 403
    assert reviewer_client.get("/api/v1/claims/", {
        "organization_id": org1.pk, "dataset": "desynpuf_outpatient_claims_sample_1",
    }).status_code == 403

    dataset_id = "desynpuf_outpatient_claims_sample_1"
    ClaimsExplorerDataset.objects.create(
        organization=org1, dataset_identifier=dataset_id,
    )
    ClaimsExplorerDataset.objects.create(
        organization=org2, dataset_identifier=dataset_id,
    )

    # User can query only the registered dataset under Org 1.
    res_org1 = analyst_client.get("/api/v1/claims/", {
        "organization_id": org1.pk, "dataset": dataset_id, "page_size": 5,
    })
    assert res_org1.status_code == 200
    assert res_org1.json()["organization_id"] == org1.pk
    assert "normalized" not in str(res_org1.json())

    # User CANNOT query Org 2 (cross-organization access denied)
    res_cross_org = analyst_client.get("/api/v1/claims/", {
        "organization_id": org2.pk, "dataset": dataset_id, "page_size": 5,
    })
    assert res_cross_org.status_code == 403

    # A guessed claim ID cannot bypass the organization or dataset boundary.
    detail_cross = analyst_client.get("/api/v1/claims/CLM12345/", {
        "organization_id": org2.pk, "dataset": dataset_id,
    })
    assert detail_cross.status_code == 403
    unregistered_org1 = analyst_client.get("/api/v1/claims/", {
        "organization_id": org1.pk,
        "dataset": "desynpuf_inpatient_claims_sample_1",
    })
    assert unregistered_org1.status_code == 403


def test_plan_audit_excludes_review_range_hospital_rates(client, monkeypatch):
    from decimal import Decimal
    from pricing import plan_audit_engine

    queries = []
    rows = [
        {
            "hcpcs": "J9271", "hospital_label": "Verified Hospital",
            "setting": "outpatient_hospital", "benchmark_quarter": "2026Q4",
            "price_per_billing_unit": "100.00", "billing_units": 1,
            "status": "review_range", "price_type": "negotiated_dollar",
            "source_file": "outlier.csv", "source_sha256": "a" * 64,
            "effective_start": "2026-01-01", "effective_end": "2026-12-31",
        },
        {
            "hcpcs": "J9271", "hospital_label": "Verified Hospital",
            "setting": "outpatient_hospital", "benchmark_quarter": "2026Q4",
            "price_per_billing_unit": "90.00", "billing_units": 1,
            "status": "ok", "price_type": "negotiated_dollar",
            "source_file": "validated.csv", "source_sha256": "b" * 64,
            "effective_start": "2026-01-01", "effective_end": "2026-12-31",
        },
    ]

    def query(sql, params, **kwargs):
        queries.append(sql)
        return [row for row in rows if row["status"] == "ok"] if "status = 'ok'" in sql else rows

    monkeypatch.setattr(plan_audit_engine, "_verified_site_names",
                        lambda: {"verified hospital": {"1000000004"}})
    monkeypatch.setattr(plan_audit_engine, "_rate_covers_quarter", lambda row, quarter: True)
    monkeypatch.setattr(plan_audit_engine.data, "query", query)

    result, errors = plan_audit_engine._hospital_rows(["J9271"], ["2026Q4"])
    assert errors == 0
    assert result[("J9271", "1000000004", "2026Q4", "outpatient_hospital")]["price"] == Decimal("90.00")
    assert len(queries) == 1
    assert "status = 'ok'" in queries[0]
    assert "review_range" not in queries[0]


def test_plan_audit_asp_lookup_never_falls_back_to_latest_quarter(client):
    from pricing.plan_audit_engine import _asp_rows

    historical, errors = _asp_rows(["J9271"], ["2008Q1"])
    assert historical == {}
    assert errors == 0


def test_end_to_end_plan_audit_workflow(client, db, tmp_path, monkeypatch):
    import csv
    import io
    import json
    from decimal import Decimal
    import yaml
    from argparse import Namespace
    from client_extractor.src.cli import extract_claims
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client as DjangoClient

    # 1. Admin creates Organization and Plan
    org_res = client.post("/api/v1/organizations/", {
        "organization_name": "E2E Audit Health Plan",
        "organization_type": "employer",
    }, content_type="application/json")
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    plan_ref = "PLAN-E2E-2026"
    plan_res = client.post("/api/v1/plans/", {
        "organization_id": org_id,
        "plan_name": "E2E Comprehensive PPO",
        "plan_reference": plan_ref,
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
    }, content_type="application/json")
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    # 2. Setup Reviewer user with organization access
    rev_group, _ = Group.objects.get_or_create(name="REVIEWER")
    client_group, _ = Group.objects.get_or_create(name="CLIENT")
    analyst_group, _ = Group.objects.get_or_create(name="ANALYST")

    def create_role_account(username, role):
        response = client.post("/api/v1/user-accounts/", {
            "username": username, "role": role, "password": "Meshkor-Test-Account-2026!",
        }, content_type="application/json")
        assert response.status_code == 201, response.content
        return get_user_model().objects.get(pk=response.json()["id"])

    rev_user = create_role_account("e2e-reviewer", "REVIEWER")
    grant_res = client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": rev_user.pk}, content_type="application/json")
    assert grant_res.status_code == 201, grant_res.content
    assert grant_res.json()["created"] is True
    duplicate_grant = client.post(f"/api/v1/organizations/{org_id}/users/",
                                  {"user_id": rev_user.pk}, content_type="application/json")
    assert duplicate_grant.status_code == 200
    assert duplicate_grant.json()["created"] is False
    from pricing.models import PlanOrganizationAccess
    assert PlanOrganizationAccess.objects.filter(organization_id=org_id, user=rev_user).count() == 1

    rev_client = DjangoClient()
    mfa_force_login(rev_client, rev_user)
    assert rev_client.get("/api/v1/organizations/").status_code == 200
    assert any(item["id"] == org_id for item in rev_client.get("/api/v1/organizations/").json())
    assert rev_client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": rev_user.pk},
                           content_type="application/json").status_code == 403
    rev_b_user = get_user_model().objects.create_user(username="e2e-reviewer-b", password="test-password")
    rev_b_user.groups.add(rev_group)
    assert rev_client.delete(f"/api/v1/organizations/{org_id}/users/{rev_b_user.pk}/").status_code == 403
    assert client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": rev_b_user.pk},
                       content_type="application/json").status_code in {200, 201}
    rev_b_client = DjangoClient()
    mfa_force_login(rev_b_client, rev_b_user)

    client_user = create_role_account("e2e-client-user", "CLIENT")
    assert client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": client_user.pk},
                       content_type="application/json").status_code in {200, 201}
    client_test_client = DjangoClient()
    mfa_force_login(client_test_client, client_user)
    assert client_test_client.post(f"/api/v1/organizations/{org_id}/users/",
                                   {"user_id": rev_user.pk}, content_type="application/json").status_code == 403
    analyst_user = create_role_account("mk06-analyst", "ANALYST")
    analyst_client = DjangoClient()
    mfa_force_login(analyst_client, analyst_user)
    assert analyst_client.post(f"/api/v1/organizations/{org_id}/users/",
                               {"user_id": rev_user.pk}, content_type="application/json").status_code == 403
    mixed_client_reviewer = get_user_model().objects.create_user(
        username="mk05-mixed-assigned-reviewer", password="test-password")
    mixed_client_reviewer.groups.add(client_group, rev_group)
    assert client.post(f"/api/v1/organizations/{org_id}/users/",
                       {"user_id": mixed_client_reviewer.pk}, content_type="application/json").status_code in {200, 201}
    mixed_client_reviewer_client = DjangoClient()
    mfa_force_login(mixed_client_reviewer_client, mixed_client_reviewer)
    assert client.post(f"/api/v1/organizations/{org_id}/users/",
                       {"user_id": client_user.pk}, content_type="application/json").status_code == 200
    assert PlanOrganizationAccess.objects.filter(organization_id=org_id, user=client_user).count() == 1
    for candidate in (
        get_user_model().objects.create_user(username="mk06-no-role", password="test-password"),
        get_user_model().objects.create_user(username="mk06-inactive-reviewer", password="test-password",
                                             is_active=False),
        get_user_model().objects.create_superuser(username="mk06-target-superuser",
                                                   email="mk06@example.invalid", password="test-password"),
    ):
        if candidate.username == "mk06-inactive-reviewer":
            candidate.groups.add(rev_group)
        assert client.post(f"/api/v1/organizations/{org_id}/users/",
                           {"user_id": candidate.pk}, content_type="application/json").status_code == 400
    assert client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": 99999999},
                       content_type="application/json").status_code == 400
    assert client.post(f"/api/v1/organizations/{org_id}/users/", {},
                       content_type="application/json").status_code == 400

    # 3. Run the actual extractor on isolated fictional TEST claims.
    source_path = tmp_path / "claims_TEST.csv"
    claim_fields = [
        "claim_id", "service_date", "hcpcs_code", "site_npi", "units", "allowed_amount",
        "paid_amount", "member_id", "claim_status", "plan_id", "service_setting",
    ]
    with source_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=claim_fields)
        writer.writeheader()
        for index in range(11):
            writer.writerow({
                "claim_id": f"TEST-CLAIM-A-{index}", "service_date": "2026-10-15",
                "hcpcs_code": "J9271", "site_npi": "1000000004",
                "units": "5" if index == 10 else "0.5",
                "allowed_amount": "1400" if index == 0 else "10",
                "paid_amount": "1100" if index == 0 else "10",
                "member_id": f"TEST-MEMBER-A-{index}", "claim_status": "paid",
                "plan_id": "PLAN-TEST-ID", "service_setting": "outpatient_hospital",
            })
        for index in range(14):
            writer.writerow({
                "claim_id": f"TEST-CLAIM-B-{index}", "service_date": "2026-10-15",
                "hcpcs_code": "J9271", "site_npi": "1000000012",
                "units": "1.75" if index == 13 else "0.25",
                "allowed_amount": "470" if index == 0 else "10",
                "paid_amount": "370" if index == 0 else "10",
                "member_id": f"TEST-MEMBER-B-{index}", "claim_status": "paid",
                "plan_id": "PLAN-TEST-ID", "service_setting": "outpatient_hospital",
            })
    config_path = tmp_path / "client_config_TEST.yaml"
    config_path.write_text(yaml.safe_dump({
        "plan_id": "PLAN-TEST-ID", "plan_reference": plan_ref,
        "hcpcs_billing_units": {
            "J9271": {"qty": 1, "unit": "UNIT", "verification_status": "validated",
                      "source_reference": "TEST-only unit evidence", "source_sha256": "a" * 64},
        },
    }), encoding="utf-8")
    output_path = tmp_path / "extractor_output"
    assert extract_claims(Namespace(
        claims=source_path, config=config_path, output=output_path,
    )) == 0
    summary_path = output_path / "claims_summary.csv"
    manifest_path = output_path / "manifest.json"
    csv_bytes = summary_path.read_bytes()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_bytes = manifest_path.read_bytes()

    legacy_manifest = dict(manifest_data)
    legacy_manifest.pop("complementary_suppression_applied")
    legacy_manifest_bytes = json.dumps(legacy_manifest).encode("utf-8")
    rejected_import = client.post("/api/v1/plan-audits/import-summary/", {
        "organization_id": org_id,
        "plan_id": plan_id,
        "file": SimpleUploadedFile("claims_summary.csv", csv_bytes, content_type="text/csv"),
        "manifest": SimpleUploadedFile("manifest.json", legacy_manifest_bytes, content_type="application/json"),
    })
    assert rejected_import.status_code == 400

    import_res = client.post("/api/v1/plan-audits/import-summary/", {
        "organization_id": org_id,
        "plan_id": plan_id,
        "file": SimpleUploadedFile("claims_summary.csv", csv_bytes, content_type="text/csv"),
        "manifest": SimpleUploadedFile("manifest.json", manifest_bytes, content_type="application/json"),
    })
    assert import_res.status_code == 201, import_res.content
    import_id = import_res.json()["id"]
    duplicate_import = client.post("/api/v1/plan-audits/import-summary/", {
        "organization_id": org_id, "plan_id": plan_id,
        "file": SimpleUploadedFile("claims_summary.csv", csv_bytes, content_type="text/csv"),
        "manifest": SimpleUploadedFile("manifest.json", manifest_bytes, content_type="application/json"),
    })
    assert duplicate_import.status_code == 409

    bad_rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    bad_rows[1][0] = "OTHER-PLAN"
    bad_csv = io.StringIO()
    csv.writer(bad_csv, lineterminator="\n").writerows(bad_rows)
    bad_bytes = bad_csv.getvalue().encode("utf-8")
    import hashlib
    bad_manifest = dict(manifest_data, sha256=hashlib.sha256(bad_bytes).hexdigest())
    invalid_plan_import = client.post("/api/v1/plan-audits/import-summary/", {
        "organization_id": org_id, "plan_id": plan_id,
        "file": SimpleUploadedFile("claims_summary.csv", bad_bytes, content_type="text/csv"),
        "manifest": SimpleUploadedFile("manifest.json", json.dumps(bad_manifest).encode(), content_type="application/json"),
    })
    assert invalid_plan_import.status_code == 400
    assert any("plan_reference" in row["reason"]
               for row in invalid_plan_import.json()["validation_summary"]["errors"])

    # 4. Upload network roster
    roster_rows = [
        ["provider_npi", "provider_name", "network_name", "network_status", "effective_start", "effective_end", "service_location", "applicable_plan_reference"],
        ["1000000004", "Primary Cancer Center", "Choice Network", "in_network", "2026-01-01", "2026-12-31", "Columbus OH", plan_ref],
        ["1000000012", "Alternative Infusion Clinic", "Choice Network", "in_network", "2026-01-01", "2026-12-31", "Dublin OH", plan_ref],
    ]
    roster_out = io.StringIO()
    csv.writer(roster_out, lineterminator="\n").writerows(roster_rows)
    roster_bytes = roster_out.getvalue().encode("utf-8")

    roster_res = client.post(f"/api/v1/plans/{plan_id}/network-roster/", {
        "file": SimpleUploadedFile("network_roster.csv", roster_bytes, content_type="text/csv"),
    })
    assert roster_res.status_code == 201, roster_res.content
    coverage_res = client.get(
        f"/api/v1/plans/{plan_id}/network-roster/?summary_import_id={import_id}"
    )
    assert coverage_res.status_code == 200
    assert coverage_res.json()["quarter_coverage"]["status_counts"] == {"IN_NETWORK": 2}

    conflict_csv = io.StringIO()
    csv.writer(conflict_csv, lineterminator="\n").writerows([
        ["provider_npi", "provider_name", "network_name", "network_status",
         "effective_start", "effective_end", "service_location", "applicable_plan_reference"],
        ["1000000004", "Primary Cancer Center", "Choice Network", "out_of_network",
         "2026-01-01", "2026-12-31", "Columbus OH", plan_ref],
    ])
    conflicting_roster = conflict_csv.getvalue().encode("utf-8")
    conflicting_res = client.post(f"/api/v1/plans/{plan_id}/network-roster/", {
        "file": SimpleUploadedFile("conflicting_roster.csv", conflicting_roster, content_type="text/csv"),
    })
    assert conflicting_res.status_code == 400
    assert client.get(f"/api/v1/plans/{plan_id}/network-roster/").json()["entry_count"] == 2

    # 5. Create Plan Audit
    create_audit_res = client.post("/api/v1/plan-audits/create/", {
        "organization_id": org_id,
        "plan_id": plan_id,
        "summary_import_id": import_id,
        "audit_name": "2026 Q4 Oncology Infusion Audit",
        "reporting_period": "2026-01-01/2026-12-31",
        "created_by_id": rev_user.pk,
    }, content_type="application/json")
    assert create_audit_res.status_code == 201, create_audit_res.content
    audit_id = create_audit_res.json()["id"]
    superadmin_id = get_user_model().objects.get(username="audit-test-admin").pk
    assert create_audit_res.json()["created_by_id"] == superadmin_id

    from pricing.plan_audit_common import is_client_only
    assert not is_client_only(get_user_model().objects.get(pk=superadmin_id))
    assert is_client_only(client_user)
    assert not is_client_only(rev_user)
    superuser_audits = client.get("/api/v1/plan-audits/")
    assert superuser_audits.status_code == 200
    assert any(row["id"] == audit_id for row in superuser_audits.json()["results"])
    superuser_draft = client.get(f"/api/v1/plan-audits/{audit_id}/")
    assert superuser_draft.status_code == 200
    assert superuser_draft.json()["status"] == "draft"
    assert not superuser_draft.json()["can_view_results"]
    assert superuser_draft.json()["created_by_id"] == superadmin_id
    assert client.put(f"/api/v1/plan-audits/{audit_id}/", {"created_by_id": rev_user.pk},
                      content_type="application/json").status_code == 405
    assert client.patch(f"/api/v1/plan-audits/{audit_id}/", {"created_by_id": rev_user.pk},
                        content_type="application/json").status_code == 405

    client_drafts = client_test_client.get("/api/v1/plan-audits/")
    assert client_drafts.status_code == 200
    client_draft = next(row for row in client_drafts.json()["results"] if row["id"] == audit_id)
    assert client_draft["can_view_results"] is False
    assert client_draft["summary"] == {}
    assert client_draft["result_fingerprint"] is None
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    for suffix in ("overview/", "results/", "drug-analysis/", "hospital-comparison/",
                   "asp-benchmark/", "historical-spending/", "savings/", "quality/",
                   "network-validation/", "report/", "export-csv/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}").status_code == 404
    assert client_test_client.post(f"/api/v1/plan-audits/{audit_id}/run/").status_code == 403
    assert rev_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    assert any(row["id"] == audit_id for row in
               rev_client.get("/api/v1/plan-audits/").json()["results"])
    assert rev_client.post(f"/api/v1/plan-audits/{audit_id}/run/").status_code == 403

    # 6. Run Plan Audit
    run_res = client.post(f"/api/v1/plan-audits/{audit_id}/run/", {
        "initiated_by_id": rev_user.pk,
    }, content_type="application/json")
    assert run_res.status_code == 200, run_res.content
    audit_data = run_res.json()
    assert audit_data["status"] == "needs_review"
    assert audit_data["run_initiated_by_id"] == superadmin_id
    assert client.get("/api/v1/plan-audits/").status_code == 200
    assert client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    assert rev_client.get(f"/api/v1/plan-audits/{audit_id}/results/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/results/").status_code == 404
    assert mixed_client_reviewer_client.get(f"/api/v1/plan-audits/{audit_id}/results/").status_code == 200

    # 7. Check Audit Overview, Results, and Quality
    overview_res = client.get(f"/api/v1/plan-audits/{audit_id}/overview/")
    assert overview_res.status_code == 200
    metrics = overview_res.json()["metrics"]
    assert metrics["totals_scope"] == "visible_approved_aggregate_rows_only"
    assert metrics["potential_allowed_savings"] is None

    results_res = client.get(f"/api/v1/plan-audits/{audit_id}/results/")
    assert results_res.status_code == 200
    assert results_res.json()["count"] == 2
    result = results_res.json()["results"][0]
    assert result["total_units"] is not None
    assert result["total_allowed_amount"] is not None
    assert result["total_paid_amount"] is not None
    assert result["source_references"]["claims_summary_import_id"] == import_id
    assert "asp_source_file" in result["source_references"]
    assert result["source_references"]["unit_review_status"] == "unresolved"
    assert Decimal(result["plan_allowed_price_per_unit"]) == Decimal("150")
    assert Decimal(result["plan_paid_price_per_unit"]) == Decimal("120")
    assert client.get(f"/api/v1/plan-audits/{audit_id}/savings/").json()["results"] == []

    # The actual unresolved engine output must not be publishable.
    from pricing.models import (AuditEvent, AuditReview, PlanAudit, PlanAuditResult,
                                PlanAuditRun, SavingsOpportunity)
    from pricing.plan_audit_common import current_audit_run, run_result_fingerprint
    audit_obj = PlanAudit.objects.get(pk=audit_id)
    run_obj = current_audit_run(audit_obj)
    unresolved_binding = {"version": run_obj.version,
                          "result_fingerprint": run_result_fingerprint(run_obj)}
    report_response = client.post(f"/api/v1/plan-audits/{audit_id}/generate-report/")
    assert report_response.status_code == 200
    run_obj.refresh_from_db()
    audit_obj.refresh_from_db()
    assert report_response.json()["report_fingerprint"] == run_obj.report_fingerprint
    from django.utils.dateparse import parse_datetime
    assert parse_datetime(report_response.json()["report_generated_at"]) == audit_obj.report_generated_at
    unresolved_approval = rev_client.post(f"/api/v1/plan-audits/{audit_id}/approve/",
        {"comments": "Unresolved fixture must not publish.", **unresolved_binding},
        content_type="application/json")
    assert unresolved_approval.status_code == 409
    assert unresolved_approval.json()["error"] == "Resolve blocking data quality issues before publication."
    audit_obj.refresh_from_db()
    run_obj.refresh_from_db()
    assert run_obj.calculation_status == "completed"
    assert run_obj.publication_status == "pending"
    assert audit_obj.published_version is None
    assert not AuditReview.objects.filter(audit_run=run_obj, review_status="approved").exists()
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/results/").status_code == 404

    # Legacy rows without current creator/run provenance cannot be published through the API.
    from django.utils import timezone
    legacy_audit_response = client.post("/api/v1/plan-audits/create/", {
        "organization_id": org_id, "plan_id": plan_id, "summary_import_id": import_id,
        "audit_name": "MK-04 legacy provenance fail-closed", "reporting_period": "2026Q4",
    }, content_type="application/json")
    assert legacy_audit_response.status_code == 201
    legacy_audit = PlanAudit.objects.get(pk=legacy_audit_response.json()["id"])
    legacy_run = PlanAuditRun.objects.create(
        plan_audit=legacy_audit, version=1, calculation_status="legacy_unverified",
        publication_status="unverified", summary_import_id=import_id,
        initiated_by=None, started_at=timezone.now(),
    )
    legacy_audit.current_version = 1
    legacy_audit.status = "needs_review"
    legacy_audit.save(update_fields=["current_version", "status"])
    legacy_approval = rev_client.post(
        f"/api/v1/plan-audits/{legacy_audit.pk}/approve/",
        {"comments": "Legacy version without provenance.", "version": 1,
         "result_fingerprint": ""}, content_type="application/json")
    assert legacy_approval.status_code == 409
    legacy_run.refresh_from_db()
    legacy_audit.refresh_from_db()
    assert legacy_run.publication_status == "unverified"
    assert legacy_audit.published_version is None

    # Start v2 with validated fixture evidence supplied during the active calculation.
    from pricing import plan_audit_run
    original_engine = plan_audit_run.run_plan_audit

    def validated_fixture_engine(audit, active_run, heartbeat=None):
        summary = original_engine(audit, active_run, heartbeat=heartbeat)
        for row in PlanAuditResult.objects.filter(audit_run=active_run):
            refs = dict(row.source_references)
            refs["unit_review_status"] = "validated"
            refs["unit_review_source_sha256"] = "f" * 64
            row.data_quality_status = "VALID"
            row.source_references = refs
            row.save(update_fields=["data_quality_status", "source_references"])
        SavingsOpportunity.objects.create(
            plan_audit=audit, audit_run=active_run, hcpcs_code="J9271",
            quarter="2026Q4", service_setting="outpatient_hospital",
            current_site_npi="1000000004", alternative_site_npi="1000000012",
            current_allowed_price_per_unit=Decimal("150"),
            alternative_allowed_price_per_unit=Decimal("120"), units=Decimal("10"),
            potential_allowed_savings=Decimal("300"), network_status="IN_NETWORK",
            source_references={"fixture": "isolated validation lifecycle test"},
        )
        return summary

    monkeypatch.setattr(plan_audit_run, "run_plan_audit", validated_fixture_engine)

    analyst_group, _ = Group.objects.get_or_create(name="ANALYST")

    def make_contributor(username, roles):
        contributor = get_user_model().objects.create_user(username=username, password="test-password")
        contributor.groups.add(*roles)
        assert client.post(f"/api/v1/organizations/{org_id}/users/", {"user_id": contributor.pk},
                           content_type="application/json").status_code in {200, 201}
        contributor_client = DjangoClient()
        mfa_force_login(contributor_client, contributor)
        return contributor, contributor_client

    run_contributor, run_contributor_client = make_contributor(
        "mk04-run-contributor", [analyst_group, rev_group])
    artifact_contributor, artifact_contributor_client = make_contributor(
        "mk04-artifact-contributor", [analyst_group, rev_group])
    csv_contributor, csv_contributor_client = make_contributor(
        "mk04-csv-contributor", [analyst_group, rev_group])
    analyst_only, analyst_only_client = make_contributor("mk04-analyst-only", [analyst_group])
    assert analyst_only_client.get("/api/v1/plan-audits/").status_code == 200
    assert analyst_only_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    assert rev_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    # Creator, run initiator, and artifact builder are independently checked.
    contributor_audit_response = client.post("/api/v1/plan-audits/create/", {
        "organization_id": org_id, "plan_id": plan_id, "summary_import_id": import_id,
        "audit_name": "MK-04 contributor independence", "reporting_period": "2026-01-01/2026-12-31",
    }, content_type="application/json")
    assert contributor_audit_response.status_code == 201
    contributor_audit_id = contributor_audit_response.json()["id"]
    assert run_contributor_client.post(f"/api/v1/plan-audits/{contributor_audit_id}/run/").status_code == 200
    contributor_audit = PlanAudit.objects.get(pk=contributor_audit_id)
    contributor_run = current_audit_run(contributor_audit)
    contributor_binding = {"version": contributor_run.version,
                           "result_fingerprint": contributor_run.result_fingerprint}
    assert artifact_contributor_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/generate-report/").status_code == 200
    contributor_artifacts = {
        artifact.artifact_type: artifact for artifact in contributor_run.artifacts.all()
    }
    contributor_artifacts["csv"].created_by_id = csv_contributor.pk
    contributor_artifacts["csv"].save(update_fields=["created_by"])
    assert contributor_artifacts["pdf"].created_by_id == artifact_contributor.pk
    assert contributor_artifacts["csv"].created_by_id == csv_contributor.pk

    def assert_not_published(response, audit_record, run_record, expected_status=403):
        assert response.status_code == expected_status, response.content
        audit_record.refresh_from_db()
        run_record.refresh_from_db()
        assert audit_record.published_version is None
        assert run_record.publication_status == "pending"
        assert not AuditReview.objects.filter(audit_run=run_record, review_status="approved").exists()
        assert not AuditEvent.objects.filter(
            action="plan_audit_approved", entity_id=str(audit_record.pk)).exists()
        for suffix in ("overview/", "results/", "report/", "export-csv/"):
            assert client_test_client.get(
                f"/api/v1/plan-audits/{audit_record.pk}/{suffix}").status_code == 404

    stale_fingerprint_attempt = rev_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "Stale result binding.", "version": contributor_binding["version"],
         "result_fingerprint": "0" * 64}, content_type="application/json")
    assert_not_published(stale_fingerprint_attempt, contributor_audit, contributor_run, expected_status=409)
    creator_attempt = client.post(f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "Creator cannot approve.", **contributor_binding}, content_type="application/json")
    assert_not_published(creator_attempt, contributor_audit, contributor_run)
    runner_attempt = run_contributor_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "Run initiator cannot approve.", **contributor_binding}, content_type="application/json")
    assert_not_published(runner_attempt, contributor_audit, contributor_run)
    artifact_attempt = artifact_contributor_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "PDF builder cannot approve.", **contributor_binding}, content_type="application/json")
    assert_not_published(artifact_attempt, contributor_audit, contributor_run)
    csv_builder_attempt = csv_contributor_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "CSV builder cannot approve.", **contributor_binding}, content_type="application/json")
    assert_not_published(csv_builder_attempt, contributor_audit, contributor_run)
    analyst_attempt = analyst_only_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "Analyst without reviewer role cannot approve.", **contributor_binding},
        content_type="application/json")
    assert_not_published(analyst_attempt, contributor_audit, contributor_run)
    assert client_test_client.get(f"/api/v1/plan-audits/{contributor_audit_id}/report/").status_code == 404
    independent_review = rev_client.post(
        f"/api/v1/plan-audits/{contributor_audit_id}/approve/",
        {"comments": "Independent reviewer approval.", **contributor_binding}, content_type="application/json")
    assert independent_review.status_code == 200

    # Missing historical identity at any contributor stage fails closed.
    missing_identity_response = client.post("/api/v1/plan-audits/create/", {
        "organization_id": org_id, "plan_id": plan_id, "summary_import_id": import_id,
        "audit_name": "MK-04 missing contributor identity", "reporting_period": "2026-01-01/2026-12-31",
    }, content_type="application/json")
    assert missing_identity_response.status_code == 201
    missing_identity_id = missing_identity_response.json()["id"]
    assert run_contributor_client.post(f"/api/v1/plan-audits/{missing_identity_id}/run/").status_code == 200
    missing_audit = PlanAudit.objects.get(pk=missing_identity_id)
    missing_run = current_audit_run(missing_audit)
    missing_binding = {"version": missing_run.version, "result_fingerprint": missing_run.result_fingerprint}
    assert artifact_contributor_client.post(
        f"/api/v1/plan-audits/{missing_identity_id}/generate-report/").status_code == 200
    creator_id, initiator_id = missing_audit.created_by_id, missing_run.initiated_by_id
    artifact_rows = list(missing_run.artifacts.all())
    missing_audit.created_by_id = None
    missing_audit.save(update_fields=["created_by"])
    missing_creator_attempt = rev_client.post(f"/api/v1/plan-audits/{missing_identity_id}/approve/",
        {"comments": "Missing creator must fail closed.", **missing_binding}, content_type="application/json")
    assert_not_published(missing_creator_attempt, missing_audit, missing_run, expected_status=409)
    missing_audit.created_by_id = creator_id
    missing_audit.save(update_fields=["created_by"])
    missing_run.initiated_by_id = None
    missing_run.save(update_fields=["initiated_by"])
    missing_initiator_attempt = rev_client.post(f"/api/v1/plan-audits/{missing_identity_id}/approve/",
        {"comments": "Missing initiator must fail closed.", **missing_binding}, content_type="application/json")
    assert_not_published(missing_initiator_attempt, missing_audit, missing_run, expected_status=409)
    missing_run.initiated_by_id = initiator_id
    missing_run.save(update_fields=["initiated_by"])
    missing_builder_types = set()
    for artifact in artifact_rows:
        builder_id = artifact.created_by_id
        artifact.created_by_id = None
        artifact.save(update_fields=["created_by"])
        missing_builder_attempt = rev_client.post(f"/api/v1/plan-audits/{missing_identity_id}/approve/", {
            "comments": f"Missing {artifact.artifact_type} builder must fail closed.", **missing_binding,
        }, content_type="application/json")
        assert_not_published(missing_builder_attempt, missing_audit, missing_run, expected_status=409)
        missing_builder_types.add(artifact.artifact_type)
        artifact.created_by_id = builder_id
        artifact.save(update_fields=["created_by"])
    assert missing_builder_types == {"pdf", "csv"}
    independent_superadmin = get_user_model().objects.create_superuser(
        username="mk04-independent-superadmin", email="mk04-superadmin@example.invalid", password="test-password")
    independent_superadmin_client = DjangoClient()
    mfa_force_login(independent_superadmin_client, independent_superadmin)
    superadmin_approval = independent_superadmin_client.post(
        f"/api/v1/plan-audits/{missing_identity_id}/approve/",
        {"comments": "Independent SUPER_ADMIN approval.", **missing_binding}, content_type="application/json")
    assert superadmin_approval.status_code == 200

    valid_rerun = client.post(f"/api/v1/plan-audits/{audit_id}/run/")
    assert valid_rerun.status_code == 200, valid_rerun.content
    audit_obj.refresh_from_db()
    run_obj = current_audit_run(audit_obj)
    artifact_res = client.post(f"/api/v1/plan-audits/{audit_id}/generate-report/", {
        "created_by_id": rev_user.pk,
    }, content_type="application/json")
    assert artifact_res.status_code == 200
    contributor_metadata = client.get(f"/api/v1/plan-audits/{audit_id}/").json()
    assert contributor_metadata["created_by_id"] == superadmin_id
    assert contributor_metadata["run_initiated_by_id"] == superadmin_id
    assert [builder["id"] for builder in contributor_metadata["artifact_builders"]] == [superadmin_id, superadmin_id]
    binding = {"version": run_obj.version, "result_fingerprint": run_obj.result_fingerprint}

    # MK-04 reproduction: the SUPER_ADMIN created, ran, and built this version.
    self_approval = client.post(f"/api/v1/plan-audits/{audit_id}/approve/", {
        "comments": "Attempted self-approval reproduction.", **binding,
        "created_by_id": rev_user.pk, "initiated_by_id": rev_user.pk,
        "artifact_builder_ids": [],
    }, content_type="application/json")
    assert self_approval.status_code == 403
    run_obj.refresh_from_db()
    audit_obj.refresh_from_db()
    assert run_obj.publication_status == "pending"
    assert audit_obj.published_version is None
    assert not AuditReview.objects.filter(audit_run=run_obj, review_status="approved").exists()
    assert not AuditEvent.objects.filter(action="plan_audit_approved", entity_id=str(audit_id)).exists()
    for suffix in ("overview/", "results/", "report/", "export-csv/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}").status_code == 404

    # 8. Review workflow: Reviewer submits comment and approves
    # Non-reviewer gets 403
    viewer_group, _ = Group.objects.get_or_create(name="Viewer")
    unauth_user = get_user_model().objects.create_user(username="unauth-viewer", password="test-password")
    unauth_user.groups.add(viewer_group)
    unauth_client = DjangoClient()
    mfa_force_login(unauth_client, unauth_user)

    unauth_approve = unauth_client.post(f"/api/v1/plan-audits/{audit_id}/approve/")
    assert unauth_approve.status_code == 403

    # Reviewer submits comment
    comment_res = rev_client.post(f"/api/v1/plan-audits/{audit_id}/review/", {
        "comments": "Reviewed aggregate rows and ASP benchmarks; verified in-network clinical status.",
        **binding,
    }, content_type="application/json")
    assert comment_res.status_code == 201
    second_comment = rev_client.post(f"/api/v1/plan-audits/{audit_id}/review/", {
        "comments": "Confirmed that source aggregates remain distinct by HCPCS, site, and quarter.",
        **binding,
    }, content_type="application/json")
    assert second_comment.status_code == 201
    assert second_comment.json()["id"] != comment_res.json()["id"]

    # Reviewer approves audit
    approve_res = rev_client.post(f"/api/v1/plan-audits/{audit_id}/approve/", {
        "comments": "Approved after clinical verification.",
        **binding,
    }, content_type="application/json")
    assert approve_res.status_code == 200
    assert approve_res.json()["review_status"] == "approved"
    published_run = run_obj
    published_result = PlanAuditResult.objects.filter(audit_run=published_run).first()
    published_saving = SavingsOpportunity.objects.get(audit_run=published_run)
    from django.core.exceptions import ValidationError
    for write_attempt in (
        lambda: published_result.save(),
        lambda: published_result.delete(),
        lambda: PlanAuditResult.objects.filter(pk=published_result.pk).update(total_units=Decimal("0")),
        lambda: PlanAuditResult.objects.filter(pk=published_result.pk).delete(),
        lambda: PlanAuditResult.objects.bulk_create([
            PlanAuditResult(audit_run=published_run),
        ]),
        lambda: published_saving.save(),
        lambda: published_saving.delete(),
        lambda: SavingsOpportunity.objects.filter(pk=published_saving.pk).update(
            potential_allowed_savings=Decimal("0")),
        lambda: SavingsOpportunity.objects.filter(pk=published_saving.pk).delete(),
        lambda: SavingsOpportunity.objects.bulk_create([
            SavingsOpportunity(audit_run=published_run),
        ]),
    ):
        with pytest.raises(ValidationError):
            write_attempt()
    review_history = rev_client.get(f"/api/v1/plan-audits/{audit_id}/review/")
    assert review_history.status_code == 200
    assert len(review_history.json()) == 3
    assert {item["review_status"] for item in review_history.json()} == {"submitted", "approved"}

    # 9. Generate Report and Download PDF & CSV
    gen_res = artifact_res

    pdf_res = client.get(f"/api/v1/plan-audits/{audit_id}/report/")
    assert pdf_res.status_code == 200
    assert pdf_res["Content-Type"] == "application/pdf"
    assert len(pdf_res.content) > 100

    csv_res = client.get(f"/api/v1/plan-audits/{audit_id}/export-csv/")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res["Content-Type"]
    assert "plan_allowed_price_per_unit" in csv_res.content.decode("utf-8")
    assert "source_references" in csv_res.content.decode("utf-8")

    # 10. Historical Spending Filtering & Quality Breakdown
    hs_all = client.get(f"/api/v1/plan-audits/{audit_id}/historical-spending/")
    assert hs_all.status_code == 200
    assert hs_all.json()["available"] is True
    assert len(hs_all.json()["by_quarter"]) == 1
    assert len(hs_all.json()["by_site"]) == 2

    # Filter by specific site_npi
    hs_site = client.get(f"/api/v1/plan-audits/{audit_id}/historical-spending/?site_npi=1000000004")
    assert hs_site.status_code == 200
    assert len(hs_site.json()["by_site"]) == 1
    assert hs_site.json()["by_site"][0]["site_npi"] == "1000000004"

    # Filter by service_setting
    hs_setting = client.get(f"/api/v1/plan-audits/{audit_id}/historical-spending/?service_setting=outpatient_hospital")
    assert hs_setting.status_code == 200
    assert len(hs_setting.json()["by_setting"]) == 1

    # 11. Client/Viewer Access Control & Subsequent Rejection Gate
    # Currently approved -> Client sees audit
    client_audits_res = client_test_client.get("/api/v1/plan-audits/")
    assert client_audits_res.status_code == 200
    assert any(a["id"] == audit_id for a in client_audits_res.json()["results"])

    client_report_res = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/report/")
    assert client_report_res.status_code == 200
    assert client_test_client.post(f"/api/v1/plan-audits/{audit_id}/approve/", binding,
                                   content_type="application/json").status_code == 403
    assert client_test_client.post(f"/api/v1/plan-audits/{audit_id}/reject/", binding,
                                   content_type="application/json").status_code == 403

    missing_reason = rev_b_client.post(f"/api/v1/plan-audits/{audit_id}/reject/",
        {"comments": "  ", **binding}, content_type="application/json")
    assert missing_reason.status_code == 400
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/report/").status_code == 200

    # Reviewer B rejects A's published version; A's old approval must not reopen it.
    reject_res = rev_b_client.post(f"/api/v1/plan-audits/{audit_id}/reject/", {
        "comments": "Requires recalculation of clinical dose following physician inquiry.",
        **binding,
    }, content_type="application/json")
    assert reject_res.status_code == 200
    assert reject_res.json()["review_status"] == "rejected"
    assert reject_res.json()["publication_status"] == "rejected"
    assert reject_res.json()["published_version"] is None
    assert reject_res.json()["reviewer"] == rev_b_user.get_username()
    assert reject_res.json()["reason"] == "Requires recalculation of clinical dose following physician inquiry."
    assert reject_res.json()["reviewed_at"]
    historical_approval = rev_client.post(f"/api/v1/plan-audits/{audit_id}/approve/", {
        "comments": "Retry the old approval.", **binding,
    }, content_type="application/json")
    assert historical_approval.status_code == 409

    ordinary_comment = rev_client.post(f"/api/v1/plan-audits/{audit_id}/review/", {
        "comments": "Additional note after rejection.", **binding,
    }, content_type="application/json")
    assert ordinary_comment.status_code == 201

    # Client user can no longer view or download rejected audit
    client_audits_after = client_test_client.get("/api/v1/plan-audits/")
    pending = next(a for a in client_audits_after.json()["results"] if a["id"] == audit_id)
    assert pending["publication_status"] == "rejected"
    assert pending["can_view_results"] is False
    assert pending["summary"] == {}
    assert pending["result_fingerprint"] is None
    assert pending["latest_publication_decision"] == {
        "status": "rejected", "reviewer": rev_b_user.get_username(),
        "reviewed_at": reject_res.json()["reviewed_at"],
        "reason": None,
    }

    for suffix in (
        "overview/", "results/", "drug-analysis/", "hospital-comparison/",
        "asp-benchmark/", "historical-spending/", "savings/", "quality/",
        "network-validation/", "report/", "export-csv/", "review/",
    ):
        assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}").status_code == 404
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/").json()["summary"] == {}
    assert client_test_client.post(f"/api/v1/plan-audits/{audit_id}/generate-report/").status_code == 403

    # Approved v2 -> rerun revokes publication -> v3 approval restores access.
    rerun = client.post(f"/api/v1/plan-audits/{audit_id}/run/")
    assert rerun.status_code == 200, rerun.content
    assert rerun.json()["current_version"] == 3
    stale_rejection = rev_b_client.post(f"/api/v1/plan-audits/{audit_id}/reject/", {
        "comments": "Stale rejection for the previous run.", **binding,
    }, content_type="application/json")
    assert stale_rejection.status_code == 409
    listed = client_test_client.get("/api/v1/plan-audits/").json()
    assert next(item for item in listed["results"] if item["id"] == audit_id)["publication_status"] != "published"
    for suffix in ("overview/", "results/", "report/", "export-csv/", "savings/", "quality/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}").status_code == 404
    audit_obj.refresh_from_db()
    run_obj = current_audit_run(audit_obj)
    second_artifacts = client.post(f"/api/v1/plan-audits/{audit_id}/generate-report/")
    assert second_artifacts.status_code == 200
    second_binding = {"version": run_obj.version, "result_fingerprint": run_obj.result_fingerprint}
    stale_approval = rev_client.post(f"/api/v1/plan-audits/{audit_id}/approve/", binding,
                                     content_type="application/json")
    assert stale_approval.status_code == 409
    reapproval = rev_client.post(f"/api/v1/plan-audits/{audit_id}/approve/", second_binding,
                                 content_type="application/json")
    assert reapproval.status_code == 200, reapproval.content
    assert reapproval.json()["version"] == 3
    client_list = client_test_client.get("/api/v1/plan-audits/")
    assert client_list.status_code == 200
    client_metadata = next(item for item in client_list.json()["results"] if item["id"] == audit_id)
    assert client_metadata["summary_import_id"] is None
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/overview/").status_code == 200
    client_results = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/results/")
    assert client_results.status_code == 200
    assert all("source_references" not in row for row in client_results.json()["results"])
    client_quality = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/quality/")
    assert client_quality.status_code == 200
    assert "import_quality" not in client_quality.json()
    for suffix in ("historical-spending/", "drug-analysis/", "hospital-comparison/",
                   "asp-benchmark/", "savings/", "network-validation/"):
        response = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}")
        assert response.status_code == 200, (suffix, response.content)
        assert "source_references" not in response.content.decode("utf-8")
    assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/report/").status_code == 200
    client_csv = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/export-csv/")
    assert client_csv.status_code == 200
    assert "source_references" not in client_csv.content.decode("utf-8")
    assert "claims_summary_import_id" not in client_csv.content.decode("utf-8")

    # A failed v4 calculation must not restore v3 client publication.
    monkeypatch.setattr(plan_audit_run, "run_plan_audit", lambda *_args: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    failed_run = client.post(f"/api/v1/plan-audits/{audit_id}/run/")
    assert failed_run.status_code == 500
    failed_audit = client_test_client.get(f"/api/v1/plan-audits/{audit_id}/")
    assert failed_audit.status_code == 200
    assert failed_audit.json()["calculation_status"] == "failed"
    assert failed_audit.json()["publication_status"] == "failed"
    for suffix in ("overview/", "results/", "report/", "export-csv/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{audit_id}/{suffix}").status_code == 404

    # 12. Cross-organization isolation
    org2_res = client.post("/api/v1/organizations/", {
        "organization_name": "Isolated Other Employer", "organization_type": "employer",
    }, content_type="application/json")
    org2_id = org2_res.json()["id"]
    from pricing.models import ClaimsSummaryImport, Plan, PlanAudit, PlanOrganization
    org2 = PlanOrganization.objects.get(pk=org2_id)
    org2_plan = Plan.objects.create(organization=org2, plan_name="Other organization synthetic plan",
                                    plan_reference="OTHER-ORG-TEST")
    org2_import = ClaimsSummaryImport.objects.create(
        organization=org2, plan=org2_plan, source_file_name="synthetic.csv",
        file_hash="a" * 64, schema_version="test-v1", import_status="accepted", row_count=1,
    )
    org2_audit = PlanAudit.objects.create(
        organization=org2, plan=org2_plan, summary_import=org2_import,
        audit_name="Other organization synthetic audit", reporting_period="2026",
        created_by=get_user_model().objects.get(username="audit-test-admin"),
    )

    other_user = get_user_model().objects.create_user(username="other-org-user", password="test-password")
    other_user.groups.add(client_group, rev_group)
    client.post(f"/api/v1/organizations/{org2_id}/users/", {"user_id": other_user.pk}, content_type="application/json")

    other_client = DjangoClient()
    mfa_force_login(other_client, other_user)
    reviewer_orgs = rev_client.get("/api/v1/organizations/")
    assert reviewer_orgs.status_code == 200
    assert [item["id"] for item in reviewer_orgs.json()] == [org_id]
    assert rev_client.get(f"/api/v1/plan-audits/{org2_audit.pk}/").status_code == 404
    # Attempting to access Org 1's audit from Org 2 user returns 404
    assert other_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 404
    unassigned_client_user = get_user_model().objects.create_user(
        username="mk05-unassigned-client", password="test-password")
    unassigned_client_user.groups.add(client_group)
    unassigned_client = DjangoClient()
    mfa_force_login(unassigned_client, unassigned_client_user)
    assert unassigned_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 404
    assert not any(item["id"] == audit_id for item in
                   unassigned_client.get("/api/v1/plan-audits/").json()["results"])
    mixed_client_analyst = get_user_model().objects.create_user(
        username="mk05-mixed-unassigned-analyst", password="test-password")
    mixed_client_analyst.groups.add(client_group, analyst_group)
    assert client.post(f"/api/v1/organizations/{org2_id}/users/",
                       {"user_id": mixed_client_analyst.pk}, content_type="application/json").status_code in {200, 201}
    mixed_client_analyst_client = DjangoClient()
    mfa_force_login(mixed_client_analyst_client, mixed_client_analyst)
    assert mixed_client_analyst_client.get(f"/api/v1/plan-audits/{audit_id}/").status_code == 404
    assert not any(item["id"] == audit_id for item in
                   mixed_client_analyst_client.get("/api/v1/plan-audits/").json()["results"])

    # Independent MK-03 lifecycle with the requested exact v1 -> reject -> v2 sequence.
    monkeypatch.setattr(plan_audit_run, "run_plan_audit", validated_fixture_engine)
    lifecycle_created = client.post("/api/v1/plan-audits/create/", {
        "organization_id": org_id, "plan_id": plan_id, "summary_import_id": import_id,
        "audit_name": "MK-03 isolated publication lifecycle", "reporting_period": "2026-01-01/2026-12-31",
    }, content_type="application/json")
    assert lifecycle_created.status_code == 201, lifecycle_created.content
    lifecycle_id = lifecycle_created.json()["id"]
    lifecycle_run = client.post(f"/api/v1/plan-audits/{lifecycle_id}/run/")
    assert lifecycle_run.status_code == 200, lifecycle_run.content
    assert lifecycle_run.json()["current_version"] == 1
    lifecycle_audit = PlanAudit.objects.get(pk=lifecycle_id)
    lifecycle_version1 = current_audit_run(lifecycle_audit)
    lifecycle_binding = {"version": lifecycle_version1.version,
                         "result_fingerprint": lifecycle_version1.result_fingerprint}
    assert client.post(f"/api/v1/plan-audits/{lifecycle_id}/generate-report/").status_code == 200
    lifecycle_approval = rev_client.post(f"/api/v1/plan-audits/{lifecycle_id}/approve/", {
        "comments": "Version 1 independently approved.", **lifecycle_binding,
    }, content_type="application/json")
    assert lifecycle_approval.status_code == 200
    assert lifecycle_approval.json()["version"] == 1
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/results/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/report/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/export-csv/").status_code == 200

    unauthorized_reviewer = get_user_model().objects.create_user(
        username="mk03-unassigned-reviewer", password="test-password")
    unauthorized_reviewer.groups.add(rev_group)
    unauthorized_reviewer_client = DjangoClient()
    mfa_force_login(unauthorized_reviewer_client, unauthorized_reviewer)
    reject_reason_with_financial_data = "Do not publish; internal allowed total $123456.78."
    reject_payload = {"comments": reject_reason_with_financial_data, **lifecycle_binding}
    assert unauthorized_reviewer_client.post(
        f"/api/v1/plan-audits/{lifecycle_id}/reject/", reject_payload,
        content_type="application/json").status_code == 404
    assert unauthorized_reviewer_client.post(
        f"/api/v1/plan-audits/{lifecycle_id}/approve/", lifecycle_binding,
        content_type="application/json").status_code == 404
    assert other_client.post(f"/api/v1/plan-audits/{lifecycle_id}/reject/", reject_payload,
                             content_type="application/json").status_code == 404
    assert other_client.post(f"/api/v1/plan-audits/{lifecycle_id}/approve/", lifecycle_binding,
                             content_type="application/json").status_code == 404
    assert rev_b_client.post(f"/api/v1/plan-audits/{lifecycle_id}/reject/", {
        "comments": "   ", **lifecycle_binding,
    }, content_type="application/json").status_code == 400
    assert rev_b_client.post(f"/api/v1/plan-audits/{lifecycle_id}/reject/", {
        "comments": "Stale version identifier.", "version": 0,
        "result_fingerprint": lifecycle_binding["result_fingerprint"],
    }, content_type="application/json").status_code == 409

    lifecycle_rejection = rev_b_client.post(
        f"/api/v1/plan-audits/{lifecycle_id}/reject/", reject_payload,
        content_type="application/json")
    assert lifecycle_rejection.status_code == 200, lifecycle_rejection.content
    assert lifecycle_rejection.json()["published_version"] is None
    for suffix in ("overview/", "results/", "report/", "export-csv/", "savings/", "quality/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/{suffix}").status_code == 404
    client_lifecycle_metadata = next(
        item for item in client_test_client.get("/api/v1/plan-audits/").json()["results"]
        if item["id"] == lifecycle_id)
    assert client_lifecycle_metadata["publication_status"] == "rejected"
    assert client_lifecycle_metadata["summary"] == {}
    assert client_lifecycle_metadata["result_fingerprint"] is None
    assert client_lifecycle_metadata["latest_publication_decision"]["reviewer"] == rev_b_user.username
    assert client_lifecycle_metadata["latest_publication_decision"]["reason"] is None
    assert reject_reason_with_financial_data not in str(client_lifecycle_metadata)
    lifecycle_history = rev_client.get(f"/api/v1/plan-audits/{lifecycle_id}/review/")
    assert lifecycle_history.status_code == 200
    assert [entry["review_status"] for entry in lifecycle_history.json()] == ["rejected", "approved"]
    assert lifecycle_history.json()[0]["comments"] == reject_reason_with_financial_data
    assert rev_client.post(f"/api/v1/plan-audits/{lifecycle_id}/approve/", {
        "comments": "Cannot reuse v1 approval.", **lifecycle_binding,
    }, content_type="application/json").status_code == 409

    lifecycle_v2_response = client.post(f"/api/v1/plan-audits/{lifecycle_id}/run/")
    assert lifecycle_v2_response.status_code == 200, lifecycle_v2_response.content
    assert lifecycle_v2_response.json()["current_version"] == 2
    for suffix in ("results/", "report/", "export-csv/"):
        assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/{suffix}").status_code == 404
    lifecycle_audit.refresh_from_db()
    lifecycle_version2 = current_audit_run(lifecycle_audit)
    lifecycle_v2_binding = {"version": lifecycle_version2.version,
                             "result_fingerprint": lifecycle_version2.result_fingerprint}
    assert client.post(f"/api/v1/plan-audits/{lifecycle_id}/generate-report/").status_code == 200
    lifecycle_v2_approval = rev_client.post(f"/api/v1/plan-audits/{lifecycle_id}/approve/", {
        "comments": "Version 2 independently approved after v1 rejection.", **lifecycle_v2_binding,
    }, content_type="application/json")
    assert lifecycle_v2_approval.status_code == 200
    assert lifecycle_v2_approval.json()["version"] == 2
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/results/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/report/").status_code == 200
    assert client_test_client.get(f"/api/v1/plan-audits/{lifecycle_id}/export-csv/").status_code == 200
    revoke = client.delete(f"/api/v1/organizations/{org_id}/users/{rev_user.pk}/")
    assert revoke.status_code == 204
    assert rev_client.get("/api/v1/organizations/").json() == []
    assert rev_client.get(f"/api/v1/plan-audits/{lifecycle_id}/").status_code == 404
    assert rev_client.post(f"/api/v1/plan-audits/{lifecycle_id}/approve/", {
        "comments": "Access was revoked.", **lifecycle_v2_binding,
    }, content_type="application/json").status_code == 404


@pytest.mark.django_db
def test_mk05_actual_role_classification_matrix(client, db):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client as DjangoClient
    from pricing.plan_audit_common import is_client_only, is_admin

    User = get_user_model()
    groups = {
        name: Group.objects.get_or_create(name=name)[0]
        for name in ("CLIENT", "Viewer", "SUPER_ADMIN", "ANALYST", "REVIEWER")
    }

    def make_user(username, role_names=(), *, superuser=False, active=True):
        account = User.objects.create_user(username=username, password="test-password",
                                           is_superuser=superuser, is_staff=superuser,
                                           is_active=active)
        if role_names:
            account.groups.add(*(groups[name] for name in role_names))
        return account

    cases = [
        (make_user("mk05-su-no-groups", superuser=True), False, True),
        (make_user("mk05-su-client", ("CLIENT",), superuser=True), False, True),
        (make_user("mk05-super-admin-group", ("SUPER_ADMIN",)), False, True),
        (make_user("mk05-analyst", ("ANALYST",)), False, False),
        (make_user("mk05-reviewer", ("REVIEWER",)), False, False),
        (make_user("mk05-client", ("CLIENT",)), True, False),
        (make_user("mk05-viewer", ("Viewer",)), True, False),
        (make_user("mk05-client-reviewer", ("CLIENT", "REVIEWER")), False, False),
        (make_user("mk05-client-analyst", ("CLIENT", "ANALYST")), False, False),
        (make_user("mk05-no-role"), False, False),
        (make_user("mk05-inactive-client", ("CLIENT",), active=False), True, False),
    ]
    for account, expected_client_only, expected_admin in cases:
        assert is_client_only(account) is expected_client_only, account.username
        assert is_admin(account) is expected_admin, account.username

    superuser_no_groups = cases[0][0]
    # Superuser permission inheritance remains broad; classification helper excludes it from CLIENT-only.
    from pricing.permissions import has_any_role
    assert has_any_role(superuser_no_groups, {"CLIENT"})
    assert has_any_role(superuser_no_groups, {"REVIEWER"})
    assert not has_any_role(cases[9][0], {"CLIENT", "Viewer", "ANALYST", "REVIEWER"})

    no_role_client = DjangoClient()
    mfa_force_login(no_role_client, cases[9][0])
    assert no_role_client.get("/api/v1/plan-audits/").status_code == 403
    inactive_client = DjangoClient()
    mfa_force_login(inactive_client, cases[10][0])
    assert inactive_client.get("/api/v1/plan-audits/").status_code == 401
    for account, _, _ in cases[:9]:
        role_client = DjangoClient()
        mfa_force_login(role_client, account)
        assert role_client.get("/api/v1/plan-audits/").status_code == 200, account.username


def test_audit_result_and_savings_admin_is_read_only():
    from django.contrib import admin
    from pricing.models import PlanAudit, PlanAuditArtifact, PlanAuditResult, PlanAuditRun, SavingsOpportunity

    assert "created_by" in admin.site._registry[PlanAudit].get_readonly_fields(None)
    assert PlanAuditRun not in admin.site._registry
    assert PlanAuditArtifact not in admin.site._registry

    for model in (PlanAuditResult, SavingsOpportunity):
        model_admin = admin.site._registry[model]
        request = None
        # The permission methods are unconditional and do not depend on request data.
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request) is False
        assert model_admin.has_delete_permission(request) is False
        assert set(model_admin.get_readonly_fields(request)) == {
            field.name for field in model._meta.fields
        }


def test_evaluation_package_and_broker_evaluations_workflow(client):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client as DjangoClient

    # 1. Evaluation package endpoint
    pkg_res = client.get("/api/v1/reports/evaluation-package/")
    assert pkg_res.status_code == 200, pkg_res.json()
    pkg_data = pkg_res.json()
    assert "product_explanation" in pkg_data
    assert "what_meshkor_does" in pkg_data["product_explanation"]
    assert "privacy_and_security_boundary" in pkg_data["product_explanation"]
    assert len(pkg_data["evaluation_questions"]) == 7
    assert len(pkg_data["pilot_onboarding_checklist"]) == 15

    # Viewer role gets 403 on evaluation package
    viewer_group, _ = Group.objects.get_or_create(name="Viewer")
    viewer_user = get_user_model().objects.create_user(username="viewer-eval-test", password="test-password")
    viewer_user.groups.add(viewer_group)
    viewer_client = DjangoClient()
    mfa_force_login(viewer_client, viewer_user)

    viewer_pkg = viewer_client.get("/api/v1/reports/evaluation-package/")
    assert viewer_pkg.status_code == 403

    # 2. Broker evaluations initial milestone check
    init_res = client.get("/api/v1/reports/evaluations/")
    assert init_res.status_code == 200
    init_data = init_res.json()
    assert init_data["milestone"]["required_count"] == 3
    assert init_data["milestone"]["verified_count"] == 0
    assert init_data["milestone"]["remaining_count"] == 3
    assert init_data["milestone"]["prerequisite_met"] is False

    # 3. Viewer cannot record evaluations
    viewer_post = viewer_client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Unauthorized Attempt",
    }, content_type="application/json")
    assert viewer_post.status_code == 403

    # 4. Record a contact-only interaction (does not qualify as verified evaluation)
    contact_res = client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Apex Benefits",
        "contact_reference": "John Smith",
        "status": "contacted",
        "feedback": "",
    }, content_type="application/json")
    assert contact_res.status_code == 201
    assert contact_res.json()["is_verified"] is False

    # Milestone should still show verified_count == 0
    res_m1 = client.get("/api/v1/reports/evaluations/").json()
    assert res_m1["milestone"]["verified_count"] == 0

    # 5. Record verified evaluation for Org 1 (Apex Benefits)
    e1_res = client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Apex Benefits",
        "contact_reference": "Jane Doe, VP Health",
        "report_version": "2024-Q3 v1.0",
        "evaluation_date": "2024-11-01",
        "status": "report_evaluated",
        "feedback": "Hospital markups exceeding 3x ASP limit are relevant for our self-funded employer clients.",
        "pilot_interest": True,
        "evidence_reference": "Meeting notes 2024-11-01",
    }, content_type="application/json")
    assert e1_res.status_code == 201
    assert e1_res.json()["is_verified"] is True
    e1_id = e1_res.json()["id"]

    res_m2 = client.get("/api/v1/reports/evaluations/").json()
    assert res_m2["milestone"]["verified_count"] == 1
    assert res_m2["milestone"]["remaining_count"] == 2
    assert res_m2["milestone"]["prerequisite_met"] is False

    # 6. Duplicate org does not increment verified milestone count
    e1_dup = client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Apex Benefits ",  # Whitespace variant
        "status": "feedback_received",
        "evaluation_date": "2024-11-02",
        "feedback": "Second meeting feedback.",
    }, content_type="application/json")
    assert e1_dup.status_code == 201
    assert e1_dup.json()["is_verified"] is True

    res_m2_dup = client.get("/api/v1/reports/evaluations/").json()
    assert res_m2_dup["milestone"]["verified_count"] == 1  # Deduplicated

    # 7. Record Org 2
    e2_res = client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Buckeye TPA Services",
        "status": "feedback_received",
        "evaluation_date": "2024-11-02",
        "feedback": "Confirmed that local claims extraction boundary resolves employer privacy concerns.",
    }, content_type="application/json")
    assert e2_res.status_code == 201
    res_m3 = client.get("/api/v1/reports/evaluations/").json()
    assert res_m3["milestone"]["verified_count"] == 2
    assert res_m3["milestone"]["remaining_count"] == 1
    assert res_m3["milestone"]["prerequisite_met"] is False

    # 8. Record Org 3 -> Satisfies prerequisite
    e3_res = client.post("/api/v1/reports/evaluations/", {
        "organization_name": "Great Lakes Benefits Trust",
        "status": "pilot_interested",
        "evaluation_date": "2024-11-03",
        "feedback": "Ready to evaluate one paid pilot audit with a 1,200-member self-funded plan.",
        "pilot_interest": True,
    }, content_type="application/json")
    assert e3_res.status_code == 201
    res_m4 = client.get("/api/v1/reports/evaluations/").json()
    assert res_m4["milestone"]["verified_count"] == 3
    assert res_m4["milestone"]["remaining_count"] == 0
    assert res_m4["milestone"]["prerequisite_met"] is True

    # 9. PATCH and DELETE
    patch_res = client.patch(f"/api/v1/reports/evaluations/{e1_id}/", {
        "next_action": "Follow up on pilot NDA agreement.",
    }, content_type="application/json")
    assert patch_res.status_code == 200
    assert patch_res.json()["next_action"] == "Follow up on pilot NDA agreement."

    del_res = client.delete(f"/api/v1/reports/evaluations/{e1_id}/")
    assert del_res.status_code == 204


def test_synthea_dataset_registration_and_category(client):
    from pricing.models import ClaimsExplorerDataset, PlanOrganization

    org = PlanOrganization.objects.create(
        organization_name="Synthea Demo Org", organization_type="tpa",
    )
    # Registration via POST
    reg_res = client.post("/api/v1/claims/datasets/", {
        "organization_id": org.pk,
        "dataset_identifier": "synthea_sample_data",
    }, content_type="application/json")
    assert reg_res.status_code == 201
    assert reg_res.json()["registered"] is True
    assert reg_res.json()["category"] == "synthetic_demo"

    # Verify category persisted in DB
    record = ClaimsExplorerDataset.objects.get(organization=org, dataset_identifier="synthea_sample_data")
    assert record.category == "synthetic_demo"

    # Verify catalog lists category
    catalog = client.get("/api/v1/claims/datasets/", {"organization_id": org.pk}).json()
    synthea_entry = next(d for d in catalog["datasets"] if d["dataset_identifier"] == "synthea_sample_data")
    assert synthea_entry["category"] == "synthetic_demo"
    assert synthea_entry["synthetic"] is True


def test_synthea_summary_and_quality_endpoint(client):
    from pricing.models import ClaimsExplorerDataset, PlanOrganization
    from pricing.claims_views import _synthea_manifest_path

    org = PlanOrganization.objects.create(
        organization_name="Synthea Analytics Org", organization_type="employer",
    )
    # 403 before registration
    unreg = client.get(f"/api/v1/claims/synthea/summary/?organization_id={org.pk}")
    assert unreg.status_code == 403

    # Register
    ClaimsExplorerDataset.objects.create(
        organization=org, dataset_identifier="synthea_sample_data", category="synthetic_demo",
    )

    if not _synthea_manifest_path().is_file():
        unavailable = client.get(f"/api/v1/claims/synthea/summary/?organization_id={org.pk}")
        assert unavailable.status_code == 503
        assert "manifest is unavailable" in unavailable.json()["error"].lower()
        return

    # 200 after registration
    res = client.get(f"/api/v1/claims/synthea/summary/?organization_id={org.pk}")
    assert res.status_code == 200, res.content
    data = res.json()
    assert data["dataset_identifier"] == "synthea_sample_data"
    assert data["category"] == "synthetic_demo"
    assert data["total_tables"] == 18
    assert data["total_rows"] > 100000
    assert "summary_metrics" in data
    assert data["summary_metrics"]["total_encounters"] == 5059
    assert data["summary_metrics"]["unique_patients"] == 111
    assert "data_boundaries" in data
    assert data["data_boundaries"]["is_synthetic"] is True
    assert "hcpcs_jcodes" in data["data_boundaries"]
    assert "quality_report" in data
    assert data["quality_report"]["overall_status"] == "PASS"


def test_synthea_subtable_queries_and_privacy(client):
    from pricing.models import ClaimsExplorerDataset, PlanOrganization
    from pricing.claims_views import _synthea_manifest_path

    org = PlanOrganization.objects.create(
        organization_name="Synthea Subtables Org", organization_type="broker",
    )
    ClaimsExplorerDataset.objects.create(
        organization=org, dataset_identifier="synthea_sample_data", category="synthetic_demo",
    )

    if not _synthea_manifest_path().is_file():
        unavailable = client.get("/api/v1/claims/", {
            "organization_id": org.pk, "dataset": "synthea_sample_data",
            "subtable": "encounters", "page_size": 10,
        })
        assert unavailable.status_code == 503
        assert "unavailable" in unavailable.json()["error"].lower()
        return

    # 1. Encounters query
    enc_res = client.get("/api/v1/claims/", {
        "organization_id": org.pk,
        "dataset": "synthea_sample_data",
        "subtable": "encounters",
        "page_size": 10,
    })
    assert enc_res.status_code == 200
    enc_data = enc_res.json()
    assert enc_data["dataset"] == "synthea_sample_data"
    assert enc_data["subtable"] == "encounters"
    assert enc_data["total"] == 5059
    assert len(enc_data["rows"]) == 10
    assert "TOTAL_CLAIM_COST" in enc_data["columns"]
    sample_enc_id = enc_data["rows"][0]["Id"]

    # 2. Patients privacy check: direct identifiers must not be exposed
    pat_res = client.get("/api/v1/claims/", {
        "organization_id": org.pk,
        "dataset": "synthea_sample_data",
        "subtable": "patients",
        "page_size": 10,
    })
    assert pat_res.status_code == 200
    pat_cols = pat_res.json()["columns"]
    for forbidden in ["SSN", "DRIVERS", "PASSPORT", "FIRST", "LAST", "MAIDEN", "ADDRESS"]:
        assert forbidden not in pat_cols

    # 3. Text search
    search_res = client.get("/api/v1/claims/", {
        "organization_id": org.pk,
        "dataset": "synthea_sample_data",
        "subtable": "encounters",
        "search": "examination",
        "page_size": 10,
    })
    assert search_res.status_code == 200
    assert search_res.json()["total"] > 0

    # 4. Detail lookup for encounter
    detail_res = client.get(f"/api/v1/claims/{sample_enc_id}/", {
        "organization_id": org.pk,
        "dataset": "synthea_sample_data",
    })
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["record_type"] == "encounter"
    assert detail["encounter"]["Id"] == sample_enc_id
    assert "procedures" in detail
    assert "medications" in detail


@pytest.mark.django_db
def test_mk07_reviewer_clinical_unit_validation_access(client, tmp_path, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from django.test import Client as DjangoClient
    from pipeline.common import paths as project_paths

    User = get_user_model()
    reviewer = User.objects.create_user(username="mk07-reviewer", password="test-password")
    reviewer.groups.add(Group.objects.get_or_create(name="REVIEWER")[0])
    reviewer_client = mfa_force_login(DjangoClient(), reviewer)
    analyst = User.objects.create_user(username="mk07-analyst", password="test-password")
    analyst.groups.add(Group.objects.get_or_create(name="ANALYST")[0])
    analyst_client = mfa_force_login(DjangoClient(), analyst)
    client_user = User.objects.create_user(username="mk07-client", password="test-password")
    client_user.groups.add(Group.objects.get_or_create(name="CLIENT")[0])
    client_role_client = mfa_force_login(DjangoClient(), client_user)

    def isolated_paths():
        configured = project_paths()
        configured["raw"] = tmp_path / "review-export"
        return configured

    monkeypatch.setattr("pipeline.common.paths", isolated_paths)
    validation_path = "/api/v1/drug-unit-validations/"
    scope_path = "/api/v1/drug-selection-scope/"
    reviewer_validation = reviewer_client.get(validation_path)
    reviewer_scope = reviewer_client.get(scope_path)
    assert (reviewer_validation.status_code, reviewer_scope.status_code) == (200, 200), {
        "validations": reviewer_validation.status_code, "scope": reviewer_scope.status_code,
    }
    assert reviewer_validation.json()["status"] == "loaded"
    assert "rows" in reviewer_validation.json()
    assert all(not {"price", "asp_payment_limit", "markup_multiple"}.intersection(row)
               for row in reviewer_validation.json()["rows"])
    assert reviewer_scope.json()["status"] == "selected"
    drug = next(item for item in reviewer_scope.json()["drugs"]
                if item.get("billing_unit") and item.get("asp_dosage"))
    assert all("partb_spending" not in item and "spend_rank" not in item
               for item in reviewer_scope.json()["drugs"])
    review_url = f"/api/v1/drug-selection-scope/{drug['hcpcs']}/unit-review/"
    bad_quantity = reviewer_client.post(review_url, {
        "status": "unit_unresolved", "notes": "Synthetic test evidence is incomplete.",
        "clinical_reviewer_name": "Synthetic Test Reviewer",
        "billing_qty": "999", "billing_unit": drug["billing_unit"]["unit"],
    }, content_type="application/json")
    assert bad_quantity.status_code == 400
    missing_evidence = reviewer_client.post(review_url, {
        "status": "unit_unresolved", "notes": "short",
        "clinical_reviewer_name": "Synthetic Test Reviewer",
        "billing_qty": drug["billing_unit"]["qty"], "billing_unit": drug["billing_unit"]["unit"],
    }, content_type="application/json")
    assert missing_evidence.status_code == 400
    saved = reviewer_client.post(review_url, {
        "status": "unit_unresolved", "notes": "Synthetic test evidence; keep this unit unresolved.",
        "clinical_reviewer_name": "Synthetic Test Reviewer",
        "billing_qty": drug["billing_unit"]["qty"], "billing_unit": drug["billing_unit"]["unit"],
    }, content_type="application/json")
    assert saved.status_code == 200, saved.content
    assert saved.json()["reviewer"] == "mk07-reviewer"
    refreshed_scope = reviewer_client.get(scope_path).json()
    reviewed_drug = next(item for item in refreshed_scope["drugs"] if item["hcpcs"] == drug["hcpcs"])
    assert reviewed_drug["unit_review"]["status"] == "unit_unresolved"
    assert reviewed_drug["unit_review"]["notes"] == "Synthetic test evidence; keep this unit unresolved."
    assert reviewed_drug["unit_review"]["clinical_reviewer_name"] == "Synthetic Test Reviewer"
    assert reviewed_drug["unit_review"]["reviewer__username"] == "mk07-reviewer"
    assert reviewed_drug["unit_review"]["scope_source_sha256"] == refreshed_scope["source_sha256"]

    for role_client in (client_role_client, analyst_client):
        assert role_client.get(validation_path).status_code == 403
        assert role_client.get(scope_path).status_code == 403
    assert client_role_client.post(review_url, saved.json(), content_type="application/json").status_code == 403
    assert analyst_client.post(review_url, saved.json(), content_type="application/json").status_code == 403
    assert client.get(validation_path).status_code == 200
    admin_scope = client.get(scope_path)
    assert admin_scope.status_code == 200
    admin_review = next(item for item in admin_scope.json()["drugs"] if item["hcpcs"] == drug["hcpcs"])
    assert admin_review["unit_review"]["status"] == "unit_unresolved"
    assert reviewer_client.get("/api/v1/application-settings/").status_code == 403
    assert reviewer_client.get("/api/v1/audit-logs/").status_code == 403
    anonymous = DjangoClient()
    assert anonymous.get(validation_path).status_code == 401
    assert anonymous.get(scope_path).status_code == 401


@pytest.mark.django_db
def test_mk08_drug_analysis_uses_only_compatible_detailed_benchmarks(client):
    from decimal import Decimal
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from pricing.models import (ClaimsSummaryImport, ClaimsSummaryRecord, Plan, PlanAudit,
                                PlanAuditResult, PlanAuditRun, PlanOrganization)

    creator = get_user_model().objects.get(username="audit-test-admin")
    organization = PlanOrganization.objects.create(organization_name="MK08 Synthetic Org",
                                                   organization_type="employer")
    plan = Plan.objects.create(organization=organization, plan_name="Synthetic plan",
                              plan_reference="MK08-PLAN")
    summary_import = ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name="synthetic-summary.csv",
        file_hash="b" * 64, schema_version="test-v1", import_status="accepted")
    audit = PlanAudit.objects.create(organization=organization, plan=plan, summary_import=summary_import,
                                     audit_name="Synthetic benchmark aggregation", reporting_period="2026",
                                     created_by=creator, status="running")
    selection_hash = "d" * 64

    def create_run(version, fixtures):
        run = PlanAuditRun.objects.create(
            plan_audit=audit, version=version, calculation_status="running", publication_status="pending",
            summary_import=summary_import, initiated_by=creator, started_at=timezone.now())
        records = [ClaimsSummaryRecord(
            summary_import=summary_import, plan_reference="MK08-PLAN", hcpcs_code="J9999", site_npi=row[1],
            quarter=row[0], service_setting="outpatient", total_units=Decimal(row[2]),
            total_allowed_amount=Decimal(row[3]), total_paid_amount=Decimal(row[4]), member_count_band="11-50",
            source_period=row[0], extraction_timestamp=timezone.now(), schema_version="test-v1")
            for row in fixtures]
        ClaimsSummaryRecord.objects.bulk_create(records)
        results = []
        for source, row in zip(records, fixtures):
            quarter, _npi, units, allowed, paid, asp, allowed_multiple, paid_multiple, quality, review_status, review_hash, asp_hash = row
            refs = {"unit_review_status": review_status,
                    "unit_review_source_sha256": review_hash or None,
                    "unit_review_billing_qty": "1" if review_status == "validated" else None,
                    "unit_review_billing_unit": ("VIAL" if source.site_npi.endswith("9") else "MG")
                                                  if review_status == "validated" else None,
                    "drug_selection_source_sha256": selection_hash,
                    "asp_source_sha256": asp_hash or None,
                    "asp_source_file": f"{quarter}.csv" if asp_hash else None}
            results.append(PlanAuditResult(
                plan_audit=audit, audit_run=run, summary_record=source, hcpcs_code="J9999",
                site_npi=source.site_npi, quarter=quarter, service_setting="outpatient",
                total_units=Decimal(units), total_allowed_amount=Decimal(allowed), total_paid_amount=Decimal(paid),
                member_count_band="11-50", plan_allowed_price_per_unit=Decimal(allowed) / Decimal(units),
                plan_paid_price_per_unit=Decimal(paid) / Decimal(units),
                asp_payment_limit=Decimal(asp) if asp is not None else None,
                allowed_markup_multiple=Decimal(allowed_multiple) if allowed_multiple is not None else None,
                paid_markup_multiple=Decimal(paid_multiple) if paid_multiple is not None else None,
                data_quality_status=quality, data_quality_notes=[], source_references=refs))
        PlanAuditResult.objects.bulk_create(results)
        run.calculation_status = "completed"
        run.completed_at = timezone.now()
        run.save(update_fields=["calculation_status", "completed_at"])
        audit.current_version = version
        audit.status = "completed"
        audit.save(update_fields=["current_version", "status"])
        return run, results

    unresolved_fixture = [
        ("2026Q1", "1000000001", "10", "100", "80", "2", None, None,
         "UNIT_UNRESOLVED", "unresolved", "", "1" * 64),
    ]
    run1, immutable_results = create_run(1, unresolved_fixture)
    before = client.get(f"/api/v1/plan-audits/{audit.pk}/drug-analysis/")
    assert before.status_code == 200
    assert before.json()["results"][0]["allowed_markup_multiple"] is None, before.json()["results"][0]
    assert before.json()["results"][0]["paid_markup_multiple"] is None

    fixtures = [
        ("2026Q1", "1000000002", "10", "100", "80", "2", "5", "4", "VALID", "validated", "c" * 64, "1" * 64),
        ("2026Q1", "1000000003", "10", "300", "240", "2", "15", "12", "NETWORK_UNVERIFIED", "validated", "c" * 64, "1" * 64),
        ("2026Q1", "1000000004", "10", "100", "80", "2", None, None, "UNIT_UNRESOLVED", "unresolved", "", "1" * 64),
        ("2026Q1", "1000000010", "5", "50", "40", "2", None, None, "NETWORK_UNVERIFIED", "validated", "c" * 64, "1" * 64),
        ("2026Q2", "1000000005", "10", "150", "100", "3", "5", "3.33333333", "NETWORK_UNVERIFIED", "validated", "c" * 64, "2" * 64),
        ("2026Q3", "1000000006", "10", "100", "80", None, None, None, "REFERENCE_NOT_FOUND", "validated", "c" * 64, ""),
        ("2026Q4", "1000000007", "10", "100", "80", "0", None, None, "REFERENCE_NOT_FOUND", "validated", "c" * 64, "4" * 64),
        ("2025Q4", "1000000008", "10", "100", "80", "2", "5", "4", "VALID", "validated", "e" * 64, "5" * 64),
        ("2025Q4", "1000000009", "10", "100", "80", "2", "5", "4", "VALID", "validated", "e" * 64, "5" * 64),
    ]
    run2, _ = create_run(2, fixtures)
    response = client.get(f"/api/v1/plan-audits/{audit.pk}/drug-analysis/")
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["allowed_markup_multiple"] is None
    assert result["paid_markup_multiple"] is None
    assert result["quarters"] == ["2025Q4", "2026Q1", "2026Q2", "2026Q3", "2026Q4"]
    assert result["quarter_breakdown"]["2026Q1"]["allowed_markup_multiple"] == "10"
    assert result["quarter_breakdown"]["2026Q1"]["paid_markup_multiple"] == "8"
    assert result["quarter_breakdown"]["2026Q1"]["eligible_row_count"] == 2
    assert result["quarter_breakdown"]["2026Q1"]["excluded_row_count"] == 2
    assert result["quarter_breakdown"]["2026Q2"]["allowed_markup_multiple"] == "5"
    assert Decimal(result["quarter_breakdown"]["2026Q2"]["paid_markup_multiple"]) == (
        Decimal("100") / (Decimal("10") * Decimal("3")))
    assert result["quarter_breakdown"]["2026Q3"]["allowed_markup_multiple"] is None
    assert result["quarter_breakdown"]["2026Q4"]["allowed_markup_multiple"] is None
    assert result["quarter_breakdown"]["2025Q4"]["allowed_markup_multiple"] is None
    assert Decimal(result["visible_allowed_amount"]) == Decimal("1100")
    assert Decimal(result["eligible_allowed_amount"]) == Decimal("550")
    assert Decimal(result["excluded_allowed_amount"]) == Decimal("550")
    assert result["excluded_row_count"] == 6
    assert Decimal(result["excluded_total_units"]) == Decimal("55")
    assert Decimal(result["eligible_allowed_amount"]) + Decimal(result["excluded_allowed_amount"]) == Decimal(
        result["visible_allowed_amount"])
    assert Decimal(result["eligible_paid_amount"]) + Decimal(result["excluded_paid_amount"]) == Decimal(
        result["visible_paid_amount"])
    assert Decimal(result["eligible_total_units"]) + Decimal(result["excluded_total_units"]) == Decimal(
        result["total_units"])
    assert Decimal(result["eligible_allowed_units"]) + Decimal(result["excluded_allowed_units"]) == Decimal(
        result["total_units"])
    assert Decimal(result["eligible_paid_units"]) + Decimal(result["excluded_paid_units"]) == Decimal(
        result["total_units"])
    assert result == client.get(f"/api/v1/plan-audits/{audit.pk}/drug-analysis/").json()["results"][0]

    assert run1.pk != run2.pk
    assert immutable_results[0].allowed_markup_multiple is None
    immutable_results[0].refresh_from_db()
    assert immutable_results[0].allowed_markup_multiple is None
    audit.current_version = 1
    audit.save(update_fields=["current_version"])
    assert client.get(f"/api/v1/plan-audits/{audit.pk}/drug-analysis/").json()["results"][0][
        "allowed_markup_multiple"] is None


def test_mk09_network_status_requires_consistent_full_quarter_coverage(monkeypatch):
    from datetime import date
    from decimal import Decimal
    from itertools import permutations
    from types import SimpleNamespace
    from pricing import plan_audit_engine as engine

    def roster(start, end, status, *, npi="1000000002", name="Choice Network", location="Clinic A",
               plan_id=1):
        return SimpleNamespace(provider_npi=npi, network_name=name, service_location=location,
                               network_status=status, effective_start=date.fromisoformat(start),
                               effective_end=date.fromisoformat(end) if end else None,
                               source_hash=("a" if status == "in_network" else "b") * 64,
                               plan_id=plan_id)

    q1_in = roster("2026-01-01", None, "in_network")
    q1_out = roster("2026-01-01", "2026-03-31", "out_of_network")
    assert engine.network_status_for([q1_in], "1000000002", "2026Q1") == "IN_NETWORK"
    assert engine.network_status_for([q1_out], "1000000002", "2026Q1") == "OUT_OF_NETWORK"
    partial_out = roster("2026-02-01", "2026-02-28", "out_of_network")
    partial_in = roster("2026-02-01", "2026-02-28", "in_network")
    current = SimpleNamespace(hcpcs_code="J9999", site_npi="1000000001", quarter="2026Q1",
                              service_setting="outpatient", total_units=Decimal("10"))
    alternative = SimpleNamespace(hcpcs_code="J9999", site_npi="1000000002", quarter="2026Q1",
                                  service_setting="outpatient", total_units=Decimal("10"))
    result_by_key = {
        (row.hcpcs_code, row.site_npi, row.quarter, row.service_setting):
            (row, SimpleNamespace(plan_allowed_price_per_unit=Decimal(price),
                                  plan_paid_price_per_unit=Decimal(price)), True)
        for row, price in ((current, "100"), (alternative, "50"))
    }
    monkeypatch.setattr(engine, "SavingsOpportunity", lambda **values: values)
    audit = SimpleNamespace(summary_import=SimpleNamespace(file_hash="c" * 64))
    assert engine._build_opportunities(
        audit, object(), [current, alternative], result_by_key, [q1_in, partial_out]) == []
    assert engine._roster_source_hashes([q1_in, partial_out], "1000000002", "2026Q1") == sorted(
        [q1_in.source_hash, partial_out.source_hash])
    assert engine.network_status_for([q1_in, partial_out], "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([q1_out, partial_in], "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    for status, expected in (("in_network", "IN_NETWORK"), ("out_of_network", "OUT_OF_NETWORK")):
        overlap = [roster("2026-01-01", "2026-02-15", status),
                   roster("2026-02-01", "2026-03-31", status)]
        adjacent = [roster("2026-01-01", "2026-01-31", status),
                    roster("2026-02-01", "2026-02-28", status),
                    roster("2026-03-01", "2026-03-31", status)]
        assert engine.network_status_for(overlap, "1000000002", "2026Q1") == expected
        assert engine.network_status_for(adjacent, "1000000002", "2026Q1") == expected
    gap = [roster("2026-01-01", "2026-01-31", "in_network"),
           roster("2026-03-01", "2026-03-31", "in_network")]
    feb_only = [roster("2026-02-01", "2026-02-28", "in_network")]
    assert engine.network_status_for(gap, "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for(feb_only, "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    expired = [roster("2025-01-01", "2025-12-31", "in_network")]
    assert engine.network_status_for(expired, "1000000002", "2026Q1") == "NETWORK_DATA_EXPIRED"
    assert engine.network_status_for([q1_in], "1000000002", "2026Q1") == "IN_NETWORK"
    assert engine.network_status_for([q1_in, partial_out], "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([roster("2026-01-01", "2026-03-31", "in_network")],
                                     "1000000002", "2026Q1") == "IN_NETWORK"
    leap_q1 = [roster("2024-01-01", "2024-03-31", "in_network")]
    assert engine.network_status_for(leap_q1, "1000000002", "2024Q1") == "IN_NETWORK"
    assert engine.network_status_for([roster("2025-10-01", "2025-12-31", "out_of_network")],
                                     "1000000002", "2025Q4") == "OUT_OF_NETWORK"
    assert engine.network_status_for([roster("2026-01-01", "2026-03-31", "in_network")],
                                     "1000000002", "2026Q1") == "IN_NETWORK"
    assert engine.network_status_for([roster("2025-10-01", "2025-12-31", "out_of_network")],
                                     "1000000002", "2026Q1") == "NETWORK_DATA_EXPIRED"
    assert engine.network_status_for([roster("2025-12-31", "2026-01-01", "in_network")],
                                     "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([q1_in, partial_out, roster("2026-02-10", "2026-02-20", "out_of_network")],
                                     "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([q1_in], "1000000003", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    plan_a = [roster("2026-01-01", "2026-03-31", "in_network", plan_id=1)]
    plan_b = [roster("2026-01-01", "2026-03-31", "out_of_network", plan_id=2)]
    assert engine.network_status_for(plan_a, "1000000002", "2026Q1") == "IN_NETWORK"
    assert engine.network_status_for(plan_b, "1000000002", "2026Q1") == "OUT_OF_NETWORK"
    assert engine.network_status_for(plan_a + plan_b, "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([roster("2026-01-01", "2026-03-31", "in_network", name="A"),
                                      roster("2026-01-01", "2026-03-31", "in_network", name="B")],
                                     "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([roster("2026-01-01", "2026-03-31", "in_network", location="")],
                                     "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    assert engine.network_status_for([roster("2026-01-01", "2026-03-31", "in_network", location="Clinic A"),
                                      roster("2026-01-01", "2026-03-31", "in_network", location="Clinic B")],
                                     "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"
    for ordered in permutations([q1_in, partial_out]):
        assert engine.network_status_for(ordered, "1000000002", "2026Q1") == "NETWORK_STATUS_UNKNOWN"

    verified_opportunities = engine._build_opportunities(
        audit, object(), [current, alternative], result_by_key, [q1_in])
    assert len(verified_opportunities) == 1
    assert verified_opportunities[0]["network_status"] == "IN_NETWORK"
    assert verified_opportunities[0]["source_references"]["network_roster_file_hashes"] == [q1_in.source_hash]

