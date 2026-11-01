#!/usr/bin/env python3
"""Build the configured market report from saved Parquet outputs and local inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq
import polars as pl
from pipeline.common import csv_safe_cell


ROOT = Path(__file__).resolve().parent
REPORT_CONFIG = ROOT / "config/report.json"


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run the data pipeline first.")
    return pq.read_table(path).to_pylist()


def fmt_num(value: float | int | None, places: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "—"
    return f"{value:,.{places}f}"


def finite_number(value: object) -> float | None:
    """Normalize numeric Parquet scalars, including Decimal, for report math."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def json_date(value: object) -> str | None:
    """Convert Parquet date scalars to JSON-safe ISO strings."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def fmt_money(value: float | int | None) -> str:
    if value is None or not math.isfinite(float(value)):
        return "—"
    return f"${value:,.2f}"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: csv_safe_cell(value) for key, value in row.items()}
                          for row in rows)


def stored_scope_status(run: dict, comparison_rows: list[dict],
                        config: dict, comparison_path: Path) -> tuple[bool, str]:
    """Verify the saved Parquet scope; raw CMS files are optional after import."""
    selected_source = run.get("drug_selection_source_file")
    selected_hash = run.get("drug_selection_source_sha256")
    scope_path = ROOT / "data" / "ref" / "drug_scope.parquet"
    if (run.get("drug_selection_source") != config["selection_source"]
            or not selected_source or not selected_hash or not scope_path.is_file()
            or not comparison_path.is_file()):
        return False, "unavailable"
    try:
        scope = pl.read_parquet(scope_path, columns=[
            "hcpcs", "selection_source_file", "selection_source_sha256"
        ])
        scope_codes = sorted(scope["hcpcs"].unique().to_list())
        run_codes = sorted(run.get("drugs", []))
        scope_hashes = set(scope["selection_source_sha256"].drop_nulls().to_list())
        scope_files = {Path(value).name for value in
                       scope["selection_source_file"].drop_nulls().to_list()}
        comparison_codes = sorted({row.get("hcpcs") for row in comparison_rows if row.get("hcpcs")})
        if (not scope_codes or scope_codes != run_codes
                or scope_hashes != {selected_hash}
                or scope_files != {Path(selected_source).name}
                or comparison_codes != run_codes
                or (run.get("rows") is not None and len(comparison_rows) != run["rows"])):
            return False, "inconsistent_parquet"

        source_path = ROOT / selected_source
        if not source_path.is_file() and selected_source.startswith("data/raw/"):
            source_path = ROOT / "data" / "raw_essential_inputs" / selected_source[len("data/raw/"):]
        if source_path.is_file():
            from pipeline.common import sha256
            if sha256(source_path) != selected_hash:
                return False, "source_hash_mismatch"
            return True, "source_verified"
        return True, "archived_parquet_verified"
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError):
        return False, "invalid_parquet"


def input_inventory(config: dict) -> list[dict]:
    inventory = []
    for group in ("required_inputs", "supplemental_inputs"):
        for spec in config.get(group, []):
            matches = set()
            for pattern in spec.get("patterns", []):
                matches.update(p for p in ROOT.glob(pattern) if p.is_file()
                               and not p.name.endswith((".part", ".sha256")))
            inventory.append({
                "key": spec["key"],
                "label": spec["label"],
                "purpose": spec.get("purpose", ""),
                "required": group == "required_inputs",
                "files": sorted(matches),
            })
    return inventory


def required_source_integrity(inventory: list[dict]) -> tuple[bool, list[str]]:
    """Require original inputs and sidecars whose digests match the source bytes."""
    problems = []
    for item in inventory:
        if not item["required"]:
            continue
        if not item["files"]:
            problems.append(f"{item['key']}: no original input file")
            continue
        for source in item["files"]:
            sidecar = source.with_name(source.name + ".sha256")
            try:
                expected = sidecar.read_text(encoding="ascii").strip().split()[0].lower()
            except (OSError, IndexError, UnicodeError):
                problems.append(f"{item['key']}: missing SHA-256 sidecar for {source.name}")
                continue
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                problems.append(f"{item['key']}: invalid SHA-256 sidecar for {source.name}")
                continue
            digest = hashlib.sha256()
            try:
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                problems.append(f"{item['key']}: source became unavailable while checking {source.name}")
                continue
            if digest.hexdigest() != expected:
                problems.append(f"{item['key']}: SHA-256 mismatch for {source.name}")
    return not problems, problems


def parquet_lineage_status(paths: dict[str, Path]) -> tuple[bool, list[str]]:
    """Verify provenance embedded in the Parquet snapshot used by the report.

    Raw downloads are ingestion inputs, not runtime dependencies. A complete
    archived snapshot remains usable when those downloads have been removed,
    provided the Parquet artifacts carry their source lineage.
    """
    lineage = [
        ("comparison", paths["comparison"], ("source_file", "source_sha256")),
        ("ASP reference", paths["asp"], ("source_file", "source_sha256")),
        ("selected drug scope", paths["scope"],
         ("selection_source_file", "selection_source_sha256")),
        ("hospital rate", paths["hospital_rates"], ("source_file", "source_sha256")),
        ("hospital quality", paths["quality"], ("source_file", "source_sha256")),
    ]
    problems = []
    for label, path, required_columns in lineage:
        if not path.is_file():
            problems.append(f"{label}: Parquet artifact is missing")
            continue
        try:
            parquet = pq.ParquetFile(path)
            columns = set(parquet.schema_arrow.names)
            missing = set(required_columns) - columns
            if missing:
                problems.append(f"{label}: Parquet lineage columns missing ({', '.join(sorted(missing))})")
                continue
            if parquet.metadata.num_rows == 0:
                problems.append(f"{label}: Parquet artifact has no rows")
                continue
            empty_checks = [
                pl.col(name).cast(pl.Utf8, strict=False).str.strip_chars().is_null()
                | (pl.col(name).cast(pl.Utf8, strict=False).str.strip_chars() == "")
                for name in required_columns
            ]
            missing_count = (pl.scan_parquet(path)
                             .select(pl.any_horizontal(*empty_checks).sum().alias("missing"))
                             .collect(engine="streaming").item())
            if missing_count:
                problems.append(f"{label}: {missing_count} rows have incomplete source lineage")
        except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
            problems.append(f"{label}: Parquet lineage could not be verified ({exc})")
    return not problems, problems


def reference_coverage() -> dict:
    """Summarize only locally loaded reference Parquet; never synthesize counts."""
    ref_dir = ROOT / "data" / "ref"
    sources = [
        ("asp", "CMS ASP benchmarks", ref_dir / "ref_asp.parquet"),
        ("crosswalk", "CMS NDC–HCPCS crosswalk", ref_dir / "ref_crosswalk.parquet"),
        ("ndc_products", "FDA NDC products", ref_dir / "ref_ndc_products.parquet"),
        ("ndc_packages", "FDA NDC packages", ref_dir / "ref_ndc_packages.parquet"),
        ("hospitals", "Ohio CMS hospital catalog", ref_dir / "ref_hospitals.parquet"),
        ("nadac", "NADAC prices", ref_dir / "ref_nadac.parquet"),
        ("providers", "NPPES providers", ref_dir / "ref_providers.parquet"),
        ("enrollments", "CMS hospital enrollments", ref_dir / "ref_enrollments.parquet"),
        ("partb_spending", "CMS Part B spending scope", ref_dir / "drug_scope.parquet"),
    ]
    rows = []
    for key, label, path in sources:
        if not path.is_file():
            rows.append({"key": key, "label": label, "available": False, "rows": 0})
            continue
        parquet = pq.ParquetFile(path)
        rows.append({"key": key, "label": label, "available": True,
                     "rows": parquet.metadata.num_rows})

    quarter_rows = []
    asp_path = ref_dir / "ref_asp.parquet"
    if asp_path.is_file():
        table = pq.read_table(asp_path, columns=["quarter", "hcpcs"])
        counts: dict[str, set[str]] = defaultdict(set)
        for quarter, code in zip(table.column("quarter").to_pylist(), table.column("hcpcs").to_pylist()):
            if quarter and code:
                counts[str(quarter)].add(str(code))
        quarter_rows = [{"quarter": quarter, "hcpcs_count": len(codes)}
                        for quarter, codes in sorted(counts.items())]
    return {"datasets": rows, "asp_quarters": quarter_rows}


def loaded_reference_sources() -> list[dict]:
    """Use lineage embedded by the loaders to make source exports useful in draft runs."""
    specs = [
        ("cms_asp", "data/ref/ref_asp.parquet"),
        ("cms_crosswalk", "data/ref/ref_crosswalk.parquet"),
        ("fda_ndc_products", "data/ref/ref_ndc_products.parquet"),
        ("fda_ndc_packages", "data/ref/ref_ndc_packages.parquet"),
        ("nadac", "data/ref/ref_nadac.parquet"),
        ("cms_hospital_list", "data/ref/ref_hospitals.parquet"),
        ("cms_partb_spending", "data/ref/drug_scope.parquet"),
        ("nppes", "data/ref/ref_providers.parquet"),
        ("hospital_enrollments", "data/ref/ref_enrollments.parquet"),
    ]
    result = []
    for kind, relative_path in specs:
        path = ROOT / relative_path
        if not path.is_file():
            continue
        columns = set(pq.ParquetFile(path).schema_arrow.names)
        if not {"source_file", "source_sha256"} <= columns:
            continue
        group = ["source_file", "source_sha256"]
        if "source_member" in columns:
            group.append("source_member")
        aggregates = [pl.len().alias("reference_rows")]
        if "effective_start" in columns:
            aggregates.append(pl.col("effective_start").min().alias("effective_start"))
        if "effective_end" in columns:
            aggregates.append(pl.col("effective_end").max().alias("effective_end"))
        grouped = (pl.scan_parquet(path).group_by(group).agg(aggregates)
                   .collect(engine="streaming").to_dicts())
        for row in grouped:
            effective_start = row.get("effective_start")
            effective_end = row.get("effective_end")
            result.append({
                "source_kind": kind,
                "source_file": row["source_file"],
                "source_member": row.get("source_member") or "",
                "source_sha256": row["source_sha256"] or "",
                "effective_start": effective_start.isoformat() if effective_start else "",
                "effective_end": effective_end.isoformat() if effective_end else "",
                "latest_file_last_updated": "",
                "hcpcs_codes": "",
                "comparison_rows": 0,
                "reference_rows": row["reference_rows"],
            })
    return result


def build_report(output_dir: Path, comparison_path: Path, quality_path: Path,
                 run_info_path: Path, report_config_path: Path = REPORT_CONFIG) -> Path:
    rows = read_rows(comparison_path)
    quality = read_rows(quality_path)
    run = json.loads(run_info_path.read_text(encoding="utf-8"))
    config = json.loads(report_config_path.read_text(encoding="utf-8"))
    inventory = input_inventory(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    selection_input_present = bool(next((i["files"] for i in inventory
                                         if i["key"] == config["selection_source"]), []))
    original_sources_verified, source_integrity_problems = required_source_integrity(inventory)
    selected_hash = run.get("drug_selection_source_sha256")
    scope_current, scope_snapshot_status = stored_scope_status(
        run, rows, config, comparison_path)
    scope_lookup: dict[str, dict] = {}
    scope_path = ROOT / "data" / "ref" / "drug_scope.parquet"
    if scope_path.is_file():
        available = set(pq.ParquetFile(scope_path).schema_arrow.names)
        wanted = [name for name in ("hcpcs", "partb_spending", "reviewed_by", "review_date",
                                    "review_status", "review_notes") if name in available]
        if "hcpcs" in wanted:
            for item in pl.scan_parquet(scope_path).select(wanted).collect(engine="streaming").to_dicts():
                scope_lookup[item["hcpcs"]] = item
    # A saved scope remains usable when its checksum agrees across the scope,
    # comparison, and run metadata. Raw CMS files are needed only for re-import.
    if not scope_current:
        rows = []
    drug_codes = list(run.get("drugs", [])) if scope_current else []
    reviewed_codes = {
        code for code in drug_codes
        if any(r.get("hcpcs") == code and r.get(config["review_field"]) is True for r in rows)
    }
    scope_complete = (
        scope_current
        and len(drug_codes) >= config["target_drug_count"]
    )
    all_units_reviewed = bool(drug_codes) and len(reviewed_codes) == len(drug_codes)
    required_parquets = {
        "comparison": comparison_path,
        "quality": quality_path,
        "run_info": run_info_path,
        "asp": ROOT / "data" / "ref" / "ref_asp.parquet",
        "scope": ROOT / "data" / "ref" / "drug_scope.parquet",
        "hospital_rates": ROOT / "data" / "hpt" / "norm" / "hpt_drug_rates.parquet",
    }
    required_parquets_ready = all(path.is_file() for path in required_parquets.values())
    parquet_lineage_verified, parquet_lineage_problems = parquet_lineage_status(required_parquets)
    # The operational dashboard and report are Parquet-backed. Original raw
    # downloads are required only to ingest or refresh those stored artifacts.
    draft = not (scope_complete and all_units_reviewed and required_parquets_ready
                 and parquet_lineage_verified)

    status_counts = Counter(r.get("status") or "(missing)" for r in rows)
    all_systems = sorted({r.get("system") for r in rows if r.get("system")})
    all_hospitals = {r.get("hospital_key") for r in rows if r.get("hospital_key")}
    priced = [
        r for r in rows
        if r.get("price_type") == config["headline_price_type"]
        and r.get("status") == config["headline_status"]
        and finite_number(r.get("markup_multiple")) is not None
    ]

    by_drug: dict[str, list[dict]] = defaultdict(list)
    by_site: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in priced:
        by_drug[row["hcpcs"]].append(row)
        by_site[(row["hcpcs"], row.get("hospital_key") or "")].append(row)

    summary_rows = []
    drug_names = {}
    for code in drug_codes:
        data = by_drug.get(code, [])
        if not data:
            continue
        drug_names[code] = next((r.get("drug_name") for r in data if r.get("drug_name")), code)
        markups = [float(r["markup_multiple"]) for r in data]
        gaps = [
            float(r["price_per_billing_unit"]) - float(r["asp_payment_limit"])
            for r in data
            if finite_number(r.get("price_per_billing_unit")) is not None
            and finite_number(r.get("asp_payment_limit")) is not None
        ]
        scope_row = scope_lookup.get(code, {})
        partb_spending = finite_number(scope_row.get("partb_spending"))
        estimated_dollars_at_stake = (
            max(0.0, (median(markups) - 1.0) * partb_spending)
            if partb_spending is not None else None
        )
        summary_rows.append({
            "hcpcs": code,
            "drug_name": drug_names[code],
            "negotiated_ok_rates": len(data),
            "hospital_sites": len({r.get("hospital_key") for r in data}),
            "median_markup": median(markups),
            "min_markup": min(markups),
            "max_markup": max(markups),
            "median_dollars_over_benchmark_per_billing_unit": median(gaps) if gaps else None,
            "partb_spending_proxy": partb_spending,
            "estimated_dollars_at_stake_proxy": estimated_dollars_at_stake,
            "clinical_reviewer_name": scope_row.get("reviewed_by") if code in reviewed_codes else None,
            "clinical_review_date": scope_row.get("review_date") if code in reviewed_codes else None,
            "clinical_review_status": scope_row.get("review_status") if code in reviewed_codes else None,
            "clinical_review_notes": scope_row.get("review_notes") if code in reviewed_codes else None,
        })
    summary_rows.sort(key=lambda r: (-r["median_markup"], r["hcpcs"]))

    site_rows = []
    for (code, key), data in by_site.items():
        markups = [float(r["markup_multiple"]) for r in data]
        gaps = [
            float(r["price_per_billing_unit"]) - float(r["asp_payment_limit"])
            for r in data
            if finite_number(r.get("price_per_billing_unit")) is not None
            and finite_number(r.get("asp_payment_limit")) is not None
        ]
        first = data[0]
        site_rows.append({
            "hcpcs": code,
            "drug_name": drug_names.get(code, first.get("drug_name")),
            "hospital_key": key,
            "hospital_label": first.get("hospital_label"),
            "system": first.get("system"),
            "locations": first.get("locations"),
            "negotiated_ok_rates": len(data),
            "payer_plans": len({(r.get("payer_name"), r.get("plan_name")) for r in data}),
            "median_markup": median(markups),
            "median_dollars_over_benchmark_per_billing_unit": median(gaps) if gaps else None,
            "unit_reviewed": code in reviewed_codes,
        })
    site_rows.sort(key=lambda r: (r["hcpcs"], r["median_markup"], r["hospital_label"] or ""))

    source_map = {}
    for row in rows:
        source = row.get("source_file") or ""
        if not source:
            continue
        key = (source, row.get("source_member") or "")
        entry = source_map.setdefault(key, {
            "source_kind": "hospital_price_comparison",
            "source_file": source,
            "source_member": key[1],
            "source_sha256": row.get("source_sha256") or "",
            "effective_start": json_date(row.get("effective_start")),
            "effective_end": json_date(row.get("effective_end")),
            "latest_file_last_updated": "",
            "hcpcs_codes": set(),
            "comparison_rows": 0,
            "reference_rows": 0,
        })
        entry["comparison_rows"] += 1
        if row.get("hcpcs"):
            entry["hcpcs_codes"].add(row["hcpcs"])
        file_date = row.get("file_last_updated")
        if isinstance(file_date, date):
            file_date = file_date.isoformat()
        if file_date and str(file_date) > entry["latest_file_last_updated"]:
            entry["latest_file_last_updated"] = str(file_date)
    source_rows = loaded_reference_sources()
    for entry in source_map.values():
        entry["hcpcs_codes"] = ",".join(sorted(entry["hcpcs_codes"]))
        entry.setdefault("reference_rows", 0)
        source_rows.append(entry)
    source_rows.sort(key=lambda r: (r["source_kind"], r["source_file"], r["source_member"]))

    outputs = config["output_files"]
    sites_path = output_dir / outputs["sites"]
    sources_path = output_dir / outputs["sources"]
    dashboard_data_path = output_dir / outputs["dashboard_data"]
    write_csv(sites_path, list(site_rows[0].keys()) if site_rows else [], site_rows)
    write_csv(sources_path, ["source_kind", "source_file", "source_member", "source_sha256",
                             "effective_start", "effective_end", "latest_file_last_updated",
                             "hcpcs_codes", "comparison_rows", "reference_rows"], source_rows)

    quality_errors = sum(bool(r.get("error")) for r in quality)
    zero_drug_files = sum((r.get("drug_rows") or 0) == 0 for r in quality)
    quarter_range = sorted({r.get("benchmark_quarter") for r in rows if r.get("benchmark_quarter")})
    file_dates = [r.get("file_last_updated") for r in rows if r.get("file_last_updated")]
    file_dates = [d.isoformat() if isinstance(d, date) else str(d) for d in file_dates]
    rate_rank = [[
        str(i), r["hcpcs"], r["drug_name"], fmt_num(r["median_markup"], 2) + "×",
        str(r["hospital_sites"]), fmt_money(r["median_dollars_over_benchmark_per_billing_unit"]),
    ] for i, r in enumerate(summary_rows, 1)]
    stake_rank = [[
        str(i), r["hcpcs"], r["drug_name"], fmt_money(r.get("partb_spending_proxy")),
        fmt_money(r.get("estimated_dollars_at_stake_proxy")), fmt_num(r["median_markup"], 2) + "×",
    ] for i, r in enumerate(sorted(
        summary_rows,
        key=lambda row: (row.get("estimated_dollars_at_stake_proxy") is None,
                         -(row.get("estimated_dollars_at_stake_proxy") or 0), row["hcpcs"]),
    )[:5], 1)]
    statuses = [[status, f"{n:,}"] for status, n in status_counts.most_common()]
    inputs_rows = [[
        item["label"], "required" if item["required"] else "supplemental",
        str(len(item["files"])), item["purpose"],
    ] for item in inventory]
    status_notes = config.get("status_notes", {})
    status_explanations = [f"`{s}`: {status_notes[s]}" for s in status_counts if s in status_notes]
    status_explanations_text = "\n".join(f"- {note}" for note in status_explanations)
    unreviewed_codes = [c for c in drug_codes if c not in reviewed_codes]
    target_count = config["target_drug_count"]
    selection_source = (run.get("drug_selection_source") if scope_current
                        else "unavailable: current CMS Part B scope has not been built")
    input_summary = [{
        "key": i["key"], "label": i["label"], "purpose": i["purpose"],
        "required": i["required"], "file_count": len(i["files"]),
        "available": bool(i["files"]),
    } for i in inventory]
    dashboard_payload = {
        "title": config["title"],
        "report_generated": date.today().isoformat(),
        "data_build_generated": run.get("generated_at", "unknown"),
        "benchmark_rule": run.get("benchmark_rule", "unknown"),
        "benchmark_quarters": quarter_range,
        "file_date_min": min(file_dates) if file_dates else None,
        "file_date_max": max(file_dates) if file_dates else None,
        "draft": draft,
        "draft_reasons": {
            "required_inputs_ready": parquet_lineage_verified,
            "required_parquets_ready": required_parquets_ready,
            "parquet_lineage_problems": parquet_lineage_problems,
            "raw_inputs_verified": original_sources_verified,
            "raw_source_integrity_problems": source_integrity_problems,
            "scope_complete": scope_complete,
            "scope_current": scope_current,
            "all_units_reviewed": all_units_reviewed,
            "selection_source_files_present": selection_input_present,
            "scope_snapshot_status": scope_snapshot_status,
            "data_source_mode": "raw_inputs_verified" if original_sources_verified else scope_snapshot_status,
        },
        "drug_count": len(drug_codes),
        "target_drug_count": target_count,
        "drug_codes": drug_codes,
        "drug_selection_year": run.get("drug_selection_year") if scope_current else None,
        "drug_selection_source_sha256": selected_hash if scope_current else None,
        "reviewed_drug_count": len(reviewed_codes),
        "hospital_count": len(all_hospitals),
        "hospitals_without_findable_file": None,
        "hospital_coverage_note": "The Ohio hospital universe has not yet been reconciled to the machine-readable-file catalog; the number without a findable file is not available.",
        "system_count": len(all_systems),
        "systems": all_systems,
        "comparison_rows": len(rows),
        "headline_rows": len(priced),
        "quality_file_count": len(quality),
        "quality_error_count": quality_errors,
        "zero_drug_file_count": zero_drug_files,
        "source_hash_rows": sum(bool(r.get("source_sha256")) for r in rows),
        "status_counts": [{"status": status, "count": count} for status, count in status_counts.most_common()],
        "drug_summary": summary_rows,
        "top_drugs_by_dollars_at_stake": sorted(
            summary_rows,
            key=lambda row: (row.get("estimated_dollars_at_stake_proxy") is None,
                             -(row.get("estimated_dollars_at_stake_proxy") or 0), row["hcpcs"]),
        )[:5],
        "dollars_at_stake_definition": (
            "CMS Medicare Part B spending by drug multiplied by the positive portion of the "
            "median posted hospital negotiated-rate markup above the CMS ASP payment limit. "
            "This is an exposure proxy, not an estimate of savings or hospital profit."
        ),
        "hospital_rates": site_rows,
        "source_inventory": source_rows,
        "inputs": input_summary,
        "reference_coverage": reference_coverage(),
        "method_notes": config.get("method_notes", []),
        "status_notes": status_notes,
        "headline_price_type": config["headline_price_type"],
        "headline_status": config["headline_status"],
        "benchmark_addon_percent": config.get("benchmark_addon_percent"),
    }
    dashboard_data_path.write_text(json.dumps(dashboard_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    draft_label = "DRAFT"
    report = f"""# {config['title']} — {draft_label}

