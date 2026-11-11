"""Organization, plan, Viewer access, and plan network-roster APIs."""
import csv
import hashlib
import heapq
import io
from bisect import bisect_right
from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .models import AuditEvent, NetworkRosterEntry, Plan, PlanOrganization, PlanOrganizationAccess
from .permissions import (CanView, CanAnalyze, CLIENT_GROUP, VIEWER_GROUP,
                          ANALYST_GROUP, REVIEWER_GROUP, SUPER_ADMIN_GROUP, has_any_role)
from .plan_audit_common import (
    get_visible_organization, get_visible_plan, is_admin, organization_payload,
    parse_iso_date, plan_payload, valid_npi, visible_organizations,
)


def _admin_required(request):
    if not is_admin(request.user):
        return Response({"error": "This action requires the Admin role."}, status=403)
    return None


def _filename(value):
    return str(value or "network_roster.csv").replace("\\", "/").split("/")[-1][:255]


def _safe_roster_rows(reader):
    try:
        yield from reader
    except csv.Error:
        yield {"__csv_parse_error__": True}


@api_view(["GET", "POST"])
@permission_classes([CanView])
def organizations(request):
    if request.method == "GET":
        queryset = PlanOrganization.objects.all() if is_admin(request.user) else visible_organizations(request.user)
        return Response([organization_payload(item) for item in queryset])
    denied = _admin_required(request)
    if denied:
        return denied
    name = str(request.data.get("organization_name", "")).strip()
    kind = str(request.data.get("organization_type", "")).strip().casefold()
    if not name or len(name) > 200 or kind not in {"employer", "tpa"}:
        return Response({"error": "Provide organization_name and organization_type employer or tpa."}, status=400)
    try:
        item = PlanOrganization.objects.create(organization_name=name, organization_type=kind)
    except IntegrityError:
        return Response({"error": "An organization with this name already exists."}, status=409)
    AuditEvent.objects.create(actor=request.user, action="plan_organization_created",
                              entity_type="plan_organization", entity_id=str(item.pk))
    return Response(organization_payload(item), status=201)


@api_view(["PATCH"])
@permission_classes([CanView])
def organization_status(request, organization_id):
    denied = _admin_required(request)
    if denied:
        return denied
    if set(request.data.keys()) != {"status"}:
        return Response({"error": "Only status may be updated."}, status=400)
    allowed_statuses = {value for value, _label in PlanOrganization.STATUS_CHOICES}
    new_status = request.data.get("status")
    if not isinstance(new_status, str) or new_status not in allowed_statuses:
        return Response({"error": "status is invalid."}, status=400)
    with transaction.atomic():
        organization = get_object_or_404(PlanOrganization.objects.select_for_update(), pk=organization_id)
        previous_status = organization.status
        if previous_status != new_status:
            organization.status = new_status
            organization.save(update_fields=["status"])
            changed_at = timezone.now()
            AuditEvent.objects.create(
                actor=request.user, action="plan_organization_status_changed",
                entity_type="plan_organization", entity_id=str(organization.pk),
                details={"previous_status": previous_status, "new_status": new_status,
                         "timestamp": changed_at.isoformat()},
            )
    return Response(organization_payload(organization))


@api_view(["GET", "POST"])
@permission_classes([CanView])
def organization_access(request, organization_id):
    denied = _admin_required(request)
    if denied:
        return denied
    organization = get_visible_organization(request.user, organization_id)
    if request.method == "GET":
        rows = PlanOrganizationAccess.objects.filter(organization=organization).select_related(
            "user").order_by("user__username")
        return Response([{"user_id": row.user_id, "username": row.user.get_username(),
                          "display_name": row.user.get_full_name() or row.user.get_username(),
                          "created_at": row.created_at} for row in rows])
    try:
        user = get_user_model().objects.get(pk=int(request.data.get("user_id")),
                                            is_active=True, is_superuser=False)
    except (TypeError, ValueError, get_user_model().DoesNotExist):
        return Response({"error": "A valid active user_id is required."}, status=400)
    if not user.groups.filter(name__in=(CLIENT_GROUP, VIEWER_GROUP, ANALYST_GROUP, REVIEWER_GROUP)).exists():
        return Response({"error": "Organization access can be granted only to an active Analyst, Reviewer, Client, or legacy Viewer account."}, status=400)
    access, created = PlanOrganizationAccess.objects.get_or_create(
        organization=organization, user=user, defaults={"granted_by": request.user})
    AuditEvent.objects.create(actor=request.user, action="plan_organization_viewer_access_granted",
                              entity_type="plan_organization", entity_id=str(organization.pk),
                              details={"user_id": user.pk})
    return Response({"organization_id": organization.pk, "user_id": user.pk,
                     "username": user.get_username(), "created": created},
                    status=201 if created else 200)


