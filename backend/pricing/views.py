"""API views. Headline numbers use negotiated dollar rates with status 'ok' only.

Rows flagged review_range, unit_unresolved, percent_of_charges, etc. are
counted and listed, but never mixed into medians.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime

from django.http import FileResponse, HttpResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import connections

from . import data
from .models import AuditEvent, DrugUnitReview, ProcessingJob, ReportRecord, SourceFile
from .permissions import ADMIN_GROUP, CanAdminister, CanAnalyze, has_any_role
from pipeline.common import csv_safe_cell

HEADLINE = "price_type = 'negotiated_dollar' AND status = 'ok'"
VIEWER_HEADLINE = "price_type = 'negotiated_dollar' AND status = 'ok' AND coalesce(reviewed, false)"
logger = logging.getLogger(__name__)

RATE_COLUMNS = [
    "hospital_key", "hospital_label", "system", "locations", "hcpcs", "drug_name",
    "description", "ndc11", "matched_via", "setting", "billing_class", "payer_name",
    "plan_name", "payer_group", "price_type", "price", "gross_charge", "discounted_cash",
    "negotiated_dollar", "estimated_amount", "median_amount", "p10_amount", "p90_amount",
    "drug_unit", "drug_unit_type",
    "billing_units", "unit_note", "benchmark_quarter", "asp_payment_limit", "asp_dosage",
    "price_per_billing_unit", "markup_multiple", "pct_over_asp", "negotiated_percentage",
    "methodology", "file_last_updated", "reviewed", "source_file", "source_member",
    "source_sha256", "status",
]
VIEWER_RATE_COLUMNS = [column for column in RATE_COLUMNS if column not in {
    "source_file", "source_member", "source_sha256",
}]
SORTABLE = {"markup_multiple", "price_per_billing_unit", "price", "hospital_label",
            "payer_group", "drug_name", "status"}
_RATE_SCHEMA_CACHE: tuple[str, int, int, set[str]] | None = None


def _missing(e: data.DataMissing) -> Response:
    return Response({"error": str(e)}, status=503)


def _bounded_query_int(request, name: str, default: int, minimum: int, maximum: int):
    try:
        return min(max(int(request.query_params.get(name, default)), minimum), maximum)
    except (TypeError, ValueError):
        return None


def _viewer_release_payload(request):
    """Return only the current immutable report payload to a Viewer."""
    if has_any_role(request.user, {ADMIN_GROUP}):
        return None, None
    try:
        source_hash = data.comparison_sha256()
    except data.DataMissing as exc:
        return None, Response({"error": str(exc)}, status=503)
    report = (ReportRecord.objects.filter(source_hash=source_hash,
                                          config_hash=data.config_sha256(), status="released")
              .order_by("-generated_at").first())
    if report is None:
        return None, Response({"error": "No current report has been released for Viewer access."}, status=403)
    path = settings.BASE_DIR.parent / "reports" / "dashboard_data.json"
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, ValueError):
        return None, Response({"error": "The released report artifact is unavailable."}, status=503)
    expected_digest = (report.metadata or {}).get("dashboard_sha256")
    if not expected_digest or hashlib.sha256(raw).hexdigest() != expected_digest or payload.get("draft"):
        return None, Response({"error": "The released report artifact has changed; an Admin must rebuild and release it."}, status=409)
    payload["clinical_signoffs"] = (report.metadata or {}).get("clinical_signoffs", {})
    return payload, None


def _viewer_dashboard_summary(payload: dict) -> dict:
    return {
        "data_evidence_state": "released_report",
        "generated_at": payload.get("data_build_generated"),
        "reporting_period": (f"{payload.get('file_date_min')} to {payload.get('file_date_max')}"
                             if payload.get("file_date_min") else None),
        "benchmark_quarters_used": ", ".join(payload.get("benchmark_quarters") or []) or None,
        "latest_asp_quarter": max(payload.get("benchmark_quarters") or [""]) or None,
        "hospitals_covered": payload.get("hospital_count", 0),
        "hospitals_with_valid_rates": payload.get("hospital_count", 0),
        "systems": payload.get("system_count", 0),
        "drugs_compared": payload.get("drug_count", 0),
        "headline_rates": payload.get("headline_rows", 0),
        "validated_comparison_rates": payload.get("headline_rows", 0),
        "rows": payload.get("comparison_rows", 0),
        "released_report": True,
    }


def _archive_input_issue(path: Path, config: dict) -> str | None:
    """Reject malformed, encrypted, traversal, and extreme-ratio ZIP inputs."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > int(config.get("upload_max_archive_members", 100_000)):
                return "Archive contains too many entries."
            total_uncompressed = 0
            max_uncompressed = int(config.get("upload_max_uncompressed_bytes", 5_368_709_120))
            max_ratio = float(config.get("upload_max_compression_ratio", 1000))
            for member in members:
                name = PurePosixPath(member.filename)
                if name.is_absolute() or ".." in name.parts or (name.parts and ":" in name.parts[0]):
                    return "Archive contains an unsafe member path."
                if member.flag_bits & 0x1:
                    return "Encrypted archive members are not supported."
                total_uncompressed += member.file_size
                ratio = member.file_size / max(member.compress_size, 1)
                if ratio > max_ratio:
                    return "Archive member compression ratio exceeds the configured safety limit."
                if total_uncompressed > max_uncompressed:
                    return "Archive uncompressed size exceeds the configured safety limit."
    except (OSError, zipfile.BadZipFile, ValueError):
        return "The uploaded ZIP/XLSX archive is invalid."
    return None


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Report service dependencies without exposing credentials or query details."""
    checks = {"api": "ok"}
    try:
        connections["default"].ensure_connection()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        info = data.run_info()
        comparison = data.files()["comparison"]
        checks["parquet"] = "ok" if comparison.is_file() and info.get("rows") is not None else "unavailable"
    except (data.DataMissing, OSError, ValueError):
        checks["parquet"] = "unavailable"
    healthy = all(value == "ok" for value in checks.values())
    return Response({"status": "ok" if healthy else "degraded", "checks": checks},
                    status=200 if healthy else 503)


@api_view(["GET"])
def meta(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    if payload is not None:
        summary = _viewer_dashboard_summary(payload)
        summary["hospitals"] = summary["hospitals_covered"]
        return Response(summary)
    try:
        info = data.run_info()
        evidence_state = data.require_current_scope()
        statuses = data.query("SELECT status, count(*) AS n FROM {cmp} GROUP BY 1 ORDER BY 2 DESC",
                              cmp="comparison")
        counts = data.query(
            "SELECT count(DISTINCT hospital_key) AS hospitals, count(DISTINCT system) AS systems,"
            f" count(*) FILTER (WHERE {HEADLINE}) AS headline_rates FROM {{cmp}}",
            cmp="comparison")[0]
    except data.DataMissing as e:
        return _missing(e)
    return Response({**info, "statuses": statuses, **counts,
                     "data_evidence_state": evidence_state,
                     "data_is_archived_snapshot": evidence_state == "archived_snapshot"})


@api_view(["GET"])
def dashboard_summary(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    if payload is not None:
        return Response(_viewer_dashboard_summary(payload))
    try:
        evidence_state = data.require_current_scope()
        info = data.run_info()
        status_rows = data.query("SELECT status, count(*) AS n FROM {cmp} GROUP BY status ORDER BY n DESC",
                                 cmp="comparison")
        headline = data.query(
            f"SELECT count(*) AS rates, count(DISTINCT hcpcs) AS drugs, "
            f"count(DISTINCT hospital_key) AS hospitals FROM {{cmp}} WHERE {HEADLINE}",
            cmp="comparison")[0]
        validated_rates = data.query(
            f"SELECT count(*) AS rates FROM {{cmp}} WHERE {HEADLINE} AND coalesce(reviewed, false)",
            cmp="comparison")[0]["rates"]
        coverage = data.query("SELECT count(DISTINCT hospital_key) AS hospitals, "
                               "count(DISTINCT system) AS systems FROM {cmp}", cmp="comparison")[0]
        quality = data.query("SELECT count(*) AS files, count(*) FILTER (WHERE error IS NOT NULL) AS errors, "
                             "count(*) FILTER (WHERE coalesce(drug_rows, 0) > 0) AS files_with_drug_rows, "
                             "count(*) FILTER (WHERE coalesce(drug_rows, 0) = 0) AS zero_drug_files, "
                             "sum(coalesce(drug_rows, 0)) AS normalized_drug_rows "
                             "FROM {quality}", quality="quality")[0]
        counts = {r["status"]: r["n"] for r in status_rows}
        asp_quarters = info.get("asp_quarters", [])
        latest_asp_quarter = max(asp_quarters) if asp_quarters else None
        used_meta = data.query(
            f"""SELECT string_agg(DISTINCT benchmark_quarter, ', ') AS benchmark_quarters_used,
                       min(file_last_updated) AS file_date_min,
                       max(file_last_updated) AS file_date_max,
                       count(*) AS eligible_rates,
                       count(DISTINCT hcpcs) AS drugs_compared,
                       count(DISTINCT hospital_key) AS hospitals_with_valid_rates
                FROM {{cmp}} WHERE {HEADLINE}""", cmp="comparison")[0]
        review_total = counts.get("unit_unresolved", 0) + counts.get("review_range", 0) + counts.get("algorithm_only", 0)
    except data.DataMissing as e:
        return _missing(e)
    discovered_hospitals = _count_ohio_hospital_universe()
    market_report_path = settings.BASE_DIR.parent / "reports" / "ohio_market_report_draft.md"
    latest_report_generated = market_report_path.stat().st_mtime if market_report_path.exists() else None
    return Response({
        **info,
        "data_evidence_state": evidence_state,
        "data_is_archived_snapshot": evidence_state == "archived_snapshot",
        "hospitals_covered": coverage["hospitals"],
        "hospital_file_count": quality["files"],
        "hospital_files_with_drug_rows": quality["files_with_drug_rows"],
        "hospital_files_with_errors": quality["errors"],
        "hospitals_with_valid_rates": used_meta["hospitals_with_valid_rates"],
        "systems": coverage["systems"],
        "headline_rates": headline["rates"],
        "drugs_compared": used_meta["drugs_compared"],
        "comparisons_requiring_review": review_total,
        "review_breakdown": {
            "unresolved_units": counts.get("unit_unresolved", 0),
            "outliers_review_range": counts.get("review_range", 0),
            "algorithm_or_percent_charges": counts.get("algorithm_only", 0),
        },
        "statuses": status_rows,
        "hospitals_discovered": discovered_hospitals,
        "hospital_file_coverage": "not_reconciled_to_ccn_npi" if discovered_hospitals is not None else "unavailable",
        "benchmark_quarters_used": used_meta["benchmark_quarters_used"] or latest_asp_quarter,
        "latest_asp_quarter": latest_asp_quarter,
        "reporting_period": f"{used_meta['file_date_min']} to {used_meta['file_date_max']}" if used_meta['file_date_min'] else None,
        "hospitals_with_price_files": None,
        "hospitals_with_unavailable_files": None,
        "latest_report_generated_epoch": latest_report_generated,
        "headline": headline,
        "validated_comparison_rates": validated_rates,
        "status_counts": status_rows,
        "unresolved_unit_rows": counts.get("unit_unresolved", 0) + counts.get("unit_ambiguous", 0),
        "review_range_rows": counts.get("review_range", 0),
        "quality": quality,
    })


def _count_ohio_hospital_universe():
    """Count OH facilities in configured provider-list inputs; return None if absent."""
    config_path = settings.BASE_DIR.parent / "config" / "report.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        spec = next((i for i in config.get("required_inputs", []) + config.get("supplemental_inputs", [])
                     if i.get("key") == "hospital_list"), None)
        if not spec:
            return None
        paths = set()
        for pattern in spec.get("patterns", []):
            paths.update(p for p in settings.BASE_DIR.parent.glob(pattern) if p.is_file() and p.suffix.lower() == ".csv")
        if not paths:
            return None
        latest = max(paths, key=lambda p: p.stat().st_mtime)
        with latest.open(newline="", encoding="utf-8-sig") as f:
            return sum(1 for row in csv.DictReader(f) if (row.get("State") or "").strip().upper() == "OH")
    except (OSError, json.JSONDecodeError, csv.Error):
        return None


@api_view(["GET"])
def dashboard_price_trends(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    where = ""
    params = []
    if payload is not None:
        where = ("WHERE status = 'ok' AND coalesce(reviewed, false) "
                 "AND hcpcs IN (SELECT unnest(?))")
        params = [payload.get("drug_codes") or []]
    try:
        by_drug = data.query(
            f"""SELECT hcpcs, any_value(drug_name) AS drug_name,
                       median(markup_multiple) AS median_markup, count(*) AS rates
                FROM {{cmp}} {where} GROUP BY hcpcs ORDER BY median_markup DESC NULLS LAST""",
            params, cmp="comparison")
        by_payer = data.query(
            f"""SELECT payer_group, hcpcs, count(*) AS rates,
                       median(markup_multiple) AS median_markup
                FROM {{cmp}} {where} GROUP BY payer_group, hcpcs ORDER BY payer_group, median_markup DESC NULLS LAST""",
            params, cmp="comparison")
        by_setting = data.query(
            f"""SELECT setting, hcpcs, count(*) AS rates,
                       median(markup_multiple) AS median_markup
                FROM {{cmp}} {where} GROUP BY setting, hcpcs ORDER BY setting, median_markup DESC NULLS LAST""",
            params, cmp="comparison")
        by_quarter = data.query(
            f"""SELECT benchmark_quarter, hcpcs, count(*) AS rates,
                       median(markup_multiple) AS median_markup
                FROM {{cmp}} {where} GROUP BY benchmark_quarter, hcpcs ORDER BY benchmark_quarter, hcpcs""",
            params, cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    return Response({"by_drug": by_drug, "by_payer_group": by_payer,
                     "by_setting": by_setting, "by_quarter": by_quarter})


@api_view(["GET"])
@permission_classes([CanAnalyze])
def sources(request):
    """Return configured input requirements and observed source files.

    The catalog must remain useful before the manifest has been generated: it
    tells the user which real inputs are present and which are still required.
    """
    project_dir = settings.BASE_DIR.parent
    config_path = project_dir / "config" / "report.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return Response({"error": f"Source configuration unavailable: {e}"}, status=503)

    specs = config.get("required_inputs", []) + config.get("supplemental_inputs", [])
    manifest = project_dir / "data" / "manifests" / "file_inventory.csv"
    if not manifest.exists():
        manifest = project_dir / "data" / "manifest.csv"
    manifest_rows = []
    if manifest.exists():
        try:
            with manifest.open(newline="", encoding="utf-8-sig") as f:
                manifest_rows = list(csv.DictReader(f))
        except (OSError, csv.Error):
            manifest_rows = []
    by_source = {}
    hashes_by_path = {}
    for row in manifest_rows:
        key = row.get("source", "")
        by_source.setdefault(key, []).append(row)
        path = row.get("relative_path") or f"data/raw_essential_inputs/{key}/{row.get('subfolder', '')}/{row.get('file_name', '')}".replace("//", "/")
        if row.get("sha256"):
            hashes_by_path[path] = row["sha256"]
    for record in SourceFile.objects.all().only("relative_path", "sha256"):
        hashes_by_path.setdefault(record.relative_path, record.sha256)

    result = []
    for spec in specs:
        key = spec.get("key", "")
        paths = set()
        for pattern in spec.get("patterns", []):
            paths.update(p for p in project_dir.glob(pattern) if p.is_file() and not p.name.endswith(".part"))
        files = [{"name": p.name, "path": p.relative_to(project_dir).as_posix(),
                  "size_bytes": p.stat().st_size,
                  "modified": p.stat().st_mtime,
                  "sha256": hashes_by_path.get(p.relative_to(project_dir).as_posix())}
                 for p in sorted(paths)]
        manifest_files = by_source.get(key, [])
        for row in manifest_files:
            if not row.get("sha256"):
                continue
            if not any(x["sha256"] == row["sha256"] for x in files):
                files.append({"name": row.get("file_name", ""),
                              "path": row.get("relative_path") or f"data/raw_essential_inputs/{key}/{row.get('subfolder', '')}/{row.get('file_name', '')}".replace("//", "/"),
                              "size_bytes": int(row.get("size_bytes") or 0),
                              "modified": row.get("modified"), "sha256": row["sha256"]})
        result.append({"source": key, "label": spec.get("label", key),
                       "purpose": spec.get("purpose", ""),
                       "required": spec in config.get("required_inputs", []),
                       "files": files, "file_count": len(files),
                       "status": "available" if files else "missing"})
    return Response(result)


@api_view(["POST"])
@permission_classes([CanAnalyze])
@parser_classes([MultiPartParser, FormParser])
def source_upload(request):
    upload = request.FILES.get("file")
    source_key = str(request.data.get("source_key", "")).strip()
    if upload is None or not source_key:
        return Response({"error": "Provide source_key and file."}, status=400)
    config_path = settings.BASE_DIR.parent / "config" / "report.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Response({"error": "Source upload configuration is unavailable."}, status=503)
    source_specs = config.get("required_inputs", []) + config.get("supplemental_inputs", [])
    if source_key not in {spec.get("key") for spec in source_specs}:
        return Response({"error": "Unknown source key."}, status=400)
    max_bytes = int(config.get("upload_max_bytes", 0))
    if not max_bytes or upload.size > max_bytes:
        return Response({"error": "File exceeds the configured upload size limit."}, status=413)
    extension = Path(upload.name).suffix.lower()
    if extension not in {e.lower() for e in config.get("allowed_upload_extensions", [])}:
        return Response({"error": "Unsupported file extension."}, status=415)

    sample = upload.read(8)
    upload.seek(0)
    if extension in {".zip", ".xlsx"} and not sample.startswith(b"PK"):
        return Response({"error": "File signature does not match the declared ZIP/XLSX format."}, status=415)
    if extension == ".xls" and not sample.startswith(b"\xd0\xcf\x11\xe0"):
        return Response({"error": "File signature does not match the declared XLS format."}, status=415)

    from pipeline.common import paths as pipeline_paths
    raw_root = pipeline_paths()["raw"]
    original_name = Path(upload.name).name
    safe_name = re.sub(r"[^A-Za-z0-9._()-]+", "_", original_name).strip("._")[:220]
    if not safe_name:
        return Response({"error": "The uploaded file name is invalid."}, status=400)
    if source_key == "hospital_mrf":
        system = re.sub(r"[^A-Za-z0-9_-]+", "_",
                        str(request.data.get("system", "")).strip()).strip("_- ").lower()
        snapshot_date = str(request.data.get("snapshot_date", "")).strip()
        try:
            datetime.strptime(snapshot_date, "%Y-%m-%d")
        except ValueError:
            return Response({"error": "Choose the hospital system and snapshot date for this MRF."}, status=400)
        if not system:
            return Response({"error": "Enter a hospital system key for this MRF."}, status=400)
        target_dir = raw_root / "hospital_mrf" / system / snapshot_date
    elif source_key == "nppes":
        # load_nppes expects the official base name directly under this folder.
        target_dir = raw_root / "NPPES"
    elif source_key == "hospital_enrollments":
        target_dir = raw_root / "Hospital Enrollments" / "uploads"
    else:
        target_dir = raw_root / source_key / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    partial_path = target_dir / f"{file_id}.part"
    digest = hashlib.sha256()
    written = 0
    try:
        with partial_path.open("xb") as dest:
            for chunk in upload.chunks():
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("File exceeds the configured upload size limit.")
                digest.update(chunk)
                dest.write(chunk)
        if extension in {".zip", ".xlsx"}:
            archive_issue = _archive_input_issue(partial_path, config)
            if archive_issue:
                partial_path.unlink(missing_ok=True)
                return Response({"error": archive_issue}, status=400)
        sha = digest.hexdigest()
        duplicate = SourceFile.objects.filter(sha256=sha, source_key=source_key).first()
        if duplicate:
            partial_path.unlink(missing_ok=True)
            return Response({"duplicate": True, "source_file_id": duplicate.pk,
                             "sha256": sha, "relative_path": duplicate.relative_path}, status=200)
        original_path = Path(safe_name)
        final_name = f"{original_path.stem}_{file_id[:8]}{original_path.suffix}"
        final_path = target_dir / final_name
        os.replace(partial_path, final_path)
        relative_path = final_path.relative_to(raw_root).as_posix()
        try:
            raw_prefix = raw_root.resolve().relative_to(settings.BASE_DIR.parent.resolve()).as_posix()
        except ValueError:
            raw_prefix = raw_root.resolve().as_posix()
        record = SourceFile.objects.create(
            source_key=source_key, original_name=Path(upload.name).name[:255],
            relative_path=f"{raw_prefix}/{relative_path}", file_format=extension.lstrip("."),
            sha256=sha, size_bytes=written, status="uploaded",
        )
        AuditEvent.objects.create(actor=request.user, action="source_uploaded", entity_type="source_file",
                                  entity_id=str(record.pk), details={"source_key": source_key, "sha256": sha})
    except ValueError as exc:
        partial_path.unlink(missing_ok=True)
        return Response({"error": str(exc)}, status=413)
    except OSError as exc:
        partial_path.unlink(missing_ok=True)
        logger.exception("Could not store uploaded source file")
        return Response({"error": "Could not store uploaded file. Contact an administrator."}, status=500)
    return Response({"id": record.pk, "source_key": source_key, "relative_path": record.relative_path,
                     "file_format": record.file_format, "size_bytes": record.size_bytes,
                     "sha256": record.sha256, "status": record.status}, status=201)


@api_view(["GET", "POST"])
@permission_classes([CanAnalyze])
def processing_jobs(request):
    if request.method == "POST":
        if not has_any_role(request.user, {ADMIN_GROUP}):
            return Response({"error": "This action requires the Admin role."}, status=403)
        job_type = str(request.data.get("job_type", "")).strip()
        if job_type not in {"refresh_data", "market_report"}:
            return Response({"error": "job_type must be refresh_data or market_report."}, status=400)
        job = ProcessingJob.objects.create(job_type=job_type, requested_by=request.user)
        AuditEvent.objects.create(actor=request.user, action="processing_job_queued", entity_type="job",
                                  entity_id=str(job.pk), details={"job_type": job_type})
        # Start a short-lived worker for this job so an upload can be imported
        # from the UI without requiring a separate worker terminal.
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [sys.executable, "manage.py", "process_jobs", "--once"],
                cwd=settings.BASE_DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=flags,
                start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            job.status = "failed"
            job.error = f"Could not start the data worker: {exc}"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error", "finished_at"])
            AuditEvent.objects.create(actor=request.user, action="processing_job_finished",
                                      entity_type="job", entity_id=str(job.pk),
                                      details={"job_type": job.job_type, "status": "failed"})
            return Response({"error": job.error, "id": job.pk, "status": job.status}, status=503)
        return Response({"id": job.pk, "job_type": job.job_type, "status": job.status,
                         "progress": job.progress}, status=202)
    limit = _bounded_query_int(request, "limit", 50, 1, 200)
    if limit is None:
        return Response({"error": "limit must be a whole number."}, status=400)
    rows = ProcessingJob.objects.order_by("-created_at")[:limit]
    return Response([{
        "id": j.pk, "job_type": j.job_type, "status": j.status, "progress": j.progress,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
        "summary": j.summary, "error": j.error,
    } for j in rows])


@api_view(["GET"])
@permission_classes([CanAnalyze])
def processing_job_detail(request, job_id: int):
    job = get_object_or_404(ProcessingJob, pk=job_id)
    return Response({"id": job.pk, "job_type": job.job_type, "status": job.status,
                     "progress": job.progress, "created_at": job.created_at,
                     "started_at": job.started_at, "finished_at": job.finished_at,
                     "summary": job.summary, "error": job.error})


@api_view(["GET"])
def report_records(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    limit = _bounded_query_int(request, "limit", 50, 1, 200)
    if limit is None:
        return Response({"error": "limit must be a whole number."}, status=400)
    if payload is not None:
        source_hash = data.comparison_sha256()
        report = (ReportRecord.objects.filter(source_hash=source_hash, status="released")
                  .select_related("approved_by").order_by("-generated_at").first())
        if report is None:
            return Response([])
        return Response([{
            "id": report.pk, "name": report.name, "report_type": report.report_type,
            "status": "released", "generated_at": report.generated_at,
            "approved_by": report.approved_by.get_username() if report.approved_by else None,
            "approved_at": report.approved_at,
        }])
    return Response([{
        "id": r.pk, "name": r.name, "report_type": r.report_type, "status": r.status,
        "generated_at": r.generated_at, "source_hash": r.source_hash,
        "config_hash": r.config_hash, "metadata": r.metadata,
        "approved_by": r.approved_by.get_username() if r.approved_by else None,
        "approved_at": r.approved_at,
    } for r in ReportRecord.objects.select_related("approved_by")[:limit]])


REFERENCE_TABLES = {
    "asp": ("asp", "Quarterly CMS ASP payment limits"),
    "crosswalk": ("crosswalk", "CMS NDC to HCPCS crosswalk"),
    "ndc-products": ("ndc_products", "FDA NDC products"),
    "ndc-packages": ("ndc_packages", "FDA NDC packages"),
    "hospitals": ("hospitals_ref", "Ohio CMS hospital catalog"),
    "nadac": ("nadac", "NADAC unit prices"),
    "providers": ("providers", "NPPES provider records"),
    "enrollments": ("enrollments", "CMS hospital enrollments"),
    "partb-spending": ("scope", "CMS Medicare Part B drug spend-ranked scope"),
}


@api_view(["GET"])
@permission_classes([CanAdminister])
def reference_catalog(request):
    """Describe real Parquet reference tables and their loaded coverage."""
    import pyarrow.parquet as parquet

    result = []
    for key, (file_key, label) in REFERENCE_TABLES.items():
        path = data.files()[file_key]
        if not path.is_file():
            result.append({"key": key, "label": label, "status": "missing", "rows": 0,
                           "columns": [], "source_files": [], "source_hashes": [],
                           "periods": [], "path": None})
            continue
        pf = parquet.ParquetFile(path)
        schema = pf.schema_arrow
        columns = schema.names
        try:
            lineage = data.query(
                "SELECT DISTINCT source_file, source_sha256 FROM {table} "
                "WHERE source_file IS NOT NULL ORDER BY source_file LIMIT 100",
                table=file_key)
            source_files = [row["source_file"] for row in lineage]
            source_hashes = sorted({row["source_sha256"] for row in lineage if row.get("source_sha256")})
        except Exception:
            source_files, source_hashes = [], []
        periods = []
        period_col = next((c for c in ("quarter", "spend_year", "reporting_period") if c in columns), None)
        if period_col:
            try:
                periods = [row["period"] for row in data.query(
                    f"SELECT DISTINCT {period_col} AS period FROM {{table}} "
                    f"WHERE {period_col} IS NOT NULL ORDER BY period", table=file_key)]
            except Exception:
                periods = []
        try:
            rel_path = path.relative_to(settings.BASE_DIR.parent).as_posix()
        except ValueError:
            rel_path = path.as_posix()
        result.append({"key": key, "label": label, "status": "loaded", "rows": pf.metadata.num_rows,
                       "columns": columns, "source_files": source_files,
                       "source_hashes": source_hashes, "periods": periods,
                       "path": rel_path})
    return Response(result)


@api_view(["GET"])
@permission_classes([CanAdminister])
def reference_table(request, dataset_name: str):
    """Search and page through an allow-listed analytical Parquet table."""
    import duckdb

    spec = REFERENCE_TABLES.get(dataset_name)
    if spec is None:
        return Response({"error": "Unknown reference table."}, status=404)
    file_key = spec[0]
    path = data.files()[file_key]
    if not path.is_file():
        return Response({"table": dataset_name, "status": "missing", "total": 0,
                         "limit": 100, "offset": 0, "columns": [], "rows": []})
    limit = _bounded_query_int(request, "limit", 100, 1, 500)
    offset = _bounded_query_int(request, "offset", 0, 0, 2_147_483_647)
    if limit is None or offset is None:
        return Response({"error": "limit and offset must be whole numbers."}, status=400)
    con = duckdb.connect()
    try:
        schema = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [path.as_posix()]).fetchall()
        columns = [r[0] for r in schema]
        quote_identifier = lambda name: '"' + str(name).replace('"', '""') + '"'
        search = request.query_params.get("q", "").strip()
        search_cols = [r[0] for r in schema if r[1].upper() in {"VARCHAR", "TEXT"}]
        filters, params = [], []
        if search and search_cols:
            filters.append("(" + " OR ".join(
                f"CAST({quote_identifier(c)} AS VARCHAR) ILIKE ?" for c in search_cols) + ")")
            params.extend([f"%{search}%"] * len(search_cols))
        for field in ("quarter", "hcpcs", "ccn", "state", "ndc11"):
            value = request.query_params.get(field)
            if value and field in columns:
                filters.append(f"CAST({quote_identifier(field)} AS VARCHAR) = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        table_source = "read_parquet(?)"
        total = con.execute(f"SELECT count(*) FROM {table_source}{where}", [path.as_posix(), *params]).fetchone()[0]
        cur = con.execute(
            f"SELECT * FROM {table_source}{where} LIMIT ? OFFSET ?",
            [path.as_posix(), *params, limit, offset])
        row_columns = [item[0] for item in cur.description]
        rows = [dict(zip(row_columns, values)) for values in cur.fetchall()]
        for row in rows:
            for key, value in row.items():
                if hasattr(value, "isoformat"):
                    row[key] = value.isoformat()
                elif hasattr(value, "is_finite"):
                    row[key] = float(value) if value.is_finite() else None
                elif isinstance(value, float) and not __import__("math").isfinite(value):
                    row[key] = None
        return Response({"table": dataset_name, "status": "loaded", "total": total,
                         "limit": limit, "offset": offset, "columns": columns, "rows": rows})
    finally:
        con.close()


@api_view(["GET"])
@permission_classes([CanAdminister])
def drug_scope_status(request):
    from pipeline.common import paths
    scope_path = paths()["ref"] / "drug_scope.parquet"
    try:
        report_config = json.loads((settings.BASE_DIR.parent / "config" / "report.json").read_text(encoding="utf-8"))
        target_count = int(report_config["target_drug_count"])
    except (OSError, ValueError, KeyError, TypeError):
        target_count = None
    try:
        data.require_current_scope()
        scope = data.drug_config()
        info = data.run_info()
        reviews = {row["hcpcs"]: row for row in DrugUnitReview.objects.filter(
            scope_source_sha256=info.get("drug_selection_source_sha256")).values(
                "hcpcs", "status", "notes", "billing_qty", "billing_unit", "reviewed_at",
                "clinical_reviewer_name", "reviewer__username")}
        for drug in scope.values():
            review = reviews.get(drug["hcpcs"])
            if has_any_role(request.user, {ADMIN_GROUP}):
                drug["unit_review"] = review
            else:
                drug.pop("unit_review", None)
                drug.pop("reviewed_by", None)
        return Response({"status": "selected", "source": info.get("drug_selection_source"),
                         "source_file": info.get("drug_selection_source_file"),
                         "source_sha256": info.get("drug_selection_source_sha256"),
                         "spend_year": info.get("drug_selection_year"),
                         "target_count": target_count, "selected_count": len(scope),
                         "drugs": list(scope.values())})
    except data.DataMissing as exc:
        return Response({"status": "blocked", "reason": str(exc), "scope_file_present": scope_path.is_file(),
                         "target_count": target_count, "selected_count": 0, "drugs": []})


@api_view(["POST"])
@permission_classes([CanAnalyze])
def review_drug_unit(request, hcpcs: str):
    """Record an Admin-submitted external clinical review for the exact scope source."""
    from decimal import Decimal, InvalidOperation
    from pipeline.common import parse_hcpcs_dosage, paths

    try:
        scope = data.drug_config()
        info = data.run_info()
    except data.DataMissing as exc:
        return _missing(exc)
    code = hcpcs.upper()
    drug = scope.get(code)
    if not drug:
        return Response({"error": "HCPCS code is not in the current CMS Part B selected scope."}, status=404)
    decision = str(request.data.get("status", "")).strip()
    if decision not in {"validated", "rejected", "unit_unresolved"}:
        return Response({"error": "status must be validated, rejected, or unit_unresolved."}, status=400)
    note = str(request.data.get("notes", "")).strip()[:4000]
    clinical_reviewer_name = str(request.data.get("clinical_reviewer_name", "")).strip()[:160]
    if len(clinical_reviewer_name) < 3:
        return Response({"error": "Enter the external pharmacist or clinical reviewer’s name."}, status=400)
    if len(note) < 10:
        return Response({"error": "Add the reviewer’s evidence and rationale (at least 10 characters)."}, status=400)
    dose = parse_hcpcs_dosage(drug.get("asp_dosage") or "")
    if not dose:
        return Response({"error": "CMS ASP dosage does not provide a verifiable billing unit."}, status=422)
    try:
        quantity = Decimal(str(request.data.get("billing_qty", dose.qty)))
        unit = str(request.data.get("billing_unit", dose.unit)).strip().upper()
    except (InvalidOperation, TypeError, ValueError):
        return Response({"error": "billing_qty must be a numeric value."}, status=400)
    if not quantity.is_finite() or quantity != Decimal(str(dose.qty)) or unit != dose.unit:
        return Response({"error": f"The review must use the CMS ASP dosage {dose.qty:g} {dose.unit}."}, status=400)

    review, _ = DrugUnitReview.objects.update_or_create(
        hcpcs=code, scope_source_sha256=info["drug_selection_source_sha256"],
        defaults={"billing_qty": quantity, "billing_unit": unit, "status": decision,
                  "notes": note, "reviewer": request.user,
                  "clinical_reviewer_name": clinical_reviewer_name},
    )
    AuditEvent.objects.create(actor=request.user, action="drug_unit_reviewed", entity_type="drug",
                              entity_id=code, details={"status": decision,
                              "scope_source_sha256": review.scope_source_sha256})

    # The pipeline remains runnable without Django. Export only scope-bound,
    # reviewer-approved decisions to its explicit input folder.
    review_dir = paths()["raw"] / "unit_reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    export = review_dir / f"app_reviews_{review.scope_source_sha256[:12]}.csv"
    temp = export.with_name(export.name + ".part")
    rows = list(DrugUnitReview.objects.filter(scope_source_sha256=review.scope_source_sha256)
                .select_related("reviewer").order_by("hcpcs"))
    try:
        with temp.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["HCPCS_Cd", "reviewed_by", "recorded_by",
                "billing_unit", "billing_unit_qty", "selection_source_sha256", "review_status", "review_notes"])
            writer.writeheader()
            for row in rows:
                values = {"HCPCS_Cd": row.hcpcs,
                    "reviewed_by": row.clinical_reviewer_name,
                    "recorded_by": row.reviewer.get_username() if row.reviewer else "unknown",
                    "billing_unit": row.billing_unit, "billing_unit_qty": row.billing_qty,
                    "selection_source_sha256": row.scope_source_sha256,
                    "review_status": row.status, "review_notes": row.notes}
                writer.writerow({key: csv_safe_cell(value) for key, value in values.items()})
        os.replace(temp, export)
    finally:
        temp.unlink(missing_ok=True)
    return Response({"hcpcs": review.hcpcs, "status": review.status, "notes": review.notes,
                     "clinical_reviewer_name": review.clinical_reviewer_name,
                     "reviewer": request.user.get_username(), "reviewed_at": review.reviewed_at,
                     "scope_source_sha256": review.scope_source_sha256}, status=200)


@api_view(["GET"])
@permission_classes([CanAdminister])
def unit_validations(request):
    try:
        rows = data.query(
            "SELECT hcpcs, any_value(drug_name) AS drug_name, hospital_key, "
            "any_value(hospital_label) AS hospital_label, any_value(description) AS description, "
            "any_value(price) AS price, any_value(drug_unit) AS drug_unit, "
            "any_value(drug_unit_type) AS drug_unit_type, any_value(billing_units) AS billing_units, "
            "any_value(unit_note) AS unit_note, any_value(asp_payment_limit) AS asp_payment_limit, "
            "any_value(markup_multiple) AS markup_multiple, any_value(status) AS status, "
            "any_value(source_file) AS source_file, any_value(source_sha256) AS source_sha256 "
            "FROM {cmp} WHERE status IN ('unit_unresolved','unit_ambiguous','billing_unit_mismatch','review_range') "
            "GROUP BY hcpcs, hospital_key ORDER BY status, hcpcs, hospital_label LIMIT 2000",
            cmp="comparison")
        return Response({"status": "loaded", "rows": rows, "total": len(rows),
                         "review_workflow": "Admin must record an external clinical reviewer and evidence for each selected drug."})
    except data.DataMissing as exc:
        return Response({"status": "blocked", "reason": str(exc), "rows": [], "total": 0,
                         "review_workflow": "Admin must record an external clinical reviewer and evidence for each selected drug."})


@api_view(["GET"])
@permission_classes([CanAdminister])
def application_settings(request):
    project_dir = settings.BASE_DIR.parent
    try:
        report = json.loads((project_dir / "config" / "report.json").read_text(encoding="utf-8"))
        pipeline = __import__("yaml").safe_load((project_dir / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
        taxonomy = __import__("yaml").safe_load((project_dir / "config" / "hospital_taxonomy.yaml").read_text(encoding="utf-8"))
        taxonomy_codes = __import__("yaml").safe_load((project_dir / "config" / "hospital_taxonomies.yaml").read_text(encoding="utf-8"))
        geography = __import__("yaml").safe_load((project_dir / "config" / "geography.yaml").read_text(encoding="utf-8"))
        units = __import__("yaml").safe_load((project_dir / "config" / "units.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Response({"error": f"Configuration could not be read: {exc}"}, status=503)
    return Response({"report": {"title": report.get("title"), "target_drug_count": report.get("target_drug_count"),
                                 "required_inputs": report.get("required_inputs"),
                                 "supplemental_inputs": report.get("supplemental_inputs")},
                     "comparison": {"review_range": pipeline.get("review_range"),
                                    "benchmark_quarter": pipeline.get("benchmark_quarter")},
                     "hospital_taxonomy": {**taxonomy, "taxonomy_codes": taxonomy_codes.get("primary_taxonomy_codes", []),
                                            "border_zip3": geography.get("include_border_zip3", [])},
                     "units": units,
                     "database_backend": settings.DATABASES["default"]["ENGINE"],
                     "plan_specific_audit": "planned; raw claims remain client-side"})


@api_view(["GET"])
@permission_classes([CanAdminister])
def audit_logs(request):
    limit = _bounded_query_int(request, "limit", 100, 1, 500)
    if limit is None:
        return Response({"error": "limit must be a whole number."}, status=400)
    events = AuditEvent.objects.select_related("actor")[:limit]
    return Response([{
        "id": e.pk, "action": e.action, "actor": e.actor.get_username() if e.actor else None,
        "entity_type": e.entity_type, "entity_id": e.entity_id,
        "details": e.details, "created_at": e.created_at,
    } for e in events])


@api_view(["GET"])
def drugs(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    headline_filter = VIEWER_HEADLINE if payload is not None else HEADLINE
    try:
        cfg = data.drug_config()
        latest = data.query(
            "SELECT hcpcs, quarter, payment_limit, dosage_text FROM {asp} "
            "WHERE hcpcs IN (SELECT unnest(?)) "
            "QUALIFY row_number() OVER (PARTITION BY hcpcs ORDER BY quarter DESC) = 1",
            [list(cfg)], asp="asp")
        spend_rows = data.query(
            "SELECT hcpcs, partb_spending FROM {scope} WHERE hcpcs IN (SELECT unnest(?))",
            [list(cfg)], scope="scope")
        stats = data.query(
            f"""SELECT hcpcs,
                   count(DISTINCT hospital_key) FILTER (WHERE {headline_filter}) AS hospitals_priced,
                   count(*) FILTER (WHERE {headline_filter}) AS rates,
                   median(price_per_billing_unit) FILTER (WHERE {headline_filter}) AS median_hospital_price,
                   median(asp_payment_limit) FILTER (WHERE {headline_filter}) AS asp_payment_limit_used,
                   any_value(benchmark_quarter) FILTER (WHERE {headline_filter}) AS benchmark_quarter_used,
                   median(markup_multiple) FILTER (WHERE {headline_filter}) AS median_markup,
                   min(markup_multiple) FILTER (WHERE {headline_filter}) AS min_markup,
                   max(markup_multiple) FILTER (WHERE {headline_filter}) AS max_markup,
                   count(*) FILTER (WHERE status = 'review_range') AS review_rows,
                   count(*) FILTER (WHERE status = 'unit_unresolved') AS unresolved_unit_rows,
                   count(*) FILTER (WHERE status NOT IN ('ok','review_range')) AS excluded_rows
                FROM {{cmp}} GROUP BY hcpcs""", cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    asp = {r["hcpcs"]: r for r in latest}
    spending = {r["hcpcs"]: r.get("partb_spending") for r in spend_rows}
    st = {r["hcpcs"]: r for r in stats}
    clinical_signoffs = (payload or {}).get("clinical_signoffs", {})
    out = []
    for code, d in cfg.items():
        a, s = asp.get(code, {}), st.get(code, {})
        result = {
            "hcpcs": code, "name": d["name"], "brand": d.get("brand"),
            "billing_unit": f'{d["billing_unit"]["qty"]:g} {d["billing_unit"]["unit"]}',
            "reviewed_by": d.get("reviewed_by"),
            "asp_quarter": a.get("quarter"),
            "asp_payment_limit": a.get("payment_limit"),
            "benchmark_quarter_used": s.get("benchmark_quarter_used") or a.get("quarter"),
            "asp_payment_limit_used": s.get("asp_payment_limit_used") or a.get("payment_limit"),
            "asp_dosage": a.get("dosage_text"),
            "median_hospital_price": s.get("median_hospital_price"),
            "hospitals_priced": s.get("hospitals_priced", 0), "rates": s.get("rates", 0),
            "median_markup": s.get("median_markup"), "min_markup": s.get("min_markup"),
            "max_markup": s.get("max_markup"), "review_rows": s.get("review_rows", 0),
            "unresolved_unit_rows": s.get("unresolved_unit_rows", 0),
            "excluded_rows": s.get("excluded_rows", 0),
        }
        result["partb_spending_proxy"] = spending.get(code)
        if result["partb_spending_proxy"] is not None and s.get("median_markup") is not None:
            result["estimated_dollars_at_stake_proxy"] = max(
                0, (float(s["median_markup"]) - 1) * float(result["partb_spending_proxy"]))
        else:
            result["estimated_dollars_at_stake_proxy"] = None
        if payload is not None:
            result.pop("reviewed_by", None)
            result.pop("review_rows", None)
            result.pop("unresolved_unit_rows", None)
            result.pop("excluded_rows", None)
            clinical = clinical_signoffs.get(code)
            result["verification_status"] = "verified" if clinical else "pending clinical review"
            result["clinical_reviewer_name"] = clinical.get("reviewer_name") if clinical else None
            result["clinical_reviewed_at"] = clinical.get("reviewed_at") if clinical else None
        out.append(result)
    return Response(out)


@api_view(["GET"])
def drug_detail(request, hcpcs: str):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    headline_filter = VIEWER_HEADLINE if payload is not None else HEADLINE
    try:
        cfg = data.drug_config()
        run = data.run_info()
    except data.DataMissing as e:
        return _missing(e)
    code = hcpcs.upper()
    if code not in cfg:
        return Response({"error": f"{code} is not in the CMS Part B selected scope."}, status=404)
    if payload is not None and code not in (payload.get("drug_codes") or []):
        return Response({"error": "This drug is not included in the current released report."}, status=404)
    try:
        asp_columns = ("quarter, payment_limit, dosage_text, short_description" if payload is not None else
                       "quarter, payment_limit, dosage_text, short_description, source_file, source_sha256")
        asp = data.query(f"SELECT {asp_columns} FROM {{asp}} WHERE hcpcs = ? ORDER BY quarter",
                         [code], asp="asp")
        hospitals = data.query(
            f"""SELECT hospital_key, any_value(hospital_label) AS hospital_label,
                   any_value(system) AS system,
                   count(*) AS rates, count(DISTINCT payer_group) AS payer_groups,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup,
                   median(price_per_billing_unit) AS median_price_per_unit,
                   any_value(asp_payment_limit) AS asp_payment_limit,
                   any_value(benchmark_quarter) AS benchmark_quarter
                FROM {{cmp}} WHERE hcpcs = ? AND {headline_filter}
                GROUP BY hospital_key ORDER BY median_markup DESC""", [code], cmp="comparison")
        payers = data.query(
            f"""SELECT payer_group, count(*) AS rates, count(DISTINCT hospital_key) AS hospitals,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup
                FROM {{cmp}} WHERE hcpcs = ? AND {headline_filter}
                GROUP BY 1 ORDER BY median_markup DESC""", [code], cmp="comparison")
        statuses = ([] if payload is not None else data.query(
            "SELECT status, count(*) AS n FROM {cmp} WHERE hcpcs = ? "
            "GROUP BY 1 ORDER BY 2 DESC", [code], cmp="comparison"))
    except data.DataMissing as e:
        return _missing(e)
    d = cfg[code]
    result = {
        "hcpcs": code, "name": d["name"], "brand": d.get("brand"),
        "billing_unit": f'{d["billing_unit"]["qty"]:g} {d["billing_unit"]["unit"]}',
        "reviewed_by": d.get("reviewed_by"),
        "asp": asp, "hospitals": hospitals, "payers": payers, "statuses": statuses,
    }
    if payload is not None:
        clinical = (payload.get("clinical_signoffs") or {}).get(code)
        result["clinical_reviewer_name"] = clinical.get("reviewer_name") if clinical else None
        result["clinical_reviewed_at"] = clinical.get("reviewed_at") if clinical else None
        result["verification_status"] = "verified" if clinical else "pending clinical review"
        result.pop("reviewed_by", None)
    else:
        clinical = DrugUnitReview.objects.filter(
            hcpcs=code, scope_source_sha256=run.get("drug_selection_source_sha256")
        ).first()
        result["clinical_reviewer_name"] = clinical.clinical_reviewer_name if clinical else None
        result["clinical_reviewed_at"] = clinical.reviewed_at.isoformat() if clinical else None
        result["verification_status"] = clinical.status if clinical else "pending clinical review"
    return Response(result)


def _hospital_file_key(system: str, source_file: str, source_member: str) -> str:
    raw = f"{system}|{source_file}|{source_member}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:10]


def _hospital_quality_fields(row: dict) -> dict:
    drug_rows = row.get("drug_rows") or 0
    error = row.get("error")
    return {
        "source_file": row.get("source_file"),
        "source_member": row.get("source_member"),
        "source_sha256": row.get("source_sha256"),
        "items_scanned": row.get("items_scanned") or 0,
        "drug_rows": drug_rows,
        "hcpcs_found": row.get("hcpcs_found") or "",
        "file_error": error,
        "file_status": "parse_error" if error else "rates_found" if drug_rows else "no_selected_drug_rows",
        "cms_version": row.get("cms_version"),
    }


@api_view(["GET"])
def hospitals(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    headline_filter = VIEWER_HEADLINE if payload is not None else HEADLINE
    review_counts = ("0 AS review_rows, 0 AS excluded_rows" if payload is not None else
                     "count(*) FILTER (WHERE status = 'review_range') AS review_rows, "
                     "count(*) FILTER (WHERE status NOT IN ('ok','review_range')) AS excluded_rows")
    try:
        rows = data.query(
            f"""SELECT hospital_key, any_value(hospital_label) AS hospital_label,
                   any_value(system) AS system, any_value(locations) AS locations,
                   any_value(file_last_updated) AS file_last_updated,
                   count(DISTINCT hcpcs) FILTER (WHERE {headline_filter}) AS drugs_priced,
                   count(*) FILTER (WHERE {headline_filter}) AS rates,
                   median(markup_multiple) FILTER (WHERE {headline_filter}) AS median_markup,
                   max(markup_multiple) FILTER (WHERE {headline_filter}) AS max_markup,
                   {review_counts}
                FROM {{cmp}} GROUP BY hospital_key
                HAVING count(*) FILTER (WHERE {headline_filter}) > 0
                ORDER BY median_markup DESC NULLS LAST""", cmp="comparison")
        if payload is not None:
            for row in rows:
                row["file_status"] = "rates_found"
            return Response(rows)
        quality_rows = data.query("SELECT * FROM {quality} ORDER BY system, source_file, source_member",
                                  quality="quality")
    except data.DataMissing as e:
        return _missing(e)
    quality_by_key = {
        _hospital_file_key(row.get("system") or "", row.get("source_file") or "",
                           row.get("source_member") or ""): row
        for row in quality_rows
    }
    result = []
    seen = set()
    for row in rows:
        hospital_key = row["hospital_key"]
        quality_row = quality_by_key.get(hospital_key)
        if quality_row:
            row.update(_hospital_quality_fields(quality_row))
            seen.add(hospital_key)
        else:
            row["file_status"] = "comparison_only"
        result.append(row)
    for quality_row in quality_rows:
        hospital_key = _hospital_file_key(quality_row.get("system") or "",
                                          quality_row.get("source_file") or "",
                                          quality_row.get("source_member") or "")
        if hospital_key in seen:
            continue
        label = (quality_row.get("hospital_name") or quality_row.get("locations") or
                 Path(quality_row.get("source_member") or quality_row.get("source_file") or "Unknown file").stem)
        result.append({
            "hospital_key": hospital_key,
            "hospital_label": label,
            "system": quality_row.get("system"),
            "locations": quality_row.get("locations"),
            "file_last_updated": quality_row.get("file_last_updated"),
            "drugs_priced": 0,
            "rates": 0,
            "median_markup": None,
            "max_markup": None,
            "review_rows": 0,
            "excluded_rows": 0,
            **_hospital_quality_fields(quality_row),
        })
        seen.add(hospital_key)
    result.sort(key=lambda r: (r["median_markup"] is None,
                               -(r["median_markup"] or 0),
                               (r["hospital_label"] or "").casefold()))
    return Response(result)


@api_view(["GET"])
def hospital_detail(request, hospital_key: str):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    headline_filter = VIEWER_HEADLINE if payload is not None else HEADLINE
    try:
        drugs_ = data.query(
            f"""SELECT hcpcs, any_value(drug_name) AS drug_name, count(*) AS rates,
                   median(markup_multiple) AS median_markup,
                   min(markup_multiple) AS min_markup, max(markup_multiple) AS max_markup,
                   any_value(asp_payment_limit) AS asp_payment_limit,
                   median(price_per_billing_unit) AS median_price_per_unit
                FROM {{cmp}} WHERE hospital_key = ? AND {headline_filter}
                GROUP BY hcpcs ORDER BY median_markup DESC""", [hospital_key], cmp="comparison")
        if payload is not None:
            info = data.query("SELECT any_value(hospital_label) AS hospital_label, "
                              "any_value(system) AS system, any_value(locations) AS locations, "
                              "any_value(file_last_updated) AS file_last_updated, count(*) AS n_rows "
                              "FROM {cmp} WHERE hospital_key = ? AND " + headline_filter,
                              [hospital_key], cmp="comparison")
            statuses, quality_rows = [], []
        else:
            info = data.query("SELECT any_value(hospital_label) AS hospital_label, "
                              "any_value(system) AS system, any_value(locations) AS locations, "
                              "any_value(file_last_updated) AS file_last_updated, "
                              "any_value(source_file) AS source_file, "
                              "any_value(source_sha256) AS source_sha256, "
                              "count(*) AS n_rows FROM {cmp} WHERE hospital_key = ?",
                              [hospital_key], cmp="comparison")
            statuses = data.query("SELECT status, count(*) AS n FROM {cmp} WHERE hospital_key = ? "
                                  "GROUP BY 1 ORDER BY 2 DESC", [hospital_key], cmp="comparison")
            quality_rows = data.query("SELECT * FROM {quality}", quality="quality")
    except data.DataMissing as e:
        return _missing(e)
    if not info or not info[0]["n_rows"]:
        quality_row = next((row for row in quality_rows
                            if _hospital_file_key(row.get("system") or "", row.get("source_file") or "",
                                                  row.get("source_member") or "") == hospital_key), None)
        if not quality_row:
            return Response({"error": "hospital not found"}, status=404)
        return Response({
            "hospital_label": (quality_row.get("hospital_name") or quality_row.get("locations") or
                               Path(quality_row.get("source_member") or "Unknown file").stem),
            "system": quality_row.get("system"),
            "locations": quality_row.get("locations"),
            "file_last_updated": quality_row.get("file_last_updated"),
            "source_sha256": quality_row.get("source_sha256"),
            "source_file": quality_row.get("source_file"),
            "source_member": quality_row.get("source_member"),
            "hospital_key": hospital_key,
            "n_rows": 0,
            "drugs": [],
            "statuses": [],
            **_hospital_quality_fields(quality_row),
        })
    result = {**info[0], "hospital_key": hospital_key, "drugs": drugs_, "statuses": statuses}
    if payload is not None:
        result.pop("n_rows", None)
        result["rates"] = sum(row.get("rates", 0) for row in drugs_)
    return Response(result)


def _rate_filters(request) -> tuple[str, list]:
    where, params = [], []
    for field in ("hcpcs", "hospital_key", "payer_group", "price_type", "status", "system"):
        v = request.GET.get(field)
        if v:
            vals = v.split(",")
            where.append(f"{field} IN (SELECT unnest(?))")
            params.append(vals)
    q = request.GET.get("q")
    if q:
        where.append("(hospital_label ILIKE ? OR payer_name ILIKE ? OR plan_name ILIKE ? "
                     "OR description ILIKE ?)")
        params += [f"%{q}%"] * 4
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _comparison_column_names() -> set[str]:
    """Read the Parquet schema so older verified snapshots remain readable."""
    import duckdb

    global _RATE_SCHEMA_CACHE
    path = data.files()["comparison"]
    stat = path.stat()
    cache = _RATE_SCHEMA_CACHE
    if cache and cache[:3] == (str(path), stat.st_size, stat.st_mtime_ns):
        return cache[3]
    connection = duckdb.connect()
    try:
        columns = {row[0] for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [path.as_posix()]).fetchall()}
    finally:
        connection.close()
    _RATE_SCHEMA_CACHE = (str(path), stat.st_size, stat.st_mtime_ns, columns)
    return columns


def _authorized_rate_filters(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return None, None, None, denied
    where, params = _rate_filters(request)
    permitted = RATE_COLUMNS if payload is None else VIEWER_RATE_COLUMNS
    try:
        available = _comparison_column_names()
    except (OSError, RuntimeError, data.DataMissing) as exc:
        return payload, None, None, Response({"error": str(exc)}, status=503)
    columns = [column for column in permitted if column in available]
    if payload is not None:
        fixed = ("coalesce(reviewed, false) AND status NOT IN "
                 "('unit_unresolved','unit_ambiguous','billing_unit_mismatch') "
                 "AND hcpcs IN (SELECT unnest(?))")
        where = f"{where} AND {fixed}" if where else f"WHERE {fixed}"
        params.append(payload.get("drug_codes") or [])
    return payload, where, params, columns


@api_view(["GET"])
def rates(request):
    payload, where, params, columns = _authorized_rate_filters(request)
    if isinstance(columns, Response):
        return columns
    sort = request.GET.get("sort", "markup_multiple")
    sort = sort if sort in SORTABLE else "markup_multiple"
    order = "ASC" if request.GET.get("order") == "asc" else "DESC"
    try:
        limit = max(1, min(int(request.GET.get("limit", 100)), 1000))
        offset = max(int(request.GET.get("offset", 0)), 0)
    except (TypeError, ValueError):
        return Response({"error": "limit and offset must be whole numbers."}, status=400)
    cols = ", ".join(columns)
    try:
        total = data.query(f"SELECT count(*) AS n FROM {{cmp}} {where}", params,
                           cmp="comparison")[0]["n"]
        rows = data.query(f"SELECT {cols} FROM {{cmp}} {where} "
                          f"ORDER BY {sort} {order} NULLS LAST LIMIT {limit} OFFSET {offset}",
                          params, cmp="comparison")
    except data.DataMissing as e:
        return _missing(e)
    return Response({"total": total, "limit": limit, "offset": offset, "rows": rows})


@api_view(["GET"])
def rates_csv(request):
    payload, where, params, columns = _authorized_rate_filters(request)
    if isinstance(columns, Response):
        return columns
    try:
        rows = data.query(f"SELECT {', '.join(columns)} FROM {{cmp}} {where} "
                          "ORDER BY hcpcs, markup_multiple DESC NULLS LAST", params,
                          cmp="comparison")
        info = data.run_info()
    except data.DataMissing as e:
        return _missing(e)
    buf = io.StringIO()
    buf.write(f"# Infusion Drug Markup Audit export. Pipeline run {info['generated_at']}. "
              "Markup = price per HCPCS billing unit / CMS ASP payment limit (ASP+6%).\n")
    w = csv.DictWriter(buf, fieldnames=columns)
    w.writeheader()
    w.writerows({column: csv_safe_cell(row.get(column)) for column in columns} for row in rows)
    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="infusion_audit_report_appendix.csv"'
    return resp


@api_view(["GET"])
@permission_classes([CanAdminister])
def rates_xlsx(request):
    """Stream a filtered comparison export without building a Python row list."""
    import duckdb
    from openpyxl import Workbook

    payload, where, params, columns = _authorized_rate_filters(request)
    if isinstance(columns, Response):
        return columns
    try:
        data.require_current_scope()
        path = data.files()["comparison"]
        con = duckdb.connect()
        try:
            total = con.execute(f"SELECT count(*) FROM read_parquet(?) {where}",
                                [path.as_posix(), *params]).fetchone()[0]
            if total > 1_048_575:
                return Response({"error": "This result exceeds Excel's worksheet row limit; narrow the filters."},
                                status=413)
            cursor = con.execute(
                f"SELECT {', '.join(columns)} FROM read_parquet(?) {where} "
                "ORDER BY hcpcs, markup_multiple DESC NULLS LAST",
                [path.as_posix(), *params])
            output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("Comparisons")
            sheet.append(columns)
            while batch := cursor.fetchmany(2000):
                for row in batch:
                    sheet.append([("'" + value if isinstance(value, str) and
                                   value[:1] in {"=", "+", "-", "@"} else value)
                                  for value in row])
            workbook.save(output)
            output.seek(0)
        finally:
            con.close()
    except data.DataMissing as exc:
        return _missing(exc)
    response = FileResponse(output, as_attachment=True, filename="infusion_audit_comparisons.xlsx",
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["X-Export-Records"] = str(total)
    return response


@api_view(["GET"])
@permission_classes([CanAdminister])
def quality(request):
    try:
        rows = data.query("SELECT * FROM {quality} ORDER BY system, source_file", quality="quality")
    except data.DataMissing as e:
        return _missing(e)
    return Response(rows)


@api_view(["GET"])
def report_pdf(request):
    payload, denied = _viewer_release_payload(request)
    if denied:
        return denied
    from .auth_views import signoff_status
    from .report import build_pdf
    codes = [c.strip().upper() for c in request.GET.get("hcpcs", "").split(",") if c.strip()]
    try:
        status = signoff_status()
        pdf = build_pdf(status, codes or None,
                        user=request.user.get_full_name() or request.user.username)
    except data.DataMissing as e:
        return _missing(e)
    except RuntimeError as e:
        return Response({"error": str(e)}, status=503)
    if payload is not None and not status["signed"]:
        return Response({"error": "Only a current released report is available to Viewers."}, status=403)
    tag = "RELEASED" if status["signed"] else "DRAFT"
    name = f"ohio_infusion_markup_report_{status['generated_at'][:10]}_{tag}.pdf"
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp
