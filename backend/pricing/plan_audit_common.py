"""Shared authorization and serialization helpers for plan-specific audits."""
from datetime import date
import hashlib
import json
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404

from .models import (
    AuditReview, ClaimsSummaryImport, DrugUnitReview, Plan, PlanAudit,
    PlanAuditResult, PlanAuditRun, PlanOrganization, SavingsOpportunity,
)
from .permissions import (
    ADMIN_GROUP, ANALYST_GROUP, CLIENT_GROUP, REVIEWER_GROUP,
    SUPER_ADMIN_GROUP, VIEWER_GROUP, has_any_role,
)


def is_admin(user):
    return has_any_role(user, {ADMIN_GROUP})


def visible_organizations(user):
    queryset = PlanOrganization.objects.filter(status="active")
    if is_admin(user):
        return queryset
    return queryset.filter(user_access__user=user).distinct()


def get_visible_organization(user, organization_id):
    return get_object_or_404(visible_organizations(user), pk=organization_id)


def get_visible_plan(user, plan_id):
    plans = Plan.objects.select_related("organization").filter(status="active")
    if not is_admin(user):
        plans = plans.filter(organization__status="active")
        plans = plans.filter(organization__user_access__user=user).distinct()
    return get_object_or_404(plans, pk=plan_id)


def get_visible_import(user, import_id):
    imports = ClaimsSummaryImport.objects.select_related("organization", "plan")
    if not is_admin(user):
        imports = imports.filter(organization__status="active", plan__status="active",
                                 plan__organization__status="active",
                                 organization__user_access__user=user).distinct()
    return get_object_or_404(imports, pk=import_id)


def get_visible_audit(user, audit_id):
    audit = get_accessible_audit(user, audit_id)
    if is_client_only(user) and (
            audit.organization.status != "active"
            or audit.plan.status != "active"
            or not published_run(audit)):
        from django.http import Http404
        raise Http404
    return audit


def get_accessible_audit(user, audit_id):
    audits = PlanAudit.objects.select_related(
        "organization", "plan", "summary_import"
    )
    if not is_admin(user):
        audits = audits.filter(organization__status="active", plan__status="active",
                               plan__organization__status="active",
                               organization__user_access__user=user).distinct()
    return get_object_or_404(audits, pk=audit_id)


def is_client_only(user):
    return (has_any_role(user, {CLIENT_GROUP, VIEWER_GROUP})
            and not has_any_role(user, {SUPER_ADMIN_GROUP, ADMIN_GROUP, ANALYST_GROUP, REVIEWER_GROUP}))


def current_audit_run(audit):
    if not audit.current_version:
        return None
    return PlanAuditRun.objects.filter(
        plan_audit_id=audit.pk, version=audit.current_version,
    ).first()


def run_results(run):
    return PlanAuditResult.objects.filter(audit_run=run) if run else PlanAuditResult.objects.none()


def run_opportunities(run):
    return SavingsOpportunity.objects.filter(audit_run=run) if run else SavingsOpportunity.objects.none()


def clinical_evidence_valid(run, hcpcs_codes=None, *, lock=False):
    """Fail closed unless each requested code still has its exact clinical unit approval."""
    if not run:
        return False
    rows = list(run_results(run).values_list("hcpcs_code", "data_quality_status", "source_references"))
    if not rows:
        return False
    requested_codes = set(hcpcs_codes) if hcpcs_codes is not None else None
    selected_codes = requested_codes if requested_codes is not None else {code for code, _, _ in rows}
    evidence = {}
    for code, quality, references in rows:
        if code not in selected_codes:
            continue
        if quality != "VALID" or (references or {}).get("unit_review_status") != "validated":
            return False
        expected = (
            references.get("unit_review_source_sha256"),
            references.get("drug_selection_source_sha256"),
            references.get("unit_review_billing_qty"),
            references.get("unit_review_billing_unit"),
        )
        if any(value in (None, "") for value in expected):
            return False
        if code in evidence and evidence[code] != expected:
            return False
        evidence[code] = expected
    if not evidence or (requested_codes is not None and requested_codes - set(evidence)):
        return False
    try:
        from . import data
        info = data.run_info()
        current_scope_hash = info.get("drug_selection_source_sha256")
        scope = data.drug_config()
        if not current_scope_hash:
            return False
        query = DrugUnitReview.objects.filter(
            hcpcs__in=evidence, scope_source_sha256=current_scope_hash,
        ).order_by("hcpcs", "pk")
        reviews = list(query.select_for_update() if lock else query)
        reviews_by_code = {review.hcpcs: review for review in reviews}
        for code, (review_hash, scope_hash, expected_qty, expected_unit) in evidence.items():
            item = scope.get(code) or {}
            unit = item.get("billing_unit") or {}
            review = reviews_by_code.get(code)
            if (scope_hash != current_scope_hash
                    or item.get("selection_source_sha256") != scope_hash
                    or not review or review.status != "validated" or not review.reviewer_id):
                return False
            try:
                if (review.scope_source_sha256 != review_hash
                        or Decimal(str(review.billing_qty)) != Decimal(str(expected_qty))
                        or Decimal(str(unit.get("qty"))) != Decimal(str(expected_qty))
                        or str(review.billing_unit).upper() != str(expected_unit).upper()
                        or str(unit.get("unit", "")).upper() != str(expected_unit).upper()):
                    return False
            except (InvalidOperation, TypeError, ValueError):
                return False
        return True
    except (data.DataMissing, OSError, ValueError, KeyError, TypeError):
        return False


