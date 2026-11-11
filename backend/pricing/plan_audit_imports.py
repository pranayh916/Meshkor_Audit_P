"""Approved aggregate import APIs. The uploaded bytes are never persisted."""
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from pipeline.common import HCPCS_RE
from .models import AuditEvent, ClaimsSummaryImport, ClaimsSummaryRecord
from .permissions import (
    ADMIN_GROUP, ANALYST_GROUP, CanAnalyze, CanView, REVIEWER_GROUP,
    SUPER_ADMIN_GROUP, has_any_role,
)
from .plan_audit_common import (
    audit_payload, get_visible_audit, get_visible_import, is_admin,
    import_payload, parse_iso_date, visible_organizations,
)


APPROVED_FIELDS = [
    "plan_reference", "hcpcs_code", "site_npi", "quarter", "service_setting",
    "total_units", "total_allowed_amount", "total_paid_amount", "member_count_band",
    "source_period", "extraction_timestamp", "schema_version",
]
MAX_SUMMARY_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ROWS = 100_000
LIST_PAGE_SIZE = 100


def _list_page(request, queryset, serializer):
    try:
        page = int(request.query_params.get("page", "1"))
        page_size = min(int(request.query_params.get("page_size", LIST_PAGE_SIZE)), 200)
        if page < 1 or page_size < 1:
            raise ValueError
    except (TypeError, ValueError):
        return Response({"error": "page and page_size must be positive whole numbers."}, status=400)
    count = queryset.count()
    start = (page - 1) * page_size
    page_count = (count + page_size - 1) // page_size
    items = ([serializer(item) for item in queryset[start:start + page_size]]
             if page <= page_count else [])
    return Response({
        "count": count, "page": page, "page_size": page_size,
        "next": page + 1 if page < page_count else None,
        "previous": page - 1 if page > 1 and page <= page_count + 1 else None,
        "results": items,
    })


def _admin_required(request):
    if not is_admin(request.user):
        return Response({"error": "This action requires the Admin role."}, status=403)
    return None


def _analyst_required(request):
    if not has_any_role(request.user, {SUPER_ADMIN_GROUP, ANALYST_GROUP}):
        return Response({"error": "This action requires the Super Admin or Analyst role."}, status=403)
    return None


def _filename(value):
    return str(value or "claims_summary.csv").replace("\\", "/").split("/")[-1][:255]


def _quarter_bounds(value):
    match = re.fullmatch(r"(20\d{2})Q([1-4])", str(value or ""))
    if not match:
        raise ValueError("quarter must use YYYYQ1 through YYYYQ4.")
    year, quarter = int(match.group(1)), int(match.group(2))
    month = 1 + (quarter - 1) * 3
    start = datetime(year, month, 1).date()
    end = datetime(year + (quarter == 4), 1 if quarter == 4 else month + 3, 1).date()
    return start, end.fromordinal(end.toordinal() - 1)


def _decimal(value, field, *, positive=False):
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a finite decimal.") from exc
    if not number.is_finite() or number < 0 or (positive and number <= 0):
        raise ValueError(f"{field} must be a non-negative finite amount.")
    normalized = number.normalize()
    exponent = normalized.as_tuple().exponent
    scale = max(-exponent, 0)
    integer_digits = max(normalized.adjusted() + 1, 0) if number else 1
    if scale > 6 or integer_digits > 18:
        raise ValueError(f"{field} supports at most 18 integer and 6 decimal digits.")
    return number


def _source_period(value):
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})", str(value or ""))
    if not match:
        raise ValueError("source_period must be start-date/end-date in ISO format.")
    start = parse_iso_date(match.group(1), "source_period start")
    end = parse_iso_date(match.group(2), "source_period end")
    if start > end:
        raise ValueError("source_period end precedes its start.")
    return start, end


def _safe_summary_rows(reader):
    try:
        yield from reader
    except csv.Error as exc:
        yield {"__csv_parse_error__": str(exc)}