@api_view(["DELETE"])
@permission_classes([CanView])
def organization_access_detail(request, organization_id, user_id):
    denied = _admin_required(request)
    if denied:
        return denied
    organization = get_visible_organization(request.user, organization_id)
    deleted, _ = PlanOrganizationAccess.objects.filter(
        organization=organization, user_id=user_id).delete()
    if not deleted:
        return Response({"error": "Viewer access was not found."}, status=404)
    AuditEvent.objects.create(actor=request.user, action="plan_organization_viewer_access_revoked",
                              entity_type="plan_organization", entity_id=str(organization.pk),
                              details={"user_id": user_id})
    return Response(status=204)


@api_view(["GET", "POST"])
@permission_classes([CanView])
def plans(request):
    if request.method == "GET":
        if is_admin(request.user):
            queryset = Plan.objects.select_related("organization").all()
        else:
            queryset = Plan.objects.select_related("organization").filter(
                organization__in=visible_organizations(request.user), status="active",
                organization__status="active")
        organization_id = request.query_params.get("organization_id")
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return Response([plan_payload(item) for item in queryset])
    denied = _admin_required(request)
    if denied:
        return denied
    try:
        organization = PlanOrganization.objects.get(pk=int(request.data.get("organization_id")), status="active")
        start = parse_iso_date(request.data.get("effective_start"), "effective_start", optional=True)
        end = parse_iso_date(request.data.get("effective_end"), "effective_end", optional=True)
    except (PlanOrganization.DoesNotExist, TypeError, ValueError):
        return Response({"error": "Select an active organization and valid effective dates."}, status=400)
    if start and end and end < start:
        return Response({"error": "effective_end must not precede effective_start."}, status=400)
    name = str(request.data.get("plan_name", "")).strip()
    reference = str(request.data.get("plan_reference", "")).strip()
    if not name or not reference or len(name) > 200 or len(reference) > 120:
        return Response({"error": "plan_name and plan_reference are required."}, status=400)
    item = Plan(organization=organization, plan_name=name,
                payer_reference=str(request.data.get("payer_reference", "")).strip()[:120],
                plan_reference=reference, effective_start=start, effective_end=end)
    try:
        item.save()
    except IntegrityError:
        return Response({"error": "plan_reference must be unique within its organization."}, status=409)
    AuditEvent.objects.create(actor=request.user, action="plan_created",
                              entity_type="plan", entity_id=str(item.pk))
    return Response(plan_payload(item), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([CanView])
def plan_detail(request, plan_id):
    if request.method == "PATCH" and is_admin(request.user):
        item = get_object_or_404(Plan.objects.select_related("organization"), pk=plan_id)
    else:
        item = get_visible_plan(request.user, plan_id)
    if request.method == "GET":
        return Response(plan_payload(item))
    denied = _admin_required(request)
    if denied:
        return denied
    allowed = {"plan_name", "payer_reference", "effective_start", "effective_end", "status"}
    if set(request.data.keys()) - allowed:
        return Response({"error": "Only plan name, payer reference, effective dates, and status may be updated."}, status=400)
    if "plan_name" in request.data:
        name = str(request.data["plan_name"]).strip()
        if not name or len(name) > 200:
            return Response({"error": "plan_name is invalid."}, status=400)
        item.plan_name = name
    if "payer_reference" in request.data:
        item.payer_reference = str(request.data["payer_reference"]).strip()[:120]
    for field in ("effective_start", "effective_end"):
        if field in request.data:
            try:
                setattr(item, field, parse_iso_date(request.data[field], field, optional=True))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=400)
    if item.effective_start and item.effective_end and item.effective_end < item.effective_start:
        return Response({"error": "effective_end must not precede effective_start."}, status=400)
    if "status" in request.data:
        allowed_statuses = {value for value, _label in Plan.STATUS_CHOICES}
        if not isinstance(request.data["status"], str) or request.data["status"] not in allowed_statuses:
            return Response({"error": "status must be active or inactive."}, status=400)
        item.status = request.data["status"]
    with transaction.atomic():
        organization = PlanOrganization.objects.select_for_update().get(pk=item.organization_id)
        previous_status = Plan.objects.select_for_update().values_list("status", flat=True).get(pk=item.pk)
        if organization.status != "active" and item.status == "active":
            return Response({"error": "An inactive organization must be activated before its plan."}, status=400)
        item.save()
        if previous_status != item.status:
            changed_at = timezone.now()
            AuditEvent.objects.create(actor=request.user, action="plan_status_changed",
                                      entity_type="plan", entity_id=str(item.pk),
                                      details={"previous_status": previous_status,
                                               "new_status": item.status,
                                               "timestamp": changed_at.isoformat()})
        else:
            AuditEvent.objects.create(actor=request.user, action="plan_updated",
                                      entity_type="plan", entity_id=str(item.pk))
    return Response(plan_payload(item))


