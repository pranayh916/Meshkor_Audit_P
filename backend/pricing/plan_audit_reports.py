"""Savings, quality, review, and report endpoints."""
import csv
import hashlib
import io
import json
from collections import Counter

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from pipeline.common import csv_safe_cell
from .models import (AuditEvent, AuditReview, PlanAudit, PlanAuditArtifact,
                     PlanAuditRun, PlanAuditResult, SavingsOpportunity)
from .permissions import CanAnalyze, CanView, CanReview, has_any_role, SUPER_ADMIN_GROUP, REVIEWER_GROUP
from .plan_audit_common import (current_audit_run, get_visible_audit, is_admin,
    is_client_only, published_run, run_opportunities, run_results,
    run_result_fingerprint)
from .plan_audit_run import _calculation_fingerprint, _decimal_text, _visible_totals


def _admin_required(request):
    if not is_admin(request.user):
        return Response({"error": "This action requires the Admin role."}, status=403)
    return None


def _savings_payload(item, *, include_source_references=True):
    payload = {
        "id": item.pk, "hcpcs_code": item.hcpcs_code, "quarter": item.quarter,
        "service_setting": item.service_setting, "current_site_npi": item.current_site_npi,
        "alternative_site_npi": item.alternative_site_npi,
        "current_allowed_price_per_unit": _decimal_text(item.current_allowed_price_per_unit),
        "alternative_allowed_price_per_unit": _decimal_text(item.alternative_allowed_price_per_unit),
        "units": _decimal_text(item.units),
        "potential_allowed_savings": _decimal_text(item.potential_allowed_savings),
        "potential_paid_difference": _decimal_text(item.potential_paid_difference),
        "network_status": item.network_status,
        "clinical_review_status": item.clinical_review_status,
        "validation_status": item.validation_status,
        "label": "Potential allowed-amount savings; clinical review pending.",
    }
    if include_source_references:
        payload["source_references"] = item.source_references
    return payload


def _paged_response(request, queryset, serialize, *, default_limit=200, max_limit=500):
    try:
        limit = min(max(int(request.query_params.get("limit", default_limit)), 1), max_limit)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return Response({"error": "limit and offset must be whole numbers."}, status=400)
    total = queryset.count()
    page_rows = list(queryset[offset:offset + limit])
    next_offset = offset + len(page_rows) if offset + len(page_rows) < total else None
    return Response({"count": total, "limit": limit, "offset": offset,
                     "next_offset": next_offset,
                     "previous_offset": max(0, offset - limit) if offset else None,
                     "results": [serialize(row) for row in page_rows]})


