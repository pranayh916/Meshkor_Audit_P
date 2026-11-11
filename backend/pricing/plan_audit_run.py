"""Run and inspect plan-specific audit comparisons."""
import logging
import hashlib
import json
import errno
import os
import threading
import uuid
from collections import defaultdict
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import AuditEvent, PlanAudit, PlanAuditResult, PlanAuditRun, SavingsOpportunity
from .permissions import CanAnalyze, CanView
from .plan_audit_common import (
    audit_payload, current_audit_run, get_visible_audit, run_opportunities,
    is_client_only, run_results, run_result_fingerprint,
)
from .plan_audit_engine import run_plan_audit

# Allow-listed sort fields for historical spending queries
_ALLOWED_SORT_FIELDS = frozenset([
    "quarter", "hcpcs_code", "site_npi", "service_setting",
    "total_allowed_amount", "total_paid_amount", "total_units",
])
# Allow-listed filter fields
_ALLOWED_FILTER_FIELDS = frozenset([
    "hcpcs_code", "quarter", "site_npi", "service_setting", "data_quality_status",
])

_LOCAL_AUDIT_LOCKS = {}
_LOCAL_AUDIT_LOCKS_GUARD = threading.Lock()


class RunOwnershipLost(Exception):
    """The execution token no longer owns the audit's current run."""


@contextmanager
def _audit_execution_lock(audit_id):
    """Acquire a process-lifetime lock for one audit execution.

    PostgreSQL advisory locks coordinate all app hosts using the same cluster.
    SQLite file locks coordinate processes sharing the same local filesystem;
    SQLite deployments across hosts or filesystems without reliable OS locking
    must use a single application host for audit execution.
    """
    if connection.vendor == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(
            f"plan-audit-run:{audit_id}".encode("ascii")).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
            acquired = cursor.fetchone()[0]
        try:
            yield acquired
        finally:
            if acquired and connection.is_usable():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
        return

    if connection.vendor == "sqlite":
        database_name = str(connection.settings_dict["NAME"])
        if database_name == ":memory:" or "mode=memory" in database_name:
            lock_key = (os.getpid(), audit_id)
            with _LOCAL_AUDIT_LOCKS_GUARD:
                lock = _LOCAL_AUDIT_LOCKS.setdefault(lock_key, threading.Lock())
            acquired = lock.acquire(blocking=False)
            try:
                yield acquired
            finally:
                if acquired:
                    lock.release()
            return

        database_path = Path(database_name).resolve()
        lock_path = database_path.with_name(f"{database_path.name}.audit-run-{audit_id}.lock")
        with lock_path.open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt
                lock_file.seek(0, os.SEEK_END)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EDEADLOCK, errno.EAGAIN}:
                        raise
                    yield False
                    return
                try:
                    yield True
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    yield False
                    return
                try:
                    yield True
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return

    raise RuntimeError("Plan audit execution locking is supported only on SQLite and PostgreSQL.")


def _fail_owned_run(audit, run, worker_id, actor):
    if not run:
        PlanAudit.objects.filter(pk=audit.pk, run_owner_token=worker_id).update(run_owner_token="")
        return False
    now = timezone.now()
    with transaction.atomic():
        changed = PlanAuditRun.objects.filter(
            pk=run.pk, calculation_status="running", worker_id=worker_id,
            plan_audit__run_owner_token=worker_id,
        ).update(calculation_status="failed", publication_status="failed", completed_at=now)
        if not changed:
            return False
        audit_changed = PlanAudit.objects.filter(
            pk=audit.pk, current_version=run.version, run_owner_token=worker_id,
        ).update(status="failed", summary={
            "error": "Audit execution failed; this result version was not completed.",
        }, run_owner_token="")
        if not audit_changed:
            # Ownership changed in the same transaction; do not leave a partially failed run.
            raise RunOwnershipLost()
        AuditEvent.objects.create(
            actor=actor, action="plan_audit_run_failed", entity_type="plan_audit",
            entity_id=str(audit.pk), details={"version": run.version},
        )
    return True


logger = logging.getLogger(__name__)


def _decimal_text(value):
    return None if value is None else format(Decimal(value), "f")


def result_payload(item):
    return {
        "id": item.pk, "hcpcs_code": item.hcpcs_code, "drug_description": item.drug_description,
        "site_npi": item.site_npi,
        "quarter": item.quarter, "service_setting": item.service_setting,
        "total_units": _decimal_text(item.total_units),
        "total_allowed_amount": _decimal_text(item.total_allowed_amount),
        "total_paid_amount": _decimal_text(item.total_paid_amount),
        "member_count_band": item.member_count_band,
        "plan_allowed_price_per_unit": _decimal_text(item.plan_allowed_price_per_unit),
        "plan_paid_price_per_unit": _decimal_text(item.plan_paid_price_per_unit),
        "hospital_price_per_unit": _decimal_text(item.hospital_price_per_unit),
        "asp_payment_limit": _decimal_text(item.asp_payment_limit),
        "hospital_markup_multiple": _decimal_text(item.hospital_markup_multiple),
        "allowed_markup_multiple": _decimal_text(item.allowed_markup_multiple),
        "paid_markup_multiple": _decimal_text(item.paid_markup_multiple),
        "plan_to_hospital_price_multiple": _decimal_text(item.plan_to_hospital_price_multiple),
        "network_status": item.network_status,
        "data_quality_status": item.data_quality_status,
        "data_quality_notes": item.data_quality_notes,
        "source_references": item.source_references,
    }