def _validate_summary(content, plan, manifest):
    errors, rows, keys, periods = [], [], set(), set()
    provenance = manifest.get("source_provenance")
    if (not isinstance(provenance, dict)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", str(provenance.get("source_sha256", "")))
            or provenance.get("source_format") not in {"csv", "xlsx", "xlsm"}
            or type(provenance.get("input_records")) is not int
            or provenance["input_records"] < 1
            or provenance.get("plan_reference") != plan.plan_reference):
        return [], 0, [{"row": 0, "reason": "Manifest source provenance is missing or invalid."}], "", "unknown"
    try:
        provenance_period = _source_period(provenance.get("source_period", ""))
    except ValueError:
        return [], 0, [{"row": 0, "reason": "Manifest source period is invalid."}], "", "unknown"
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], 0, [{"row": 0, "reason": "CSV must use UTF-8 encoding."}], "", "unknown"
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        return [], 0, [{"row": 1, "reason": f"Malformed CSV syntax: {exc}"}], "", "unknown"
    if fieldnames != APPROVED_FIELDS:
        return [], 0, [{"row": 1, "reason": "CSV header does not exactly match the approved aggregate schema."}], "", "unknown"
    if (manifest.get("schema_version") != "1.0"
            or manifest.get("approved_fields") != APPROVED_FIELDS
            or manifest.get("raw_claims_included") is not False
            or manifest.get("member_identifiers_included") is not False
            or type(manifest.get("small_cell_suppression_threshold")) is not int
            or manifest.get("small_cell_suppression_threshold") != 11
            or manifest.get("complementary_suppression_applied") is not True):
        return [], 0, [{"row": 0, "reason": "Manifest schema or privacy/suppression declaration is invalid."}], "", "unknown"

    input_rows = 0
    for line, row in enumerate(_safe_summary_rows(reader), start=2):
        if "__csv_parse_error__" in row:
            errors.append({"row": line, "reason": f"Malformed CSV syntax: {row['__csv_parse_error__']}"})
            break
        input_rows += 1
        if input_rows > MAX_ROWS:
            errors.append({"row": line, "reason": "Aggregate file exceeds the 100,000 row limit."})
            break
        try:
            if None in row or any(row.get(field) is None for field in APPROVED_FIELDS):
                raise ValueError("Row has missing or extra columns.")
            if row["plan_reference"] != plan.plan_reference:
                raise ValueError("plan_reference does not match the selected plan.")
            if not HCPCS_RE.fullmatch(row["hcpcs_code"]):
                raise ValueError("hcpcs_code is not a valid five-character HCPCS code.")
            from .plan_audit_common import valid_npi
            if not valid_npi(row["site_npi"]):
                raise ValueError("site_npi is not a valid 10-digit NPI.")
            q_start, q_end = _quarter_bounds(row["quarter"])
            units = _decimal(row["total_units"], "total_units", positive=True)
            allowed = _decimal(row["total_allowed_amount"], "total_allowed_amount")
            paid = _decimal(row["total_paid_amount"], "total_paid_amount")
            if row["member_count_band"] not in {"11-50", "51-100", "100+"}:
                raise ValueError("Suppressed or unrecognized member_count_band is not accepted.")
            if not row["service_setting"].strip() or len(row["service_setting"]) > 80:
                raise ValueError("service_setting is required and limited to 80 characters.")
            source_start, source_end = _source_period(row["source_period"])
            if q_end < source_start or q_start > source_end:
                raise ValueError("quarter does not overlap source_period.")
            if plan.effective_start and q_end < plan.effective_start:
                raise ValueError("quarter does not overlap the plan effective dates.")
            if plan.effective_end and q_start > plan.effective_end:
                raise ValueError("quarter does not overlap the plan effective dates.")
            timestamp = datetime.fromisoformat(row["extraction_timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("extraction_timestamp must include a timezone.")
            if row["schema_version"] != "1.0":
                raise ValueError("Only aggregate schema version 1.0 is accepted.")
            key = (row["hcpcs_code"], row["site_npi"], row["quarter"], row["service_setting"])
            if key in keys:
                raise ValueError("Duplicate aggregate grouping key.")
            keys.add(key)
            periods.add(row["source_period"])
            rows.append({
                "plan_reference": row["plan_reference"], "hcpcs_code": row["hcpcs_code"],
                "site_npi": row["site_npi"], "quarter": row["quarter"],
                "service_setting": row["service_setting"].strip(),
                "total_units": units, "total_allowed_amount": allowed,
                "total_paid_amount": paid, "member_count_band": row["member_count_band"],
                "source_period": row["source_period"], "extraction_timestamp": timestamp,
                "schema_version": "1.0",
            })
        except (ValueError, TypeError, InvalidOperation) as exc:
            errors.append({"row": line, "reason": str(exc)})
    if input_rows == 0:
        errors.append({"row": 0, "reason": "Aggregate summary has no data rows."})
    if len(periods) > 1:
        errors.append({"row": 0, "reason": "All aggregate rows must share one source_period."})
    if periods and _source_period(next(iter(periods))) != provenance_period:
        errors.append({"row": 0, "reason": "Manifest source period does not match the aggregate CSV."})
    try:
        manifest_rows = manifest.get("aggregate_rows")
        if type(manifest_rows) is not int or manifest_rows != input_rows:
            raise ValueError
    except (TypeError, ValueError):
        errors.append({"row": 0, "reason": "Manifest aggregate row count does not match the CSV."})
    return rows, input_rows, errors, next(iter(periods), ""), "1.0"


def _store_rejected(organization, plan, filename, digest, version, input_rows, valid_rows,
                    errors, source_period, imported_by):
    summary = {
        "input_rows": input_rows, "valid_rows": valid_rows, "stored_rows": 0,
        "rejected_rows": max(len(errors), input_rows - valid_rows),
        "errors": errors[:500], "errors_truncated": len(errors) > 500,
        "raw_claims_stored": False, "member_identifiers_stored": False,
    }
    return ClaimsSummaryImport.objects.create(
        organization=organization, plan=plan, source_file_name=filename, file_hash=digest,
        schema_version=version or "unknown", imported_by=imported_by, import_status="rejected",
        row_count=0, validation_summary=summary, source_period=source_period,
    )


@api_view(["POST"])
@permission_classes([CanAnalyze])
@parser_classes([MultiPartParser, FormParser])
def import_plan_summary(request):
    denied = _analyst_required(request)
    if denied:
        return denied
    upload, manifest_upload = request.FILES.get("file"), request.FILES.get("manifest")
    if not upload or not upload.name.casefold().endswith(".csv"):
        return Response({"error": "Select the extractor's approved claims_summary.csv file."}, status=400)
    if not manifest_upload or not manifest_upload.name.casefold().endswith(".json"):
        return Response({"error": "Select the matching extractor manifest.json file."}, status=400)
    if upload.size > MAX_SUMMARY_BYTES or manifest_upload.size > MAX_MANIFEST_BYTES:
        return Response({"error": "Summary CSV or manifest exceeds its upload limit."}, status=413)
    from .models import Plan, PlanOrganization
    try:
        organization = visible_organizations(request.user).get(
            pk=int(request.data.get("organization_id")))
        plan = Plan.objects.select_related("organization").get(
            pk=int(request.data.get("plan_id")), status="active")
    except (TypeError, ValueError, PlanOrganization.DoesNotExist, Plan.DoesNotExist):
        return Response({"error": "Select an active organization and plan."}, status=400)
    if plan.organization_id != organization.pk:
        return Response({"error": "The selected plan does not belong to this organization."}, status=400)

    content, manifest_content = upload.read(), manifest_upload.read()
    digest = hashlib.sha256(content).hexdigest()
    try:
        manifest = json.loads(manifest_content.decode("utf-8-sig"))
        if not isinstance(manifest, dict):
            raise ValueError
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return Response({"error": "Manifest must be a JSON object encoded as UTF-8."}, status=400)
    if (manifest.get("sha256") != digest or manifest.get("file") != _filename(upload.name)
            or manifest.get("raw_claims_included") is not False
            or manifest.get("member_identifiers_included") is not False
            or type(manifest.get("small_cell_suppression_threshold")) is not int
            or manifest.get("small_cell_suppression_threshold") != 11
            or manifest.get("complementary_suppression_applied") is not True):
        return Response({"error": "Manifest integrity or privacy/suppression checks failed."}, status=400)
    filename = _filename(upload.name)
    if ClaimsSummaryImport.objects.filter(plan=plan, file_hash=digest, import_status="accepted").exists():
        return Response({"error": "This summary file has already been imported for the selected plan."}, status=409)
    rows, input_rows, errors, source_period, version = _validate_summary(content, plan, manifest)
    if errors:
        try:
            with transaction.atomic():
                record = _store_rejected(organization, plan, filename, digest, version,
                                         input_rows, len(rows), errors, source_period, request.user)
        except IntegrityError:
            return Response({"error": "This summary file has already been imported."}, status=409)
        AuditEvent.objects.create(actor=request.user, action="plan_summary_import_rejected",
                                  entity_type="claims_summary_import", entity_id=str(record.pk),
                                  details={"error_count": len(errors), "sha256": digest})
        return Response({"error": "The aggregate summary failed validation; no aggregate rows were stored.",
                         "import_id": record.pk, "import_status": "rejected",
                         "validation_summary": record.validation_summary}, status=400)

    summary = {
        "input_rows": input_rows, "valid_rows": input_rows, "stored_rows": input_rows,
        "rejected_rows": 0, "errors": [], "raw_claims_stored": False,
        "member_identifiers_stored": False, "manifest_sha256_verified": True,
        "source_provenance": {
            "source_sha256": manifest["source_provenance"]["source_sha256"].lower(),
            "source_format": manifest["source_provenance"]["source_format"],
            "input_records": manifest["source_provenance"]["input_records"],
            "plan_reference": plan.plan_reference,
            "source_period": manifest["source_provenance"]["source_period"],
        },
    }
    try:
        with transaction.atomic():
            record = ClaimsSummaryImport.objects.create(
                organization=organization, plan=plan, source_file_name=filename,
                file_hash=digest, schema_version=version, imported_by=request.user,
                import_status="accepted", row_count=len(rows),
                validation_summary=summary, source_period=source_period,
            )
            ClaimsSummaryRecord.objects.bulk_create([
                ClaimsSummaryRecord(summary_import=record, **row) for row in rows
            ], batch_size=1000)
    except IntegrityError:
        return Response({"error": "Import conflicts with an existing file hash or aggregate key."}, status=409)
    AuditEvent.objects.create(actor=request.user, action="plan_summary_imported",
                              entity_type="claims_summary_import", entity_id=str(record.pk),
                              details={"row_count": len(rows), "sha256": digest})
    return Response(import_payload(record), status=201)


@api_view(["GET"])
@permission_classes([CanAnalyze])
def plan_summary_imports(request):
    queryset = ClaimsSummaryImport.objects.select_related("organization", "plan").filter(
        organization__in=visible_organizations(request.user))
    if not is_admin(request.user):
        queryset = queryset.filter(plan__status="active", plan__organization__status="active")
    if request.query_params.get("plan_id"):
        queryset = queryset.filter(plan_id=request.query_params["plan_id"])
    queryset = queryset.order_by("-imported_at", "-pk")
    return _list_page(request, queryset, import_payload)


@api_view(["GET"])
@permission_classes([CanAnalyze])
def plan_summary_import_detail(request, import_id):
    return Response(import_payload(get_visible_import(request.user, import_id)))


@api_view(["GET"])
@permission_classes([CanAnalyze])
def plan_summary_import_quality(request, import_id):
    item = get_visible_import(request.user, import_id)
    return Response({"import_id": item.pk, "file_hash": item.file_hash,
                     "import_status": item.import_status,
                     "validation_summary": item.validation_summary})


@api_view(["GET"])
@permission_classes([CanView])
def plan_audits(request):
    from .models import PlanAudit
    from .plan_audit_common import audit_payload
    queryset = PlanAudit.objects.select_related(
        "organization", "plan", "summary_import", "created_by"
    ).filter(organization__in=visible_organizations(request.user))
    if not is_admin(request.user):
        queryset = queryset.filter(plan__status="active", plan__organization__status="active")
    if request.query_params.get("plan_id"):
        queryset = queryset.filter(plan_id=request.query_params["plan_id"])
    queryset = queryset.order_by("-created_at", "-pk")
    return _list_page(request, queryset, lambda item: audit_payload(item, request.user))


@api_view(["POST"])
@permission_classes([CanAnalyze])
def create_plan_audit(request):
    if not has_any_role(request.user, {SUPER_ADMIN_GROUP, ANALYST_GROUP}):
        return Response({"error": "This action requires the Super Admin or Analyst role."}, status=403)
    from .models import Plan, PlanAudit, PlanOrganization
    try:
        organization = visible_organizations(request.user).get(
            pk=int(request.data.get("organization_id")))
        plan = Plan.objects.get(pk=int(request.data.get("plan_id")), organization=organization, status="active")
        summary = ClaimsSummaryImport.objects.get(
            pk=int(request.data.get("summary_import_id")), organization=organization,
            plan=plan, import_status="accepted")
    except (TypeError, ValueError, PlanOrganization.DoesNotExist, Plan.DoesNotExist,
            ClaimsSummaryImport.DoesNotExist):
        return Response({"error": "Select a matching active organization, plan, and accepted import."}, status=400)
    name = str(request.data.get("audit_name", "")).strip()
    period = str(request.data.get("reporting_period", summary.source_period)).strip()
    if not name or len(name) > 200 or not period or len(period) > 64:
        return Response({"error": "audit_name and reporting_period are required."}, status=400)
    item = PlanAudit.objects.create(
        organization=organization, plan=plan, summary_import=summary,
        audit_name=name, reporting_period=period, created_by=request.user)
    AuditEvent.objects.create(actor=request.user, action="plan_audit_created",
                              entity_type="plan_audit", entity_id=str(item.pk))
    return Response(audit_payload(item, request.user), status=201)


@api_view(["GET"])
@permission_classes([CanView])
def plan_audit_detail(request, audit_id):
    from .plan_audit_common import get_accessible_audit, is_client_only
    from django.http import Http404
    audit = get_accessible_audit(request.user, audit_id)
    if is_client_only(request.user) and (
            audit.organization.status != "active" or audit.plan.status != "active"):
        raise Http404
    return Response(audit_payload(audit, request.user))