**Report generated:** {date.today().isoformat()}  
**Underlying comparison build:** {run.get('generated_at', 'unknown')}  
**Benchmark rule:** {run.get('benchmark_rule', 'unknown')}  
**Source file dates:** {min(file_dates) if file_dates else 'unknown'} to {max(file_dates) if file_dates else 'unknown'}  
**Benchmark quarters present in comparison:** {', '.join(quarter_range) or 'none'}

## Scope and review status

This run covers **{len(drug_codes)} current HCPCS drug codes**, **{len(all_hospitals)} hospital sites**, and **{len(all_systems)} hospital systems**. Configured codes: {', '.join(drug_codes) or 'none'}. Target scope: {target_count} codes. Selection source: `{selection_source}`. Scope snapshot: `{scope_snapshot_status}`. Original selection file present: {str(selection_input_present).lower()}. Unit-reviewed codes: {len(reviewed_codes)} of {len(drug_codes)}{'; unreviewed: ' + ', '.join(unreviewed_codes) if unreviewed_codes else ''}.

The first ranking is by median markup among rows matching the configured headline price type (`{config['headline_price_type']}`) and status (`{config['headline_status']}`). The “dollars at stake” ranking is an exposure proxy: CMS Medicare Part B spending for the drug multiplied by the positive portion of the median posted hospital rate markup above the ASP payment limit. It is not a savings estimate, hospital profit, or a guarantee that the same volume could move to another site. It assumes Medicare spending is a usable volume proxy for the posted hospital rates.