def _visible_totals(audit, run=None, *, include_unvalidated_savings=True):
    run = run or current_audit_run(audit)
    results = list(run_results(run))
    allowed = sum((row.total_allowed_amount for row in results), Decimal(0))
    paid = sum((row.total_paid_amount for row in results), Decimal(0))
    units = sum((row.total_units for row in results), Decimal(0))
    opportunities_query = run_opportunities(run)
    if not include_unvalidated_savings:
        opportunities_query = opportunities_query.filter(
            validation_status="validated", clinical_review_status__in=("approved", "validated"),
        )
    opportunities = list(opportunities_query)
    savings = sum((row.potential_allowed_savings for row in opportunities), Decimal(0))
    return {
        "drugs_analyzed": len({row.hcpcs_code for row in results}),
        "hospitals_compared": len({row.site_npi for row in results if row.hospital_price_per_unit is not None}),
        "sites_with_claims": len({row.site_npi for row in results}),
        "units_analyzed": _decimal_text(units),
        "visible_allowed_amount": _decimal_text(allowed),
        "visible_paid_amount": _decimal_text(paid),
        "potential_allowed_savings": _decimal_text(savings) if opportunities else None,
        "data_quality_warnings": sum(row.data_quality_status != "VALID" for row in results),
        "totals_scope": "visible_approved_aggregate_rows_only",
    }