@api_view(["GET", "POST"])
@permission_classes([CanView])
@parser_classes([MultiPartParser, FormParser])
def plan_network_roster(request, plan_id):
    plan = get_visible_plan(request.user, plan_id)
    if request.method == "GET":
        counts = list(plan.network_roster.values("network_status").annotate(count=Count("id")))
        response = {"plan_id": plan.pk, "entry_count": plan.network_roster.count(),
                    "status_counts": counts, "quarter_coverage": None}
        summary_import_id = request.query_params.get("summary_import_id")
        if summary_import_id:
            from .plan_audit_common import get_visible_import
            try:
                summary_import = get_visible_import(request.user, summary_import_id)
            except (Http404, TypeError, ValueError):
                return Response({"error": "The requested summary import is unavailable."}, status=404)
            if summary_import.plan_id != plan.pk or summary_import.import_status != "accepted":
                return Response({"error": "Select an accepted summary import for this plan."}, status=400)
            from .plan_audit_engine import network_status_for
            roster = list(plan.network_roster.all())
            statuses = {}
            distinct_records = list(summary_import.records.values("site_npi", "quarter").distinct())
            for record in distinct_records:
                status = network_status_for(roster, record["site_npi"], record["quarter"])
                statuses[status] = statuses.get(status, 0) + 1
            response["quarter_coverage"] = {
                "summary_import_id": summary_import.pk,
                "site_quarters": sum(statuses.values()),
                "status_counts": statuses,
            }
        return Response(response)
    if not has_any_role(request.user, {SUPER_ADMIN_GROUP, ANALYST_GROUP}):
        return Response({"error": "This action requires the Super Admin or Analyst role."}, status=403)
    upload = request.FILES.get("file")
    if not upload or not upload.name.casefold().endswith(".csv") or upload.size > 32 * 1024 * 1024:
        return Response({"error": "Upload a network roster CSV no larger than 32 MB."}, status=400)
    raw = upload.read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    except (UnicodeDecodeError, csv.Error):
        return Response({"error": "Network roster must be a valid UTF-8 CSV."}, status=400)
    fields = ["provider_npi", "provider_name", "network_name", "network_status",
              "effective_start", "effective_end", "service_location", "applicable_plan_reference"]
    if reader.fieldnames != fields:
        return Response({"error": "Network roster columns do not match the documented schema."}, status=400)
    rows, errors, unique = [], [], set()
    for line, row in enumerate(_safe_roster_rows(reader), start=2):
        if row.get("__csv_parse_error__"):
            errors.append({"row": line, "reason": "Network roster CSV syntax is invalid."})
            break
        if line > 100_001:
            errors.append({"row": line, "reason": "Network roster exceeds the 100,000 row limit."})
            break
        try:
            if None in row or any(row.get(field) is None for field in fields):
                raise ValueError("Row has missing or extra columns.")
            if row.get("applicable_plan_reference") != plan.plan_reference:
                raise ValueError("applicable_plan_reference does not match this plan.")
            npi = (row.get("provider_npi") or "").strip()
            if not valid_npi(npi):
                raise ValueError("provider_npi is invalid.")
            status = (row.get("network_status") or "").strip().casefold()
            if status not in {"in_network", "out_of_network"}:
                raise ValueError("network_status must be IN_NETWORK or OUT_OF_NETWORK.")
            name = (row.get("network_name") or "").strip()
            if not name or len(name) > 160:
                raise ValueError("network_name is required and limited to 160 characters.")
            start = parse_iso_date(row.get("effective_start"), "effective_start")
            end = parse_iso_date(row.get("effective_end"), "effective_end", optional=True)
            if end and end < start:
                raise ValueError("effective_end precedes effective_start.")
            location = (row.get("service_location") or "").strip()
            provider_name = (row.get("provider_name") or "").strip()
            if len(location) > 240 or len(provider_name) > 200:
                raise ValueError("provider_name or service_location exceeds its maximum length.")
            key = (npi, name, start, location)
            if key in unique:
                raise ValueError("Duplicate provider-network-period row.")
            unique.add(key)
            rows.append(NetworkRosterEntry(
                plan=plan, provider_npi=npi,
                provider_name=provider_name,
                network_name=name, network_status=status, effective_start=start,
                effective_end=end, service_location=location,
                source_file_name=_filename(upload.name), source_hash=digest))
        except (ValueError, TypeError) as exc:
            errors.append({"row": line, "reason": str(exc)})
            if len(errors) >= 500:
                break
    if not rows and not errors:
        errors.append({"row": 0, "reason": "Network roster has no data rows."})
    if errors:
        return Response({"error": "Network roster was rejected; no rows were stored.",
                         "rejected_rows": len(errors), "errors": errors}, status=400)
    conflicts = _conflicting_roster_rows(rows)
    if conflicts:
        return Response({"error": "Network roster contains conflicting effective intervals; no rows were stored.",
                         "rejected_rows": len(conflicts),
                         "errors": [{"row": line, "reason": "Conflicting network statuses overlap for this provider."}
                                    for line in conflicts]}, status=400)
    try:
        with transaction.atomic():
            Plan.objects.select_for_update().get(pk=plan.pk)
            existing = list(plan.network_roster.all())
            conflicts = _conflicting_roster_entries(rows, existing)
            if conflicts:
                return Response({
                    "error": "Network roster conflicts with existing effective intervals; no rows were stored.",
                    "rejected_rows": len(conflicts),
                    "errors": [{"row": line, "reason": "Conflicting network statuses overlap an existing provider interval."}
                               for line in conflicts],
                }, status=400)
            NetworkRosterEntry.objects.bulk_create(rows, batch_size=1000)
    except IntegrityError:
        return Response({"error": "Roster entries already exist. No entries were stored."}, status=409)
    AuditEvent.objects.create(actor=request.user, action="plan_network_roster_imported",
                              entity_type="plan", entity_id=str(plan.pk),
                              details={"row_count": len(rows), "sha256": digest})
    return Response({"plan_id": plan.pk, "accepted_rows": len(rows), "sha256": digest,
                     "raw_roster_file_stored": False}, status=201)