## Drug ranking

{markdown_table(['Rank', 'HCPCS', 'Drug', 'Median markup', 'Hospitals', 'Median $ over benchmark per billing unit'], rate_rank)}

### Top five by estimated dollars at stake

{markdown_table(['Rank', 'HCPCS', 'Drug', 'CMS Part B spend proxy', 'Estimated exposure proxy', 'Median markup'], stake_rank)}

Individual hospital comparisons, including payer-plan counts and unit-review flags, are in [`{outputs['sites']}`]({outputs['sites']}). Lower-markup sites are leads for further review; the report does not establish network status, clinical suitability, or physician agreement.

Dashboard data: [`{outputs['dashboard_data']}`]({outputs['dashboard_data']}).

## Data quality

Comparison rows: **{len(rows):,}**. Negotiated-dollar `ok` rows used in the ranking: **{len(priced):,}**. Quality-file records: **{len(quality):,}**; parser errors: **{quality_errors:,}**; files with zero in-scope drug rows: **{zero_drug_files:,}**. Source hashes are attached to **{sum(bool(r.get('source_sha256')) for r in rows):,} of {len(rows):,} comparison rows**.

{markdown_table(['Row status', 'Count'], statuses)}

Rows outside the configured headline status are excluded from headline medians.

{status_explanations_text if status_explanations_text else 'No configured status notes apply to the observed statuses.'}