def _calculation_fingerprint():
    project = settings.BASE_DIR.parent
    paths = (
        Path(__file__).with_name("plan_audit_engine.py"),
        Path(__file__).with_name("plan_audit_run.py"),
        project / "config" / "hospital_sites.csv",
        project / "config" / "drugs_in_scope.yaml",
        project / "config" / "pipeline.yaml",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _run_reference_fingerprints(run):
    collected = defaultdict(set)
    for references in run_results(run).values_list("source_references", flat=True).iterator():
        for key, value in references.items():
            if value not in (None, "", []):
                if isinstance(value, list):
                    collected[key].update(str(item) for item in value)
                else:
                    collected[key].add(str(value))
    fingerprints = {}
    for key, values in sorted(collected.items()):
        ordered = sorted(values)
        canonical = json.dumps(ordered, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        fingerprints[key] = {"values": ordered, "sha256": hashlib.sha256(canonical).hexdigest()}
    return fingerprints


@api_view(["POST"])
@permission_classes([CanAnalyze])
def run_audit(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    run = None
    worker_id = uuid.uuid4().hex
    try:
        with _audit_execution_lock(audit.pk) as acquired:
            if not acquired:
                return Response({"error": "An audit run is already in progress."}, status=409)
            with transaction.atomic():
                audit = PlanAudit.objects.select_for_update().select_related(
                    "organization", "plan", "summary_import"
                ).get(pk=audit.pk)
                if audit.summary_import.import_status != "accepted":
                    return Response({"error": "The selected summary import is not accepted."}, status=409)
                lease_seconds = getattr(settings, "PLAN_AUDIT_RUN_LEASE_SECONDS", 300)
                stale_before = timezone.now() - timedelta(seconds=lease_seconds)
                stale_runs = list(audit.runs.select_for_update().filter(calculation_status="running").filter(
                    Q(heartbeat_at__lt=stale_before) |
                    Q(heartbeat_at__isnull=True, started_at__lt=stale_before)))
                active_runs = audit.runs.filter(calculation_status="running")
                if active_runs.exclude(pk__in=[item.pk for item in stale_runs]).exists():
                    return Response({"error": "An audit run is already in progress."}, status=409)
                for abandoned in stale_runs:
                    abandoned.calculation_status = "failed"
                    abandoned.publication_status = "failed"
                    abandoned.completed_at = timezone.now()
                    abandoned.save(update_fields=["calculation_status", "publication_status", "completed_at"])
                    AuditEvent.objects.create(actor=request.user, action="plan_audit_run_abandoned",
                        entity_type="plan_audit", entity_id=str(audit.pk), details={"version": abandoned.version})
                now = timezone.now()
                previous = PlanAuditRun.objects.select_for_update().filter(
                    plan_audit_id=audit.pk, version=audit.current_version,
                ).first() if audit.current_version else None
                if previous and previous.publication_status in {"pending", "published"}:
                    was_published = previous.publication_status == "published"
                    previous.publication_status = "revoked"
                    previous.revoked_at = now
                    previous.revocation_reason = "A newer calculation run has started."
                    previous.save(update_fields=["publication_status", "revoked_at", "revocation_reason"])
                    if was_published:
                        AuditEvent.objects.create(actor=request.user, action="plan_audit_publication_revoked",
                            entity_type="plan_audit", entity_id=str(audit.pk),
                            details={"version": previous.version, "reason": previous.revocation_reason})
                latest_version = audit.runs.order_by("-version").values_list("version", flat=True).first() or 0
                version = latest_version + 1
                run = PlanAuditRun.objects.create(
                    plan_audit=audit, version=version, calculation_status="running",
                    publication_status="pending", summary_import=audit.summary_import,
                    source_sha256=audit.summary_import.file_hash, initiated_by=request.user,
                    started_at=now, heartbeat_at=now, worker_id=worker_id,
                    calculation_fingerprint=_calculation_fingerprint(),
                )
                audit.status = "running"
                audit.summary = {}
                audit.current_version = version
                audit.published_version = None
                audit.run_owner_token = worker_id
                audit.completed_at = None
                audit.report_generated_at = None
                audit.save(update_fields=["status", "summary", "current_version", "published_version",
                                          "run_owner_token", "completed_at", "report_generated_at"])
                AuditEvent.objects.create(actor=request.user, action="plan_audit_run_started",
                    entity_type="plan_audit", entity_id=str(audit.pk),
                    details={"version": version, "source_sha256": run.source_sha256})

            def heartbeat():
                changed = PlanAuditRun.objects.filter(
                    pk=run.pk, calculation_status="running", worker_id=worker_id,
                    plan_audit__run_owner_token=worker_id, plan_audit__current_version=run.version,
                ).update(heartbeat_at=timezone.now())
                if not changed:
                    raise RunOwnershipLost()

            summary = run_plan_audit(audit, run, heartbeat=heartbeat)
            run.reference_fingerprints = _run_reference_fingerprints(run)
            run.result_fingerprint = run_result_fingerprint(run)
            run.calculation_status = "completed"
            run.completed_at = timezone.now()
            with transaction.atomic():
                changed = PlanAuditRun.objects.filter(
                        pk=run.pk, calculation_status="running", worker_id=worker_id,
                        plan_audit__run_owner_token=worker_id, plan_audit__current_version=run.version,
                ).update(reference_fingerprints=run.reference_fingerprints,
                         result_fingerprint=run.result_fingerprint,
                         calculation_status="completed", completed_at=run.completed_at)
                if not changed:
                    raise RunOwnershipLost()
                audit.summary = summary
                has_warnings = any(status != "VALID" for status in summary["quality_status_counts"])
                audit.status = "needs_review" if has_warnings else "completed"
                audit.completed_at = run.completed_at
                changed = PlanAudit.objects.filter(
                    pk=audit.pk, current_version=run.version, run_owner_token=worker_id,
                ).update(summary=summary, status=audit.status, completed_at=run.completed_at,
                         run_owner_token="")
                if not changed:
                    raise RunOwnershipLost()
                audit.run_owner_token = ""
                AuditEvent.objects.create(actor=request.user, action="plan_audit_run_completed",
                    entity_type="plan_audit", entity_id=str(audit.pk),
                    details={"version": run.version, "result_fingerprint": run.result_fingerprint,
                             "result_rows": summary["result_rows"],
                             "savings_opportunities": summary["savings_opportunities"], "status": audit.status})
    except RunOwnershipLost:
        return Response({"error": "Audit run ownership was lost."}, status=409)
    except Exception:
        logger.exception("Plan audit execution failed for audit id %s.", audit.pk)
        _fail_owned_run(audit, run, worker_id, request.user)
        return Response({"error": "Audit execution failed. Check reference-data availability and server logs."},
                        status=500)
    return Response(audit_payload(audit, request.user))


@api_view(["GET"])
@permission_classes([CanView])
def audit_results(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    try:
        limit = min(max(int(request.query_params.get("limit", 100)), 1), 500)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return Response({"error": "limit and offset must be whole numbers."}, status=400)
    queryset = run_results(current_audit_run(audit))
    if request.query_params.get("hcpcs_code"):
        queryset = queryset.filter(hcpcs_code=request.query_params["hcpcs_code"].upper())
    if request.query_params.get("quarter"):
        queryset = queryset.filter(quarter=request.query_params["quarter"])
    if request.query_params.get("data_quality_status"):
        queryset = queryset.filter(data_quality_status=request.query_params["data_quality_status"])
    total = queryset.count()
    rows = queryset[offset:offset + limit]
    serialized = [result_payload(row) for row in rows]
    if is_client_only(request.user):
        for item in serialized:
            item.pop("source_references", None)
    return Response({"count": total, "limit": limit, "offset": offset,
                     "results": serialized})


@api_view(["GET"])
@permission_classes([CanView])
def drug_analysis(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    grouped = defaultdict(lambda: {
        "units": Decimal(0), "allowed": Decimal(0), "paid": Decimal(0),
        "qualities": defaultdict(int), "sites": set(), "quarters": set(), "rows": [],
    })
    for row in run_results(current_audit_run(audit)):
        item = grouped[row.hcpcs_code]
        item["units"] += row.total_units
        item["allowed"] += row.total_allowed_amount
        item["paid"] += row.total_paid_amount
        item["sites"].add(row.site_npi)
        item["quarters"].add(row.quarter)
        item["qualities"][row.data_quality_status] += 1
        item["rows"].append(row)

    def exclusion_reason(row, metric):
        refs = row.source_references or {}
        blocking_quality = {"UNIT_UNRESOLVED", "UNIT_AMBIGUOUS", "BILLING_UNIT_MISMATCH"}
        if (row.data_quality_status in blocking_quality
                or blocking_quality.intersection(row.data_quality_notes or [])
                or refs.get("unit_review_status") != "validated"):
            return "unit_not_validated"
        hashes = (refs.get("unit_review_source_sha256"), refs.get("drug_selection_source_sha256"))
        if any(not isinstance(value, str) or len(value) != 64
               or any(char not in "0123456789abcdef" for char in value.lower()) for value in hashes):
            return "unit_review_source_unverified"
        quarter = str(row.quarter or "")
        if (len(quarter) != 6 or not quarter[:4].isdigit()
                or quarter[4] != "Q" or quarter[5] not in "1234"):
            return "benchmark_quarter_invalid"
        try:
            units = Decimal(row.total_units)
            benchmark = Decimal(row.asp_payment_limit) if row.asp_payment_limit is not None else None
            numerator = Decimal(row.total_allowed_amount if metric == "allowed" else row.total_paid_amount)
            detail = getattr(row, f"{metric}_markup_multiple")
            detail = Decimal(detail) if detail is not None else None
        except (ArithmeticError, TypeError, ValueError):
            return "invalid_benchmark_inputs"
        if (not units.is_finite() or units <= 0 or not numerator.is_finite() or numerator < 0):
            return "invalid_benchmark_inputs"
        if benchmark is None or not benchmark.is_finite() or benchmark <= 0:
            return "asp_missing_or_nonpositive"
        asp_hash = refs.get("asp_source_sha256")
        if (not isinstance(asp_hash, str) or len(asp_hash) != 64
                or any(char not in "0123456789abcdef" for char in asp_hash.lower())):
            return "benchmark_source_unverified"
        if detail is None or not detail.is_finite() or detail < 0:
            return "detailed_markup_unavailable"
        return None

    result = []
    for code, item in sorted(grouped.items()):
        allowed_unit = item["allowed"] / item["units"] if item["units"] else None
        paid_unit = item["paid"] / item["units"] if item["units"] else None
        by_quarter = defaultdict(list)
        for row in item["rows"]:
            by_quarter[row.quarter].append(row)
        quarter_results = {}
        eligible_allowed_rows, eligible_paid_rows = set(), set()
        excluded_allowed_amount = Decimal(0)
        excluded_paid_amount = Decimal(0)
        excluded_total_units = Decimal(0)
        excluded_row_count = 0
        exclusion_counts = defaultdict(int)
        for quarter in sorted(by_quarter):
            rows = by_quarter[quarter]
            reasons = {row.pk: {
                "allowed": exclusion_reason(row, "allowed"),
                "paid": exclusion_reason(row, "paid"),
            } for row in rows}
            candidates = [row for row in rows if any(reason is None for reason in reasons[row.pk].values())]
            signatures = {
                (row.asp_payment_limit, (row.source_references or {}).get("asp_source_sha256"),
                 (row.source_references or {}).get("unit_review_source_sha256"),
                 (row.source_references or {}).get("unit_review_billing_qty"),
                 (row.source_references or {}).get("unit_review_billing_unit"),
                 (row.source_references or {}).get("drug_selection_source_sha256"))
                for row in candidates
            }
            mixed_basis = len(signatures) > 1
            if mixed_basis:
                for row in candidates:
                    reasons[row.pk]["allowed"] = "mixed_quarter_benchmark_or_unit_evidence"
                    reasons[row.pk]["paid"] = "mixed_quarter_benchmark_or_unit_evidence"

            eligible_allowed = [row for row in rows if reasons[row.pk]["allowed"] is None]
            eligible_paid = [row for row in rows if reasons[row.pk]["paid"] is None]
            eligible_allowed_rows.update(row.pk for row in eligible_allowed)
            eligible_paid_rows.update(row.pk for row in eligible_paid)
            allowed_benchmark_amount = sum(
                (Decimal(row.total_units) * Decimal(row.asp_payment_limit) for row in eligible_allowed), Decimal(0))
            paid_benchmark_amount = sum(
                (Decimal(row.total_units) * Decimal(row.asp_payment_limit) for row in eligible_paid), Decimal(0))
            allowed_numerator = sum((Decimal(row.total_allowed_amount) for row in eligible_allowed), Decimal(0))
            paid_numerator = sum((Decimal(row.total_paid_amount) for row in eligible_paid), Decimal(0))
            eligible_both = {row.pk for row in eligible_allowed} & {row.pk for row in eligible_paid}
            excluded_any = [row for row in rows if row not in eligible_allowed or row not in eligible_paid]
            q_excluded_units = sum((Decimal(row.total_units) for row in excluded_any), Decimal(0))
            q_excluded_allowed = sum((Decimal(row.total_allowed_amount) for row in rows
                                      if reasons[row.pk]["allowed"] is not None), Decimal(0))
            q_excluded_paid = sum((Decimal(row.total_paid_amount) for row in rows
                                   if reasons[row.pk]["paid"] is not None), Decimal(0))
            q_eligible_allowed_units = sum((Decimal(row.total_units) for row in eligible_allowed), Decimal(0))
            q_eligible_paid_units = sum((Decimal(row.total_units) for row in eligible_paid), Decimal(0))
            q_excluded_allowed_units = sum((Decimal(row.total_units) for row in rows
                                            if reasons[row.pk]["allowed"] is not None), Decimal(0))
            q_excluded_paid_units = sum((Decimal(row.total_units) for row in rows
                                         if reasons[row.pk]["paid"] is not None), Decimal(0))
            for row in excluded_any:
                excluded_row_count += 1
                row_reasons = {reason for reason in reasons[row.pk].values() if reason}
                for reason in row_reasons:
                    exclusion_counts[reason] += 1
            excluded_total_units += q_excluded_units
            excluded_allowed_amount += q_excluded_allowed
            excluded_paid_amount += q_excluded_paid
            quarter_asp_values = sorted({Decimal(row.asp_payment_limit) for row in eligible_allowed + eligible_paid})
            quarter_asp = quarter_asp_values[0] if len(quarter_asp_values) == 1 else None
            quarter_results[quarter] = {
                "eligible_row_count": len(eligible_both),
                "eligible_allowed_row_count": len(eligible_allowed),
                "eligible_paid_row_count": len(eligible_paid),
                "excluded_row_count": len(excluded_any),
                "visible_total_units": _decimal_text(sum((Decimal(row.total_units) for row in rows), Decimal(0))),
                "visible_allowed_amount": _decimal_text(sum((Decimal(row.total_allowed_amount) for row in rows), Decimal(0))),
                "visible_paid_amount": _decimal_text(sum((Decimal(row.total_paid_amount) for row in rows), Decimal(0))),
                "eligible_total_units": _decimal_text(sum((Decimal(row.total_units) for row in rows
                                                           if row.pk in eligible_both), Decimal(0))),
                "eligible_allowed_amount": _decimal_text(allowed_numerator),
                "eligible_paid_amount": _decimal_text(paid_numerator),
                "eligible_allowed_units": _decimal_text(q_eligible_allowed_units),
                "eligible_paid_units": _decimal_text(q_eligible_paid_units),
                "excluded_allowed_amount": _decimal_text(q_excluded_allowed),
                "excluded_paid_amount": _decimal_text(q_excluded_paid),
                "excluded_allowed_units": _decimal_text(q_excluded_allowed_units),
                "excluded_paid_units": _decimal_text(q_excluded_paid_units),
                "excluded_total_units": _decimal_text(q_excluded_units),
                "asp_payment_limit": _decimal_text(quarter_asp),
                "allowed_markup_multiple": _decimal_text(
                    allowed_numerator / allowed_benchmark_amount if allowed_benchmark_amount else None),
                "paid_markup_multiple": _decimal_text(
                    paid_numerator / paid_benchmark_amount if paid_benchmark_amount else None),
                "comparison_status": "not_comparable" if mixed_basis or not eligible_allowed and not eligible_paid
                                     else "comparable",
            }
        allowed_numerator = sum((Decimal(row.total_allowed_amount) for row in item["rows"]
                                 if row.pk in eligible_allowed_rows), Decimal(0))
        paid_numerator = sum((Decimal(row.total_paid_amount) for row in item["rows"]
                              if row.pk in eligible_paid_rows), Decimal(0))
        allowed_benchmark_amount = sum((Decimal(row.total_units) * Decimal(row.asp_payment_limit)
                                        for row in item["rows"] if row.pk in eligible_allowed_rows), Decimal(0))
        paid_benchmark_amount = sum((Decimal(row.total_units) * Decimal(row.asp_payment_limit)
                                     for row in item["rows"] if row.pk in eligible_paid_rows), Decimal(0))
        eligible_total_units = sum((Decimal(row.total_units) for row in item["rows"]
                                    if row.pk in (eligible_allowed_rows & eligible_paid_rows)), Decimal(0))
        eligible_allowed_units = sum((Decimal(row.total_units) for row in item["rows"]
                                      if row.pk in eligible_allowed_rows), Decimal(0))
        eligible_paid_units = sum((Decimal(row.total_units) for row in item["rows"]
                                   if row.pk in eligible_paid_rows), Decimal(0))
        excluded_allowed_units = item["units"] - eligible_allowed_units
        excluded_paid_units = item["units"] - eligible_paid_units
        single_quarter = len(item["quarters"]) == 1
        allowed_markup = (allowed_numerator / allowed_benchmark_amount
                          if single_quarter and allowed_benchmark_amount else None)
        paid_markup = (paid_numerator / paid_benchmark_amount
                       if single_quarter and paid_benchmark_amount else None)
        only_quarter = sorted(item["quarters"])[0] if single_quarter else None
        eligible_quarter = quarter_results.get(only_quarter) if only_quarter else None
        result.append({
            "hcpcs_code": code, "total_units": _decimal_text(item["units"]),
            "visible_allowed_amount": _decimal_text(item["allowed"]),
            "visible_paid_amount": _decimal_text(item["paid"]),
            "allowed_price_per_unit": _decimal_text(allowed_unit),
            "paid_price_per_unit": _decimal_text(paid_unit),
            "asp_payment_limit": eligible_quarter["asp_payment_limit"] if eligible_quarter else None,
            "allowed_markup_multiple": _decimal_text(allowed_markup),
            "paid_markup_multiple": _decimal_text(paid_markup),
            "hospitals": len(item["sites"]), "quarters": sorted(item["quarters"]),
            "data_quality_status_counts": dict(item["qualities"]),
            "quarter_breakdown": quarter_results,
            "benchmark_comparison_status": ("not_comparable" if not eligible_allowed_rows and not eligible_paid_rows
                                             else "single_quarter" if single_quarter else "quarter_specific_only"),
            "eligible_row_count": len(eligible_allowed_rows & eligible_paid_rows),
            "eligible_allowed_row_count": len(eligible_allowed_rows),
            "eligible_paid_row_count": len(eligible_paid_rows),
            "eligible_allowed_amount": _decimal_text(allowed_numerator),
            "eligible_paid_amount": _decimal_text(paid_numerator),
            "eligible_total_units": _decimal_text(eligible_total_units),
            "eligible_allowed_units": _decimal_text(eligible_allowed_units),
            "eligible_paid_units": _decimal_text(eligible_paid_units),
            "excluded_row_count": excluded_row_count,
            "excluded_allowed_amount": _decimal_text(excluded_allowed_amount),
            "excluded_paid_amount": _decimal_text(excluded_paid_amount),
            "excluded_total_units": _decimal_text(excluded_total_units),
            "excluded_allowed_units": _decimal_text(excluded_allowed_units),
            "excluded_paid_units": _decimal_text(excluded_paid_units),
            "benchmark_exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
            "markup_aggregation": "eligible amount divided by eligible units times each matching ASP; multi-quarter totals are shown by quarter",
            "totals_scope": "visible_approved_aggregate_rows_only",
        })
    return Response({"audit_id": audit.pk, "results": result})


def _paged_audit_response(request, queryset, serialize, *, default_limit=200, max_limit=500):
    try:
        limit = min(max(int(request.query_params.get("limit", default_limit)), 1), max_limit)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return Response({"error": "limit and offset must be whole numbers."}, status=400)
    total = queryset.count()
    page = list(queryset[offset:offset + limit])
    next_offset = offset + len(page) if offset + len(page) < total else None
    return Response({
        "count": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "previous_offset": max(0, offset - limit) if offset else None,
        "results": [serialize(row) for row in page],
    })



@api_view(["GET"])
@permission_classes([CanView])
def hospital_comparison(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    client_only = is_client_only(request.user)
    rows = (
        run_results(current_audit_run(audit))
        .exclude(hospital_price_per_unit__isnull=True)
        .order_by("pk")
    )

    def serialize(row):
        result = {
            "hcpcs_code": row.hcpcs_code,
            "site_npi": row.site_npi,
            "quarter": row.quarter,
            "service_setting": row.service_setting,
            "plan_allowed_price_per_unit": _decimal_text(
                row.plan_allowed_price_per_unit
            ),
            "hospital_reported_price_per_unit": _decimal_text(
                row.hospital_price_per_unit
            ),
            "hospital_markup_multiple": _decimal_text(
                row.hospital_markup_multiple
            ),
            "plan_to_hospital_price_multiple": _decimal_text(
                row.plan_to_hospital_price_multiple
            ),
            "data_quality_status": row.data_quality_status,
            "interpretation": (
                "Hospital-reported reference price; "
                "not the employer plan's contracted rate."
            ),
        }
        if not client_only:
            result["source_references"] = row.source_references
        return result

    return _paged_audit_response(request, rows, serialize)


@api_view(["GET"])
@permission_classes([CanView])
def asp_benchmark(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    client_only = is_client_only(request.user)
    rows = run_results(current_audit_run(audit)).order_by(
        "hcpcs_code", "quarter", "site_npi",
        "service_setting", "pk"
    )

    def serialize(row):
        result = {
            "hcpcs_code": row.hcpcs_code,
            "site_npi": row.site_npi,
            "quarter": row.quarter,
            "plan_allowed_price_per_unit": _decimal_text(
                row.plan_allowed_price_per_unit
            ),
            "plan_paid_price_per_unit": _decimal_text(
                row.plan_paid_price_per_unit
            ),
            "asp_payment_limit": _decimal_text(
                row.asp_payment_limit
            ),
            "allowed_markup_multiple": _decimal_text(
                row.allowed_markup_multiple
            ),
            "paid_markup_multiple": _decimal_text(
                row.paid_markup_multiple
            ),
            "data_quality_status": row.data_quality_status,
        }
        if not client_only:
            result["source_references"] = row.source_references
        return result

    return _paged_audit_response(request, rows, serialize)


@api_view(["GET"])
@permission_classes([CanView])
def audit_overview(request, audit_id):
    audit = get_visible_audit(request.user, audit_id)
    return Response({"audit": audit_payload(audit, request.user),
                     "metrics": _visible_totals(
                         audit, current_audit_run(audit),
                         include_unvalidated_savings=not is_client_only(request.user),
                     )})


# ---------------------------------------------------------------------------
# Historical spending analytics (Task B)
# ---------------------------------------------------------------------------

_ALLOWED_HCPCS_RE = __import__("re").compile(r"^[A-Z0-9]{5}$")
_ALLOWED_QUARTER_RE = __import__("re").compile(r"^20\d{2}Q[1-4]$")
_ALLOWED_NPI_RE = __import__("re").compile(r"^\d{10}$")
_ALLOWED_QUALITY_STATUSES = frozenset(["VALID", "UNIT_UNRESOLVED", "REFERENCE_NOT_FOUND", "NETWORK_UNVERIFIED"])


def _safe_filter(queryset, params):
    """Apply allow-listed query filters; silently ignore unrecognised or unsafe values."""
    hcpcs = str(params.get("hcpcs_code", "")).upper().strip()
    if hcpcs and _ALLOWED_HCPCS_RE.fullmatch(hcpcs):
        queryset = queryset.filter(hcpcs_code=hcpcs)
    quarter = str(params.get("quarter", "")).upper().strip()
    if quarter and _ALLOWED_QUARTER_RE.fullmatch(quarter):
        queryset = queryset.filter(quarter=quarter)
    site_npi = str(params.get("site_npi", "")).strip()
    if site_npi and _ALLOWED_NPI_RE.fullmatch(site_npi):
        queryset = queryset.filter(site_npi=site_npi)
    quality = str(params.get("data_quality_status", "")).upper().strip()
    if quality and quality in _ALLOWED_QUALITY_STATUSES:
        queryset = queryset.filter(data_quality_status=quality)
    service_setting = str(params.get("service_setting", "")).strip()
    if service_setting and len(service_setting) <= 80:
        queryset = queryset.filter(service_setting=service_setting)
    return queryset


@api_view(["GET"])
@permission_classes([CanView])
def historical_spending(request, audit_id):
    """
    Historical spending view for a completed plan audit.

    Returns:
    - summary: audit header + top-level metrics
    - by_quarter: allowed and paid totals grouped by quarter
    - by_hcpcs: spending totals grouped by HCPCS code
    - by_site: spending totals grouped by site NPI
    - by_setting: spending totals grouped by service setting
    - data_quality: quality status distribution
    - data_notes: standard interpretation notes

    Security:
    - Enforces org/plan/audit access via get_visible_audit (same chain as audit_results).
    - Returns only PlanAuditResult rows already stored from the approved import.
    - Suppressed cells are excluded because suppressed rows are never stored
      (ClaimsSummaryImport only stores accepted rows passing the extractor's suppression controls).
    - No raw claims, member IDs, or filesystem paths are exposed.
    - Filters are allow-listed; unrecognised values are silently ignored.
    - Decimal precision preserved throughout using Decimal arithmetic.
    """
    audit = get_visible_audit(request.user, audit_id)

    # Only completed audits have meaningful result rows.
    if audit.status not in {"completed", "needs_review"}:
        return Response({
            "audit_id": audit.pk,
            "available": False,
            "reason": "Run the audit to populate historical spending analytics.",
            "by_quarter": [],
            "by_hcpcs": [],
            "by_site": [],
            "by_setting": [],
            "data_quality": {},
            "data_notes": _spending_notes(),
        })

    queryset = run_results(current_audit_run(audit))
    queryset = _safe_filter(queryset, request.query_params)

    # Aggregate across the filtered result set. All arithmetic uses Decimal.
    by_quarter = defaultdict(lambda: {"allowed": Decimal(0), "paid": Decimal(0), "units": Decimal(0), "rows": 0})
    by_hcpcs = defaultdict(lambda: {"allowed": Decimal(0), "paid": Decimal(0), "units": Decimal(0),
                                    "drug_description": "", "sites": set(), "quarters": set()})
    by_site = defaultdict(lambda: {"allowed": Decimal(0), "paid": Decimal(0), "units": Decimal(0),
                                   "hcpcs_set": set(), "network_statuses": set()})
    by_setting = defaultdict(lambda: {"allowed": Decimal(0), "paid": Decimal(0), "units": Decimal(0), "rows": 0})
    quality_counts = defaultdict(int)

    total_allowed = Decimal(0)
    total_paid = Decimal(0)
    total_units = Decimal(0)
    row_count = 0
    matched_benchmarks = 0
    unmatched_benchmarks = 0
    distinct_hcpcs = set()
    distinct_sites = set()

    for row in queryset.iterator(chunk_size=2000):
        row_count += 1
        total_allowed += row.total_allowed_amount
        total_paid += row.total_paid_amount
        total_units += row.total_units
        distinct_hcpcs.add(row.hcpcs_code)
        distinct_sites.add(row.site_npi)
        quality_counts[row.data_quality_status] += 1

        if row.asp_payment_limit is not None:
            matched_benchmarks += 1
        else:
            unmatched_benchmarks += 1

        q = by_quarter[row.quarter]
        q["allowed"] += row.total_allowed_amount
        q["paid"] += row.total_paid_amount
        q["units"] += row.total_units
        q["rows"] += 1

        h = by_hcpcs[row.hcpcs_code]
        h["allowed"] += row.total_allowed_amount
        h["paid"] += row.total_paid_amount
        h["units"] += row.total_units
        h["sites"].add(row.site_npi)
        h["quarters"].add(row.quarter)
        if not h["drug_description"] and row.drug_description:
            h["drug_description"] = row.drug_description

        s = by_site[row.site_npi]
        s["allowed"] += row.total_allowed_amount
        s["paid"] += row.total_paid_amount
        s["units"] += row.total_units
        s["hcpcs_set"].add(row.hcpcs_code)
        s["network_statuses"].add(row.network_status)

        g = by_setting[row.service_setting or "unknown"]
        g["allowed"] += row.total_allowed_amount
        g["paid"] += row.total_paid_amount
        g["units"] += row.total_units
        g["rows"] += 1

    if row_count == 0:
        return Response({
            "audit_id": audit.pk,
            "available": False,
            "reason": (
                "No audit results are available for the current filters. "
                "If no filters are applied, the audit may not have produced result rows — "
                "check the data quality endpoint."
            ),
            "by_quarter": [],
            "by_hcpcs": [],
            "by_site": [],
            "by_setting": [],
            "data_quality": {},
            "data_notes": _spending_notes(),
        })

    quarters_sorted = sorted(by_quarter.keys())
    by_quarter_list = [
        {
            "quarter": q,
            "total_allowed_amount": _decimal_text(by_quarter[q]["allowed"]),
            "total_paid_amount": _decimal_text(by_quarter[q]["paid"]),
            "total_units": _decimal_text(by_quarter[q]["units"]),
            "result_row_count": by_quarter[q]["rows"],
        }
        for q in quarters_sorted
    ]

    by_hcpcs_list = sorted(
        [
            {
                "hcpcs_code": code,
                "drug_description": item["drug_description"] or None,
                "total_allowed_amount": _decimal_text(item["allowed"]),
                "total_paid_amount": _decimal_text(item["paid"]),
                "total_units": _decimal_text(item["units"]),
                "site_count": len(item["sites"]),
                "quarter_count": len(item["quarters"]),
                "allowed_per_unit": _decimal_text(
                    item["allowed"] / item["units"] if item["units"] else None
                ),
                "paid_per_unit": _decimal_text(
                    item["paid"] / item["units"] if item["units"] else None
                ),
            }
            for code, item in by_hcpcs.items()
        ],
        key=lambda r: r["hcpcs_code"],
    )

    by_site_list = sorted(
        [
            {
                "site_npi": npi,
                "total_allowed_amount": _decimal_text(item["allowed"]),
                "total_paid_amount": _decimal_text(item["paid"]),
                "total_units": _decimal_text(item["units"]),
                "hcpcs_count": len(item["hcpcs_set"]),
                "network_status_summary": _resolve_network_summary(item["network_statuses"]),
            }
            for npi, item in by_site.items()
        ],
        key=lambda r: r["site_npi"],
    )

    by_setting_list = sorted(
        [
            {
                "service_setting": setting,
                "total_allowed_amount": _decimal_text(item["allowed"]),
                "total_paid_amount": _decimal_text(item["paid"]),
                "total_units": _decimal_text(item["units"]),
                "result_row_count": item["rows"],
            }
            for setting, item in by_setting.items()
        ],
        key=lambda r: r["service_setting"],
    )

    return Response({
        "audit_id": audit.pk,
        "audit_name": audit.audit_name,
        "organization_name": audit.organization.organization_name,
        "plan_name": audit.plan.plan_name,
        "reporting_period": audit.reporting_period,
        "audit_status": audit.status,
        "available": True,
        "summary": {
            "total_allowed_amount": _decimal_text(total_allowed),
            "total_paid_amount": _decimal_text(total_paid),
            "total_units": _decimal_text(total_units),
            "result_row_count": row_count,
            "distinct_hcpcs_count": len(distinct_hcpcs),
            "distinct_site_count": len(distinct_sites),
            "distinct_quarter_count": len(by_quarter),
            "matched_benchmark_rows": matched_benchmarks,
            "unmatched_benchmark_rows": unmatched_benchmarks,
            "totals_scope": "visible_approved_aggregate_rows_only",
        },
        "by_quarter": by_quarter_list,
        "by_hcpcs": by_hcpcs_list,
        "by_site": by_site_list,
        "by_setting": by_setting_list,
        "data_quality": dict(quality_counts),
        "data_notes": _spending_notes(),
    })


def _resolve_network_summary(statuses):
    """Summarise multiple network statuses for a site without fabricating coverage."""
    if not statuses:
        return "NETWORK_STATUS_UNKNOWN"
    if statuses == {"IN_NETWORK"}:
        return "IN_NETWORK"
    if statuses == {"OUT_OF_NETWORK"}:
        return "OUT_OF_NETWORK"
    return "MIXED_OR_UNKNOWN"


def _spending_notes():
    return [
        "Totals include only approved, unsuppressed aggregate rows from the selected audit.",
        "Suppressed cells (fewer than 11 distinct members) are excluded by the client extractor and are not stored.",
        "Complementary suppression is declared in the manifest and verified at import.",
        "Amounts are shown without member counts or claim-level detail to preserve privacy controls.",
        "Hospital price references are not this plan's contracted rates.",
        "Potential savings remain pending clinical review and network verification; they are not guarantees.",
        "Historical charts do not include synthetic research claims, ASP references, or hospital-published prices.",
    ]