@api_view(["GET"])
@permission_classes([CanView])
def audit_savings(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    rows = run_opportunities(current_audit_run(audit))
    if is_client_only(request.user):
        rows = rows.filter(validation_status="validated", clinical_review_status__in=("approved", "validated"))
    return _paged_response(
        request, rows.order_by("pk"),
        lambda row: _savings_payload(row, include_source_references=not is_client_only(request.user)),
    )


@api_view(["GET"])
@permission_classes([CanView])
def audit_network_validation(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    rows = run_results(current_audit_run(audit)).order_by("site_npi", "quarter", "hcpcs_code")
    def serialize(row):
        payload = {
        "site_npi": row.site_npi, "quarter": row.quarter,
        "data_network_status": row.network_status,
        "hcpcs_code": row.hcpcs_code, "service_setting": row.service_setting,
        }
        if not is_client_only(request.user):
            payload["source_references"] = row.source_references
        return payload
    return _paged_response(request, rows, serialize)


@api_view(["GET"])
@permission_classes([CanView])
def audit_quality(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    results = run_results(current_audit_run(audit))
    statuses = Counter(results.values_list("data_quality_status", flat=True))
    result_count = results.count()
    asp_count = results.filter(asp_payment_limit__isnull=False).count()
    hospital_count = results.filter(hospital_price_per_unit__isnull=False).count()
    response = {
        "audit_id": audit.pk, "status": audit.status,
        "result_status_counts": dict(statuses),
        "benchmark_availability": {
            "result_rows": result_count,
            "asp_available": asp_count,
            "asp_unavailable": result_count - asp_count,
            "hospital_reference_available": hospital_count,
            "hospital_reference_unavailable": result_count - hospital_count,
        },
        "notes": [
            "Only approved, unsuppressed aggregate rows are included.",
            "Hospital price references require a verified site mapping and an unambiguous matching quarter and setting.",
            "Network status is unknown unless the plan roster covers the entire claim quarter.",
            "Potential savings remain pending clinical review; no savings are treated as guaranteed.",
            "Summary metrics include only visible approved aggregate rows.",
        ] + (["Potential savings are unavailable because no evidence-backed lower-priced full-quarter in-network alternative was identified."]
             if not run_opportunities(current_audit_run(audit)).exists() else []),
    }
    if not is_client_only(request.user):
        response["import_quality"] = audit.summary_import.validation_summary
    return Response(response)


@api_view(["POST"])
@permission_classes([CanAnalyze])
def generate_plan_report(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    run = current_audit_run(audit)
    results = run_results(run)
    if (not run or run.calculation_status != "completed" or not results.exists()
            or run_result_fingerprint(run) != run.result_fingerprint
            or run.summary_import_id != audit.summary_import_id
            or run.source_sha256 != audit.summary_import.file_hash
            or run.calculation_fingerprint != _calculation_fingerprint()):
        return Response({"error": "Run the audit before generating a report."}, status=409)
    if run.artifacts.exists():
        return Response({"error": "Immutable report artifacts already exist for this run."}, status=409)
    pdf_bytes = _build_pdf(audit, run)
    csv_bytes = _build_csv(run)
    pdf_hash, csv_hash = hashlib.sha256(pdf_bytes).hexdigest(), hashlib.sha256(csv_bytes).hexdigest()
    with transaction.atomic():
        locked = PlanAuditRun.objects.select_for_update().get(pk=run.pk)
        current = PlanAudit.objects.select_for_update().get(pk=audit.pk)
        if current.current_version != locked.version or locked.calculation_status != "completed":
            return Response({"error": "The audit version changed; regenerate for the current run."}, status=409)
        PlanAuditArtifact.objects.create(audit_run=locked, artifact_type="pdf", content=pdf_bytes,
                                         sha256=pdf_hash, created_by=request.user)
        PlanAuditArtifact.objects.create(audit_run=locked, artifact_type="csv", content=csv_bytes,
                                         sha256=csv_hash, created_by=request.user)
        locked.report_fingerprint = hashlib.sha256(json.dumps(
            {"csv": csv_hash, "pdf": pdf_hash}, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        locked.save(update_fields=["report_fingerprint"])
        current.report_generated_at = timezone.now()
        current.save(update_fields=["report_generated_at"])
        AuditEvent.objects.create(actor=request.user, action="plan_audit_report_generated",
                                  entity_type="plan_audit", entity_id=str(current.pk),
                                  details={"version": locked.version, "result_fingerprint": locked.result_fingerprint,
                                           "report_fingerprint": locked.report_fingerprint})
    return Response({"audit_id": audit.pk, "version": run.version,
                     "result_fingerprint": run.result_fingerprint,
                     "report_fingerprint": locked.report_fingerprint,
                     "report_generated_at": current.report_generated_at,
                     "report_url": f"/api/v1/plan-audits/{audit.pk}/report/",
                     "csv_url": f"/api/v1/plan-audits/{audit.pk}/export-csv/"})


def _build_pdf(audit, run):
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)
    y = height - 42

    def draw(value, *, size=8, bold=False):
        nonlocal y
        text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(value if value is not None else ""))
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(36, y, text[:180]); y -= size + 6
        if y < 40:
            pdf.showPage(); y = height - 42

    draw("MeshKor Healthcare | Plan-Specific Infusion Drug Audit", size=15, bold=True)
    draw(f"Organization: {audit.organization.organization_name} | Plan: {audit.plan.plan_name}", size=10)
    draw(f"Audit: {audit.audit_name} | Version: {run.version} | Result SHA-256: {run.result_fingerprint}")
    metrics = _visible_totals(audit, run, include_unvalidated_savings=False)
    draw(f"Visible units: {metrics['units_analyzed']} | Allowed: {metrics['visible_allowed_amount']} | Paid: {metrics['visible_paid_amount']}")
    draw("Potential savings are shown only when validated and clinically approved.")
    draw("HCPCS | NPI | Quarter | Allowed/unit | Paid/unit | Hospital/unit | ASP | Quality", bold=True)
    total_rows = run_results(run).count()
    draw(f"Summary detail: first 5,000 of {total_rows:,} result rows; complete detail is in the companion CSV.")
    for row in run_results(run).order_by("pk")[:5000]:
        draw(f"{row.hcpcs_code} | {row.site_npi} | {row.quarter} | {_decimal_text(row.plan_allowed_price_per_unit)} | "
             f"{_decimal_text(row.plan_paid_price_per_unit)} | {_decimal_text(row.hospital_price_per_unit)} | "
             f"{_decimal_text(row.asp_payment_limit)} | {row.data_quality_status}")
    draw("Hospital reference prices are not this plan's contracted rates. Clinical suitability must be verified.")
    pdf.save()
    return buffer.getvalue()


def _build_csv(run, *, include_source_references=True):
    output = io.StringIO(newline="")
    fields = ["audit_version", "result_fingerprint", "hcpcs_code", "site_npi", "quarter", "service_setting",
        "total_units", "total_allowed_amount", "total_paid_amount", "member_count_band",
        "plan_allowed_price_per_unit", "plan_paid_price_per_unit", "hospital_price_per_unit",
        "asp_payment_limit", "hospital_markup_multiple", "allowed_markup_multiple", "paid_markup_multiple",
        "plan_to_hospital_price_multiple", "network_status", "data_quality_status", "data_quality_notes"]
    if include_source_references:
        fields.append("source_references")
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for row in run_results(run):
        data = {"audit_version": run.version, "result_fingerprint": run.result_fingerprint,
            "hcpcs_code": row.hcpcs_code, "site_npi": row.site_npi, "quarter": row.quarter,
            "service_setting": row.service_setting, "total_units": _decimal_text(row.total_units),
            "total_allowed_amount": _decimal_text(row.total_allowed_amount), "total_paid_amount": _decimal_text(row.total_paid_amount),
            "member_count_band": row.member_count_band, "plan_allowed_price_per_unit": _decimal_text(row.plan_allowed_price_per_unit),
            "plan_paid_price_per_unit": _decimal_text(row.plan_paid_price_per_unit), "hospital_price_per_unit": _decimal_text(row.hospital_price_per_unit),
            "asp_payment_limit": _decimal_text(row.asp_payment_limit), "hospital_markup_multiple": _decimal_text(row.hospital_markup_multiple),
            "allowed_markup_multiple": _decimal_text(row.allowed_markup_multiple), "paid_markup_multiple": _decimal_text(row.paid_markup_multiple),
            "plan_to_hospital_price_multiple": _decimal_text(row.plan_to_hospital_price_multiple), "network_status": row.network_status,
            "data_quality_status": row.data_quality_status, "data_quality_notes": "; ".join(row.data_quality_notes)}
        if include_source_references:
            data["source_references"] = json.dumps(
                row.source_references, sort_keys=True, separators=(",", ":"))
        writer.writerow({key: csv_safe_cell(value) for key, value in data.items()})
    return ("\ufeff" + output.getvalue()).encode("utf-8")


@api_view(["GET"])
@permission_classes([CanView])
def plan_report(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    run = published_run(audit) if is_client_only(request.user) else current_audit_run(audit)
    artifact = run.artifacts.filter(artifact_type="pdf").first() if run else None
    if not artifact or hashlib.sha256(bytes(artifact.content)).hexdigest() != artifact.sha256:
        return Response({"error": "A verified report artifact is not available for this audit version."}, status=404)
    response = HttpResponse(bytes(artifact.content), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="plan-audit-{audit.pk}-v{run.version}.pdf"'
    return response


@api_view(["GET"])
@permission_classes([CanView])
def export_plan_csv(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    run = published_run(audit) if is_client_only(request.user) else current_audit_run(audit)
    artifact = run.artifacts.filter(artifact_type="csv").first() if run else None
    if not artifact or hashlib.sha256(bytes(artifact.content)).hexdigest() != artifact.sha256:
        return Response({"error": "A verified CSV artifact is not available for this audit version."}, status=404)
    content = (_build_csv(run, include_source_references=False)
               if is_client_only(request.user) else bytes(artifact.content))
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="plan-audit-{audit.pk}-v{run.version}-results.csv"'
    return response


@api_view(["GET", "POST"])
@permission_classes([CanView])
def audit_review(request, audit_id):
    if request.method == "GET" and is_client_only(request.user):
        from django.http import Http404
        raise Http404
    if request.method == "POST" and not has_any_role(request.user, {SUPER_ADMIN_GROUP, REVIEWER_GROUP}):
        return Response({"error": "Only a Reviewer or Super Admin can submit a formal review."}, status=403)
    audit = get_visible_audit(request.user, audit_id)
    run = published_run(audit) if is_client_only(request.user) else current_audit_run(audit)
    if request.method == "GET":
        return Response([{
            "id": item.pk, "reviewer": item.reviewer.get_username() if item.reviewer_id else None,
            "review_status": item.review_status, "comments": item.comments,
            "reviewed_at": item.reviewed_at,
        } for item in audit.reviews.filter(audit_run=run).select_related("reviewer")])
    if not run or run.calculation_status != "completed":
        return Response({"error": "Run the audit before submitting a review."}, status=409)
    if request.data.get("version") != run.version or request.data.get("result_fingerprint") != run.result_fingerprint:
        return Response({"error": "Review must identify the current audit version and result fingerprint."}, status=409)
    comments = str(request.data.get("comments", "")).strip()
    if len(comments) > 2000:
        return Response({"error": "Review comments are limited to 2,000 characters."}, status=400)
    review = AuditReview.objects.create(
        plan_audit=audit, audit_run=run, reviewer=request.user,
        review_status="submitted", comments=comments,
    )
    AuditEvent.objects.create(actor=request.user, action="plan_audit_review_submitted",
                              entity_type="plan_audit", entity_id=str(audit.pk))
    return Response({"id": review.pk, "version": run.version,
                     "result_fingerprint": run.result_fingerprint, "review_status": review.review_status,
                     "reviewed_at": review.reviewed_at}, status=201)


def _set_review(request, audit_id, status):
    if not has_any_role(request.user, {SUPER_ADMIN_GROUP, REVIEWER_GROUP}):
        return Response({"error": "Only a Reviewer or Super Admin can approve or reject an audit."}, status=403)
    audit = get_visible_audit(request.user, audit_id)
    if is_client_only(request.user):
        return Response({"error": "Client accounts cannot approve audit results."}, status=403)
    if audit.status not in {"completed", "needs_review"}:
        return Response({"error": "Run the audit before reviewing it."}, status=409)
    comments = str(request.data.get("comments", "")).strip()
    if status == "rejected" and not comments:
        return Response({"error": "Provide a review reason when rejecting an audit."}, status=400)
    if len(comments) > 2000:
        return Response({"error": "Review comments are limited to 2,000 characters."}, status=400)
    with transaction.atomic():
        audit = PlanAudit.objects.select_for_update().select_related("summary_import").get(pk=audit.pk)
        run = PlanAuditRun.objects.select_for_update().filter(
            plan_audit_id=audit.pk, version=audit.current_version,
        ).first()
        if (not run or run.calculation_status != "completed"
                or request.data.get("version") != run.version
                or request.data.get("result_fingerprint") != run.result_fingerprint
                or run_result_fingerprint(run) != run.result_fingerprint
                or run.summary_import_id != audit.summary_import_id
                or run.source_sha256 != audit.summary_import.file_hash
                or run.calculation_fingerprint != _calculation_fingerprint()):
            return Response({"error": "The audit version or its source/results changed; review the current version."}, status=409)
        if status == "approved" and run.publication_status != "pending":
            return Response({"error": "This run is no longer pending approval. Start a new version for republication."}, status=409)
        if status == "rejected" and run.publication_status not in {"pending", "published"}:
            return Response({"error": "This run has already received a final publication decision."}, status=409)
        artifacts = {obj.artifact_type: obj for obj in run.artifacts.all()}
        if status == "approved":
            if not audit.created_by_id or not run.initiated_by_id:
                return Response({
                    "error": "Approval is unavailable because this audit's creator or run initiator identity is missing."
                }, status=409)
            if set(artifacts) != {"pdf", "csv"} or any(
                hashlib.sha256(bytes(obj.content)).hexdigest() != obj.sha256 for obj in artifacts.values()
            ):
                return Response({"error": "Generate and verify both report artifacts before approval."}, status=409)
            if any(artifact.created_by_id is None for artifact in artifacts.values()):
                return Response({
                    "error": "Approval is unavailable because a report artifact builder identity is missing."
                }, status=409)
            contributor_ids = {
                audit.created_by_id,
                run.initiated_by_id,
                *(artifact.created_by_id for artifact in artifacts.values()),
            }
            if request.user.pk in contributor_ids:
                return Response({
                    "error": "You cannot approve an audit that you created, ran, or built. An independent reviewer must approve this version."
                }, status=403)
            if any(row.data_quality_status != "VALID" for row in run_results(run)):
                return Response({"error": "Resolve blocking data quality issues before publication."}, status=409)
            expected = hashlib.sha256(json.dumps(
                {key: artifacts[key].sha256 for key in sorted(artifacts)},
                sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            if expected != run.report_fingerprint:
                return Response({"error": "Report artifacts do not match this run."}, status=409)
        review = AuditReview.objects.create(plan_audit=audit, audit_run=run, reviewer=request.user,
                                            review_status=status, comments=comments)
        run.review_status = status
        run.publication_status = "published" if status == "approved" else "rejected"
        run.approved_by = request.user if status == "approved" else None
        run.approved_at = timezone.now() if status == "approved" else None
        run.published_at = timezone.now() if status == "approved" else None
        if status == "rejected":
            run.revoked_at = timezone.now()
            run.revocation_reason = comments
        run.save(update_fields=["review_status", "publication_status", "approved_by", "approved_at",
                                "published_at", "revoked_at", "revocation_reason"])
        audit.published_version = run.version if status == "approved" else None
        audit.status = "completed" if status == "approved" else "needs_review"
        audit.save(update_fields=["published_version", "status"])
        AuditEvent.objects.create(actor=request.user, action=f"plan_audit_{status}",
            entity_type="plan_audit", entity_id=str(audit.pk),
            details={"version": run.version, "result_fingerprint": run.result_fingerprint,
                     "reason": comments})
    return Response({"id": review.pk, "audit_id": audit.pk, "version": run.version,
        "result_fingerprint": run.result_fingerprint, "review_status": status,
        "publication_status": run.publication_status,
        "published_version": audit.published_version,
        "reviewer": request.user.get_username(), "reason": comments,
        "audit_status": audit.status, "reviewed_at": review.reviewed_at})


@api_view(["POST"])
@permission_classes([CanReview])
def approve_plan_audit(request, audit_id):
    return _set_review(request, audit_id, "approved")


@api_view(["POST"])
@permission_classes([CanReview])
def reject_plan_audit(request, audit_id):
    return _set_review(request, audit_id, "rejected")