def run_result_fingerprint(run):
    result_rows = list(run_results(run).order_by("pk").values())
    savings_rows = list(run_opportunities(run).order_by("pk").values())
    payload = json.dumps(
        {"results": result_rows, "savings": savings_rows},
        sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def published_run(audit):
    if not audit.published_version or audit.published_version != audit.current_version:
        return None
    run = PlanAuditRun.objects.filter(
        plan_audit_id=audit.pk, version=audit.published_version,
        calculation_status="completed", publication_status="published",
        review_status="approved", approved_by__isnull=False, approved_at__isnull=False,
        published_at__isnull=False,
    ).first()
    if (not run or not run.result_fingerprint or not run.report_fingerprint
            or run_result_fingerprint(run) != run.result_fingerprint
            or not clinical_evidence_valid(run)):
        return None
    artifacts = {item.artifact_type: item for item in run.artifacts.all()}
    if set(artifacts) != {"pdf", "csv"}:
        return None
    if any(hashlib.sha256(bytes(item.content)).hexdigest() != item.sha256
           for item in artifacts.values()):
        return None
    expected_report_fingerprint = hashlib.sha256(json.dumps(
        {kind: artifacts[kind].sha256 for kind in sorted(artifacts)},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if expected_report_fingerprint != run.report_fingerprint:
        return None
    return run


def organization_payload(item):
    return {
        "id": item.pk, "organization_name": item.organization_name,
        "organization_type": item.organization_type, "status": item.status,
        "created_at": item.created_at,
    }


def plan_payload(item):
    return {
        "id": item.pk, "organization_id": item.organization_id,
        "organization_name": item.organization.organization_name,
        "plan_name": item.plan_name, "payer_reference": item.payer_reference,
        "plan_reference": item.plan_reference, "effective_start": item.effective_start,
        "effective_end": item.effective_end, "status": item.status,
        "created_at": item.created_at,
    }


def import_payload(item):
    return {
        "id": item.pk, "organization_id": item.organization_id,
        "organization_name": item.organization.organization_name, "plan_id": item.plan_id,
        "plan_name": item.plan.plan_name, "source_file_name": item.source_file_name,
        "file_hash": item.file_hash, "schema_version": item.schema_version,
        "imported_at": item.imported_at, "import_status": item.import_status,
        "row_count": item.row_count, "source_period": item.source_period,
        "validation_summary": item.validation_summary,
    }


def audit_payload(item, user=None):
    client = is_client_only(user) if user else False
    run = current_audit_run(item)
    published = published_run(item)
    can_view = bool(published) if client else bool(
        run and run.calculation_status == "completed" and run_results(run).exists())
    artifact_rows = list(run.artifacts.select_related("created_by")) if run else []
    artifacts = {artifact.artifact_type for artifact in artifact_rows}
    latest_decision = (AuditReview.objects.filter(
        audit_run=run, review_status__in=("approved", "rejected"),
    ).select_related("reviewer").first() if run else None)
    can_download = bool(published) if client else bool(run and "pdf" in artifacts)
    can_download_csv = bool(published) if client else bool(run and "csv" in artifacts)
    payload = {
        "id": item.pk, "organization_id": item.organization_id,
        "organization_name": item.organization.organization_name, "plan_id": item.plan_id,
        "plan_name": item.plan.plan_name,
        "summary_import_id": item.summary_import_id if not client else None,
        "audit_name": item.audit_name, "reporting_period": item.reporting_period,
        "status": item.status, "created_by": item.created_by.get_username() if item.created_by_id else None,
        "created_by_id": item.created_by_id if not client else None,
        "run_initiated_by": (run.initiated_by.get_username()
                              if run and run.initiated_by_id and not client else None),
        "run_initiated_by_id": run.initiated_by_id if run and not client else None,
        "artifact_builders": ([{
            "id": artifact.created_by_id,
            "username": artifact.created_by.get_username() if artifact.created_by_id else None,
        } for artifact in artifact_rows] if not client else []),
        "created_at": item.created_at, "completed_at": item.completed_at,
        "report_generated_at": item.report_generated_at if not client else None,
        "summary": item.summary if not client else {},
        "calculation_status": run.calculation_status if run else item.status,
        "publication_status": ("published" if published else
                                run.publication_status if run else "unpublished"),
        "latest_publication_decision": ({
            "status": latest_decision.review_status,
            "reviewer": latest_decision.reviewer.get_username() if latest_decision.reviewer_id else None,
            "reviewed_at": latest_decision.reviewed_at,
            "reason": None if client else latest_decision.comments,
        } if latest_decision else None),
        "current_version": item.current_version,
        "published_version": item.published_version if published else None,
        "result_fingerprint": run.result_fingerprint if run and not client else None,
        "can_view_results": can_view,
        "can_download_report": can_download,
        "can_download_csv": can_download_csv,
    }
    return payload


def parse_iso_date(value, label, *, optional=False):
    if value in (None, "") and optional:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date.") from exc
    return parsed


def valid_npi(value):
    import re
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{10}", raw):
        return False
    digits = [int(digit) for digit in "80840" + raw]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