def _intervals_overlap(first_start, first_end, second_start, second_end):
    return (first_end is None or second_start <= first_end) and (
        second_end is None or first_start <= second_end
    )


def _conflicting_roster_rows(rows):
    conflicts = set()
    grouped = {}
    for index, item in enumerate(rows):
        grouped.setdefault(item.provider_npi, []).append((index, item))
    infinity = date.max
    for intervals in grouped.values():
        intervals.sort(key=lambda pair: (pair[1].effective_start, pair[0]))
        active = {"in_network": {}, "out_of_network": {}}
        unreported = {"in_network": set(), "out_of_network": set()}
        expirations = []
        for index, item in intervals:
            while expirations and expirations[0][0] < item.effective_start:
                _end, status, expired_index = heapq.heappop(expirations)
                active[status].pop(expired_index, None)
                unreported[status].discard(expired_index)
            opposite = "out_of_network" if item.network_status == "in_network" else "in_network"
            if active[opposite]:
                conflicts.add(index + 2)
                conflicts.update(other_index + 2 for other_index in unreported[opposite])
                unreported[opposite].clear()
            end = item.effective_end or infinity
            active[item.network_status][index] = end
            if not active[opposite]:
                unreported[item.network_status].add(index)
            heapq.heappush(expirations, (end, item.network_status, index))
    return sorted(conflicts)


def _conflicting_roster_entries(rows, existing):
    conflicts = set()
    grouped = {}
    infinity = date.max
    for other in existing:
        grouped.setdefault((other.provider_npi, other.network_status), []).append(
            (other.effective_start, other.effective_end or infinity))
    indexes = {}
    for key, intervals in grouped.items():
        intervals.sort(key=lambda item: item[0])
        starts, max_ends, latest_end = [], [], date.min
        for start, end in intervals:
            starts.append(start)
            latest_end = max(latest_end, end)
            max_ends.append(latest_end)
        indexes[key] = (starts, max_ends)
    for index, item in enumerate(rows, start=2):
        for status in {"in_network", "out_of_network"} - {item.network_status}:
            starts, max_ends = indexes.get((item.provider_npi, status), ([], []))
            end = item.effective_end or infinity
            position = bisect_right(starts, end) - 1
            if position >= 0 and max_ends[position] >= item.effective_start:
                conflicts.add(index)
                break
    return sorted(conflicts)