## Sources and method

- The benchmark rule recorded by the build is `{run.get('benchmark_rule', 'unknown')}`.
- File-level SHA-256 values and comparison row counts are in [`{outputs['sources']}`]({outputs['sources']}).
- Source availability is discovered from the configured input patterns below.

{markdown_table(['Input', 'Requirement', 'Files found', 'Purpose'], inputs_rows)}

## Method notes

{chr(10).join('- ' + note for note in config.get('method_notes', []))}

## Limits and readiness

- Required Parquet artifacts ready: {str(required_parquets_ready).lower()}.
- Source lineage embedded in the required Parquet artifacts is complete: {str(parquet_lineage_verified).lower()}.
- Parquet lineage issues: {', '.join(parquet_lineage_problems) if parquet_lineage_problems else 'none'}.
- Original raw inputs present with matching SHA-256 sidecars: {str(original_sources_verified).lower()}; raw files are needed to re-import, not to read the saved Parquet snapshot.
- Raw source availability or integrity notes: {', '.join(source_integrity_problems) if source_integrity_problems else 'none'}.
- Original configured input files currently present: {sum(bool(i['files']) for i in inventory if i['required'])} of {sum(i['required'] for i in inventory)}.
- Drug scope meets the configured count and selection-evidence requirement: {str(scope_complete).lower()}.
- All configured drug codes have a manual review flag: {str(all_units_reviewed).lower()}.
- Hospital coverage observed in the comparison: {len(all_hospitals)} sites across {len(all_systems)} systems; completeness is determined by the configured coverage inputs.
- Hospitals with no findable price file: not available; the current provider universe has not been reconciled to the MRF catalog.
- Input readiness: {'ready from the current Parquet snapshot' if not draft else 'incomplete; review the Parquet lineage, scope, and clinical unit-review status before external use'}.

## Report status

{'This report is a draft because one or more configured source, scope, or review requirements are unmet.' if draft else 'Source, scope, and clinical review checks are ready; an independent Admin must still release the report. Until then, this report remains a draft.'}
"""
    report_path = output_dir / outputs["report"]
    report_path.write_text(report, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports")
    parser.add_argument("--comparison", type=Path, default=ROOT / "data/mart/comparison.parquet")
    parser.add_argument("--quality", type=Path, default=ROOT / "data/hpt/norm/hpt_file_quality.parquet")
    parser.add_argument("--run-info", type=Path, default=ROOT / "data/mart/run_info.json")
    parser.add_argument("--report-config", type=Path, default=REPORT_CONFIG)
    args = parser.parse_args()
    output = build_report(args.output_dir, args.comparison, args.quality, args.run_info, args.report_config)
    print(f"Wrote {output}")
    outputs = json.loads(args.report_config.read_text(encoding="utf-8"))["output_files"]
    print(f"Wrote {args.output_dir / outputs['sites']}")
    print(f"Wrote {args.output_dir / outputs['sources']}")
    print(f"Wrote {args.output_dir / outputs['dashboard_data']}")


if __name__ == "__main__":
    main()
