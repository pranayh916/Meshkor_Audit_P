"""Inspect Parquet footers and reconcile the saved comparison row count."""
import json

import pyarrow.parquet as pq
from django.core.management.base import BaseCommand, CommandError

from pipeline.common import paths
from pricing.data import files


class Command(BaseCommand):
    help = "Validate Parquet readability, schemas, and the comparison row count."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Fail if core outputs are missing.")

    def handle(self, *args, **options):
        p = paths()
        candidates = sorted({f for folder in (p["mart"], p["ref"], p["hpt_norm"])
                             if folder.exists() for f in folder.rglob("*.parquet")
                             if not f.name.endswith(".incomplete.parquet")})
        errors = []
        row_counts = {}
        for path in candidates:
            try:
                parquet_file = pq.ParquetFile(path)
                if not parquet_file.schema_arrow.names:
                    raise ValueError("no columns in schema")
                row_counts[path.resolve()] = parquet_file.metadata.num_rows
                self.stdout.write(f"OK  {path}  rows={parquet_file.metadata.num_rows}  columns={len(parquet_file.schema_arrow.names)}")
            except Exception as exc:
                errors.append(f"{path}: {type(exc).__name__}: {exc}")

        core = files()
        for name in ("comparison", "scope"):
            if not core[name].is_file():
                errors.append(f"Missing required output: {core[name]}")
        info_path = core["run_info"]
        if info_path.is_file() and core["comparison"].resolve() in row_counts:
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                expected = info.get("rows")
                actual = row_counts[core["comparison"].resolve()]
                if expected is not None and expected != actual:
                    errors.append(f"Comparison row count mismatch: run_info={expected}, Parquet={actual}")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"Invalid run metadata {info_path}: {exc}")
        elif options["strict"]:
            errors.append(f"Missing comparison metadata: {info_path}")

        self.stdout.write(f"Inspected {len(candidates)} Parquet files.")
        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError(f"Parquet validation found {len(errors)} issue(s).")
        self.stdout.write(self.style.SUCCESS("Parquet validation passed."))
