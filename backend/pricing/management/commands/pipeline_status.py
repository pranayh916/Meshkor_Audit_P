"""Summarize source inventory, analytical outputs, and recent application jobs."""
import json

from django.core.management.base import BaseCommand

from pipeline.common import paths
from pricing.data import files
from pricing.models import ProcessingJob


class Command(BaseCommand):
    help = "Show local pipeline output status and recent persisted jobs."

    def handle(self, *args, **options):
        p = paths()
        outputs = {}
        for name, path in files().items():
            outputs[name] = {"path": path.as_posix(), "exists": path.is_file(),
                             "size_bytes": path.stat().st_size if path.is_file() else 0}
        report = {"raw_file_count": sum(1 for f in p["raw"].rglob("*") if f.is_file()) if p["raw"].exists() else 0,
                  "outputs": outputs}
        try:
            report["recent_jobs"] = list(ProcessingJob.objects.order_by("-created_at").values(
                "id", "job_type", "status", "progress", "created_at", "finished_at")[:10])
        except Exception as exc:
            report["recent_jobs_error"] = f"Operational database unavailable ({type(exc).__name__})."
        self.stdout.write(json.dumps(report, indent=2, default=str))
