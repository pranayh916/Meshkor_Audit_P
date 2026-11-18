import argparse
import csv
import json
import hashlib
import math
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .export.summary_export import export_summary
from .logging.secure_logger import configure_secure_logger
from .processing.aggregate_claims import aggregate_claims
from .processing.resolve_adjustments import resolve_claims
from .readers import read_claims
from .validation.claims_validator import (
    HCPCS_PATTERN, OPTIONAL_FIELDS, REQUIRED_FIELDS, claim_chain_context,
    normalize_header, validate_claim,
)


logger = configure_secure_logger()
CLAIM_LIMIT = 1_000_000
INPUT_SIZE_LIMIT = 256 * 1024 * 1024
SCHEMA_VERSION = "1.0"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Process claims locally and export approved aggregates only."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="Validate and aggregate claims locally")
    extract.add_argument("--claims", required=True, type=Path)
    extract.add_argument("--config", default=Path("config/client_config.yaml"), type=Path)
    extract.add_argument("--output", default=Path("output"), type=Path)
    args = parser.parse_args(argv)
    if args.command == "extract":
        return extract_claims(args)
    return 2


def extract_claims(args):
    try:
        config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.error("The local configuration could not be read: %s", exc)
        return 2
    if not isinstance(config, dict):
        logger.error("The local configuration must be a YAML object.")
        return 2
    plan_id = str(config.get("plan_id", "")).strip()
    plan_reference = str(config.get("plan_reference", "")).strip()
    if (not plan_id or not plan_reference
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}", plan_reference)):
        logger.error("Set plan_id and a safe plan_reference in the local client configuration.")
        return 2
    schema_version = str(config.get("schema_version", SCHEMA_VERSION)).strip()
    if schema_version != SCHEMA_VERSION:
        logger.error("This extractor supports schema_version %s.", SCHEMA_VERSION)
        return 2
    column_mapping = config.get("column_mapping") or {}
    if (not isinstance(column_mapping, dict)
            or any(field not in REQUIRED_FIELDS | OPTIONAL_FIELDS
                   or not isinstance(source, str) or not source.strip()
                   for field, source in column_mapping.items())
            or len({normalize_header(column_mapping.get(field, field))
                    for field in REQUIRED_FIELDS | (OPTIONAL_FIELDS & set(column_mapping))})
            != len(REQUIRED_FIELDS) + len(OPTIONAL_FIELDS & set(column_mapping))):
        logger.error("column_mapping must map unique source column names to supported canonical fields.")
        return 2
    billing_units = config.get("hcpcs_billing_units") or {}
    if not isinstance(billing_units, dict):
        logger.error("hcpcs_billing_units must be a mapping sourced from a verified CMS scope.")
        return 2
    normalized_billing_units = {}
    for code, unit in billing_units.items():
        normalized_code = str(code).strip().upper()
        if (not HCPCS_PATTERN.fullmatch(normalized_code) or not isinstance(unit, dict)
                or normalized_code in normalized_billing_units):
            logger.error("A configured billing unit has an invalid code or structure.")
            return 2
        try:
            quantity = float(unit.get("qty"))
        except (TypeError, ValueError):
            logger.error("A configured billing unit quantity is invalid.")
            return 2
        if (not math.isfinite(quantity) or quantity <= 0
                or not str(unit.get("unit", "")).strip()):
            logger.error("A configured billing unit quantity and unit are required.")
            return 2
        if (unit.get("verification_status") != "validated"
                or not str(unit.get("source_reference", "")).strip()
                or not re.fullmatch(r"[0-9a-fA-F]{64}", str(unit.get("source_sha256", "")))):
            logger.error("Every billing unit needs validated status, a source reference, and a SHA-256 checksum.")
            return 2
        normalized_billing_units[normalized_code] = unit
    billing_units = normalized_billing_units

    try:
        if not args.claims.is_file() or args.claims.stat().st_size > INPUT_SIZE_LIMIT:
            raise ValueError("Claims input is missing or exceeds the 256 MiB local safety limit.")
        source_sha256 = _sha256_file(args.claims)
    except OSError as exc:
        logger.error("Claims input could not be inspected: %s", exc)
        return 2

    _archive_previous_export(args.output)

    claims, errors, fingerprints, quarantined = [], [], set(), []
    input_count = duplicate_count = invalid_count = 0
    try:
        for source_row, source in read_claims(args.claims, column_mapping):
            input_count += 1
            if input_count > CLAIM_LIMIT:
                raise ValueError(f"Input exceeds the {CLAIM_LIMIT:,}-record safety limit.")
            try:
                normalized_source = _map_source_columns(source, column_mapping)
                context = claim_chain_context(normalized_source, source_row)
                try:
                    claim = validate_claim(normalized_source, source_row)
                except (ValueError, TypeError):
                    if context:
                        quarantined.append(context)
                    raise
                if claim["plan_id"] != plan_id:
                    if context:
                        quarantined.append(context)
                    raise ValueError("plan_id does not match the configured local plan")
                fingerprint = _record_fingerprint(claim)
                if fingerprint in fingerprints:
                    duplicate_count += 1
                    if claim["claim_status"] in {"adjusted", "reversed"}:
                        quarantined.append(context)
                    errors.append({"row": source_row, "category": "duplicate_exact_record",
                                   "reason": "Exact duplicate excluded."})
                    continue
                fingerprints.add(fingerprint)
                claims.append(claim)
            except (ValueError, TypeError) as exc:
                invalid_count += 1
                errors.append({"row": source_row, "category": "invalid_record",
                               "reason": str(exc)})
    except (OSError, ValueError, NotImplementedError, csv.Error) as exc:
        logger.error("Claims input could not be processed: %s", exc)
        return 2

    quality = {
        "total_input_records": input_count, "valid_records": len(claims),
        "invalid_records": invalid_count, "duplicate_records": duplicate_count,
        "adjusted_records": 0, "reversed_records": 0, "excluded_records": invalid_count + duplicate_count,
        "reasons": {},
    }
    for error in errors:
        quality["reasons"][error["category"]] = quality["reasons"].get(error["category"], 0) + 1
    adjudicated = resolve_claims(claims, quality, quarantined=quarantined)
    dates = [claim["service_date"] for claim in claims]
    source_period = f"{min(dates).isoformat()}/{max(dates).isoformat()}" if dates else ""
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary, privacy_quality = aggregate_claims(
        adjudicated, plan_reference=plan_reference, source_period=source_period,
        extracted_at=extracted_at, billing_units=billing_units,
    )
    for reason, count in privacy_quality["reasons"].items():
        quality["reasons"][reason] = quality["reasons"].get(reason, 0) + count
    quality["excluded_records"] += privacy_quality["excluded_records"]
    quality["suppressed_aggregate_cells"] = privacy_quality["suppressed_aggregate_cells"]
    quality["rejected_aggregate_cells"] = privacy_quality["rejected_aggregate_cells"]
    quality["excluded_aggregate_cells"] = privacy_quality["excluded_aggregate_cells"]
    quality["aggregate_cell_reasons"] = privacy_quality["aggregate_cell_reasons"]
    quality["exported_aggregate_rows"] = len(summary)
    quality["schema_version"] = SCHEMA_VERSION
    _write_quality(args.output, quality, errors)
    if not summary:
        logger.error("No aggregates passed adjudication, unit, and privacy controls; no summary was exported.")
        return 1
    provenance = {
        "source_sha256": source_sha256,
        "source_format": args.claims.suffix.casefold().lstrip("."),
        "input_records": input_count,
        "source_period": source_period,
        "plan_reference": plan_reference,
    }
    destination, manifest, digest = export_summary(
        summary, args.output, source_provenance=provenance
    )
    logger.info("Created %s (%d approved aggregate rows; SHA-256 %s)",
                destination, len(summary), digest)
    logger.info("Local data-quality report: %s", args.output / "data_quality.json")
    logger.info("Manifest: %s. Raw claims remain in the client environment.", manifest)
    return 0


