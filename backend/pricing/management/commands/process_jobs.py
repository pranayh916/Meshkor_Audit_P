"""Background worker for queued local data and report jobs.

Run: python manage.py process_jobs
Use --once to process at most one queued job and exit.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from pricing import data as analytics_data
from pricing.models import AuditEvent, ProcessingJob, ReportRecord, SourceFile


def _mark_parquet_converted(project: Path) -> int:
    """Mark uploads converted only when their checksum appears in a Parquet artifact."""
    import polars as pl

    artifacts = [
        project / "data" / "ref" / name for name in (
            "ref_asp.parquet", "ref_crosswalk.parquet", "ref_ndc_products.parquet",
            "ref_ndc_packages.parquet", "ref_nadac.parquet", "ref_providers.parquet",
            "ref_enrollments.parquet", "ref_hospitals.parquet", "drug_scope.parquet",
        )
    ] + [
        project / "data" / "hpt" / "norm" / name for name in (
            "hpt_drug_rates.parquet", "hpt_file_quality.parquet",
        )
    ] + [project / "data" / "mart" / "comparison.parquet"]

    hashes: set[str] = set()
    failed_hashes: set[str] = set()
    for path in artifacts:
        if not path.is_file():
            continue
        frame = pl.scan_parquet(path)
        columns = frame.collect_schema().names()
        for column in ("source_sha256", "unit_review_sha256"):
            if column in columns:
                hashes.update(frame.select(pl.col(column).drop_nulls().unique())
                              .collect().to_series().to_list())

    quality_path = project / "data" / "hpt" / "norm" / "hpt_file_quality.parquet"
    if quality_path.is_file():
        quality = pl.scan_parquet(quality_path)
        columns = quality.collect_schema().names()
        if {"source_sha256", "error"} <= set(columns):
            failed_hashes.update(
                quality.filter(pl.col("error").is_not_null())
                .select(pl.col("source_sha256").drop_nulls().unique())
                .collect().to_series().to_list()
            )

    converted = hashes - failed_hashes
    if not converted:
        return 0
    return SourceFile.objects.filter(status="uploaded", sha256__in=converted).update(status="converted")


class Command(BaseCommand):
    help = "Process queued data refresh and market report jobs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one job and exit.")
        parser.add_argument("--poll-interval", type=float, default=2.0)

    def handle(self, *args, **options):
        once, delay = options["once"], max(0.25, options["poll_interval"])
        while True:
            job = self._claim()
            if job:
                self._process(job)
                if once:
                    return
            elif once:
                self.stdout.write("No queued jobs.")
                return
            else:
                time.sleep(delay)

    def _claim(self):
        with transaction.atomic():
            job = (ProcessingJob.objects.select_for_update()
                   .filter(status="queued").order_by("created_at").first())
            if not job:
                return None
            job.status = "running"
            job.progress = 1
            job.started_at = timezone.now()
            job.save(update_fields=["status", "progress", "started_at"])
            return job

    def _run(self, job, args, progress, tail):
        project = Path(__file__).resolve().parents[4]
        process = subprocess.Popen(
            [sys.executable, "-u", *args], cwd=project,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
        )
        for line in process.stdout:
            clean = line.rstrip()
            tail.append(clean)
            if len(tail) > 300:
                del tail[:100]
            if clean.startswith("==="):
                job.progress = min(progress + 5, 90)
                job.save(update_fields=["progress"])
        return process.wait()

    def _process(self, job):
        project = Path(__file__).resolve().parents[4]
        tail = []
        success = True
        try:
            if job.job_type == "refresh_data":
                code = self._run(job, ["-m", "pipeline.run_all"], 10, tail)
                if code:
                    success = False
                job.progress = 90
                job.save(update_fields=["progress"])
                report_code = self._run(job, ["build_market_report.py"], 90, tail)
                success = success and report_code == 0
            elif job.job_type == "market_report":
                code = self._run(job, ["build_market_report.py"], 15, tail)
                success = code == 0
            else:
                raise ValueError(f"Unsupported queued job type: {job.job_type}")

            dashboard = project / "reports" / "dashboard_data.json"
            if dashboard.is_file():
                dashboard_bytes = dashboard.read_bytes()
                dashboard_payload = json.loads(dashboard_bytes)
                source_hash = analytics_data.comparison_sha256()
                config_hash = analytics_data.config_sha256()
                record = (ReportRecord.objects.filter(source_hash=source_hash, config_hash=config_hash)
                          .order_by("-generated_at").first())
                defaults = {
                    "name": f"Ohio market report {timezone.localdate().isoformat()}",
                    "report_type": "ohio_market",
                    "status": "generated" if success and not dashboard_payload.get("draft", True) else "draft",
                    "output_path": "reports/ohio_market_report_draft.md",
                    "built_by": job.requested_by,
                    "metadata": {"job_id": job.pk, "job_type": job.job_type,
                                 "pipeline_success": success,
                                 "dashboard_sha256": hashlib.sha256(dashboard_bytes).hexdigest(),
                                 "draft_reasons": dashboard_payload.get("draft_reasons", {})},
                }
                if record is None:
                    record = ReportRecord.objects.create(source_hash=source_hash,
                                                         config_hash=config_hash, **defaults)
                elif record.status != "released":
                    for field, value in defaults.items():
                        setattr(record, field, value)
                    record.save(update_fields=[*defaults.keys()])
                job.summary = {"report_id": record.pk}
            if success:
                converted_count = _mark_parquet_converted(project)
                job.summary = {**(job.summary or {}),
                               "parquet_converted_sources": converted_count}
                job.status, job.progress, job.error = "succeeded", 100, ""
            else:
                job.status, job.error = "failed", "\n".join(tail[-100:])[-12000:]
        except Exception as exc:
            success = False
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}\n" + "\n".join(tail[-100:])[-12000:]
        job.finished_at = timezone.now()
        job.summary = {**(job.summary or {}), "output_tail": "\n".join(tail[-60:])[-8000:]}
        job.save(update_fields=["status", "progress", "error", "summary", "finished_at"])
        AuditEvent.objects.create(actor=job.requested_by, action="processing_job_finished",
                                  entity_type="job", entity_id=str(job.pk),
                                  details={"job_type": job.job_type, "status": job.status})
        self.stdout.write(f"Job {job.pk} {job.status} ({job.job_type})")