def _record_fingerprint(claim):
    fields = sorted(REQUIRED_FIELDS | {"adjustment_reference", "reversal_reference", "service_setting"})
    return tuple(str(claim.get(field, "")) for field in fields)


def _archive_previous_export(output):
    """Keep prior approved exports, but never leave one looking current after a new run starts."""
    output = Path(output)
    export_names = ("claims_summary.csv", "manifest.json")
    existing = [output / name for name in export_names if (output / name).exists()]
    if not existing:
        return
    archive = output / "history" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    archive.mkdir(parents=True, exist_ok=False)
    for path in existing:
        os.replace(path, archive / path.name)
    logger.info("Previous approved export archived at %s", archive)


def _map_source_columns(row, column_mapping):
    if row.get("__extra_columns__"):
        return row
    by_normalized_header = {normalize_header(key): value for key, value in row.items()}
    normalized = {}
    for field in REQUIRED_FIELDS | OPTIONAL_FIELDS:
        source_name = column_mapping.get(field, field)
        normalized[field] = by_normalized_header.get(normalize_header(source_name))
    return normalized


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_quality(output, quality, errors):
    output.mkdir(parents=True, exist_ok=True)
    # Local row numbers/reasons only; never include a claim or member identifier.
    (output / "data_quality.json").write_text(json.dumps({
        "summary": quality, "row_errors": errors,
        "raw_claim_values_included": False,
        "member_identifiers_included": False,
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
