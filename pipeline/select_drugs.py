"""Select the target HCPCS drug scope from the CMS Part B spending data."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import zipfile
from io import BytesIO
from datetime import date
from pathlib import Path

import polars as pl

from .common import load_yaml, norm_hcpcs, parse_hcpcs_dosage, paths, sha256


def key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def number(value: object) -> float | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "").replace("$", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def csv_tables(path: Path):
    """Yield tabular CMS CSV members from a CSV file or ZIP, with their headers."""
    if path.suffix.casefold() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.casefold().endswith(".csv") and not member.startswith("__MACOSX"):
                    raw = archive.read(member).decode("utf-8-sig", errors="replace")
                    reader = csv.DictReader(io.StringIO(raw))
                    if reader.fieldnames:
                        yield member, reader.fieldnames, list(reader)
    elif path.suffix.casefold() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames:
                yield path.name, reader.fieldnames, list(reader)


def excel_tables(path: Path):
    """Read CMS's annual DYT Excel workbooks, whose table header starts on row 6."""
    import fastexcel

    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            if not member.casefold().endswith(".xlsx") or member.startswith("__MACOSX"):
                continue
            workbook_bytes = archive.read(member)
            reader = fastexcel.read_excel(workbook_bytes)
            sheet = next((name for name in reader.sheet_names
                          if "spending" in name.casefold() and "utilization" in name.casefold()), None)
            if sheet is None:
                continue
            frame = pl.read_excel(BytesIO(workbook_bytes), sheet_name=sheet, engine="calamine",
                                  read_options={"header_row": 5}, infer_schema_length=None)
            headers = frame.columns
            # The yearly report repeats Total Spending for each calendar year.
            # In the CMS DYT workbook the final occurrence is the report year.
            spending_headers = [name for name in headers if key(name).startswith("totalspending")]
            if not spending_headers:
                continue
            code_col = next((name for name in headers
                             if "hcpcs" in key(name) and "code" in key(name)), None)
            if not code_col:
                continue
            year_match = re.search(r"DYT(20\d{2})", path.name, flags=re.I)
            if not year_match:
                year_match = re.search(r"20\d{2}", sheet)
            if not year_match:
                continue
            year = int(year_match.group(1) if year_match.lastindex else year_match.group(0))
            renamed = {name: f"total_spending_{year}" if name == spending_headers[-1] else name
                       for name in headers}
            rows = [{renamed.get(k, k): v for k, v in row.items()} for row in frame.to_dicts()]
            # Normalize the descriptive fields used by the shared selector.
            column_map = {key(name): name for name in renamed.values()}
            normalized_rows = []
            for row in rows:
                normalized_rows.append({
                    "HCPCS_Cd": row.get(code_col),
                    "Drug_Description": row.get(column_map.get("drugdescription")),
                    "Brnd_Name": row.get(column_map.get("brandname")),
                    "Gnrc_Name": row.get(column_map.get("genericname")),
                    f"Tot_Spndng_{year}": row.get(f"total_spending_{year}"),
                })
            yield member, ["HCPCS_Cd", "Drug_Description", "Brnd_Name", "Gnrc_Name",
                           f"Tot_Spndng_{year}"], normalized_rows


def find_spending_table(files: list[Path]):
    candidates = []
    for path in files:
        tables = excel_tables(path) if path.suffix.casefold() == ".zip" and "dyt" in path.name.casefold() else csv_tables(path)
        for member, headers, rows in tables:
            columns = {key(h): h for h in headers}
            # CMS publishes HCPCS_Cd; key() intentionally removes punctuation,
            # so match the normalized column names here.
            code_col = next((columns[k] for k in ("hcpcscd", "hcpcscode", "hcpcs") if k in columns), None)
            spend_fields = []
            for normalized, original in columns.items():
                match = re.fullmatch(r"totspndng(?:_?(20\d{2}))?", normalized)
                if match:
                    spend_fields.append((int(match.group(1)) if match.group(1) else 0, original))
            if code_col and spend_fields:
                spend_year, spend_col = max(spend_fields)
            source_year = max(spend_year, int(re.search(r"20\d{2}", path.name).group(0))
                              if re.search(r"20\d{2}", path.name) else 0)
            candidates.append((source_year, path.name, path, member, rows,
                                   columns, code_col, spend_year, spend_col))
    if not candidates:
        raise FileNotFoundError(
            "No CMS Part B Spending by Drug CSV found under data/raw_essential_inputs/partb_spending. "
            "Add the CMS summary data file, then rerun python -m pipeline.run_all."
        )
    return max(candidates, key=lambda item: (item[0], item[1]))


def review_rows(raw_dir: Path, selection_hash: str) -> dict[str, dict]:
    """Load optional reviewer sign-offs; a sign-off only applies to the exact ASP unit."""
    reviews = {}
    for path in sorted(raw_dir.glob("**/*.csv")):
        digest = sha256(path)
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                fields = {key(k): v for k, v in row.items()}
                code = norm_hcpcs(fields.get("hcpcs_cd") or fields.get("hcpcs_code") or fields.get("hcpcs"))
                reviewer = (fields.get("reviewed_by") or fields.get("reviewer") or "").strip()
                review_hash = (fields.get("selection_source_sha256") or
                               fields.get("scope_source_sha256") or "").strip().lower()
                if code and reviewer and review_hash == selection_hash.lower():
                    fields["source_file"] = path.relative_to(Path(__file__).resolve().parent.parent).as_posix()
                    fields["source_sha256"] = digest
                    reviews[code] = fields
    return reviews


def main() -> int:
    locations = paths()
    raw = locations["raw"]
    asp_path = locations["ref"] / "ref_asp.parquet"
    if not asp_path.exists():
        raise FileNotFoundError(f"{asp_path.name} is missing; run python -m pipeline.load_asp first.")
    report_config = json.loads((Path(__file__).resolve().parent.parent / "config" / "report.json")
                               .read_text(encoding="utf-8"))
    input_specs = {item["key"]: item for item in report_config.get("required_inputs", [])}
    patterns = input_specs.get("partb_spending", {}).get("patterns", ["data/raw_essential_inputs/partb_spending/**/*"])
    raw_root = paths()["raw"]
    raw_prefix = load_yaml("pipeline.yaml")["paths"]["raw"].replace("\\", "/").rstrip("/") + "/"
    raw_patterns = [pattern.removeprefix(raw_prefix) for pattern in patterns]
    input_paths = sorted({p for pattern in raw_patterns for p in raw_root.glob(pattern)
                          if p.is_file() and p.suffix.casefold() in {".csv", ".zip"}})
    output = locations["ref"] / "drug_scope.parquet"
    if not input_paths and output.is_file():
        print("No new CMS Part B source file; using the saved drug-scope Parquet.")
        return 0
    (_, _, source_path, source_member, spending_rows, columns,
     code_col, spend_year, spend_col) = find_spending_table(input_paths)

    description_col = next((columns[k] for k in ("hcpcsdesc", "drugdescription", "description")
                            if k in columns), None)
    brand_col = next((columns[k] for k in ("brndname", "brandname", "brand") if k in columns), None)
    generic_col = next((columns[k] for k in ("gnrcname", "genericname", "drugname") if k in columns), None)

    totals: dict[str, dict] = {}
    duplicate_rows = 0
    for row in spending_rows:
        code = norm_hcpcs(row.get(code_col))
        spend = number(row.get(spend_col))
        if not code or not code.startswith("J") or spend is None or spend < 0:
            continue
        record = totals.get(code)
        if record:
            duplicate_rows += 1
            record["partb_spending"] += spend
            continue
        generic = (row.get(generic_col) or "").strip() if generic_col else ""
        brand = (row.get(brand_col) or "").strip() if brand_col else ""
        description = (row.get(description_col) or "").strip() if description_col else ""
        totals[code] = {
            "hcpcs": code,
            "name": generic or description or brand or code,
            "brand": brand or None,
            "description": description or None,
            "partb_spending": spend,
        }
    if not totals:
        raise ValueError(f"No J-code rows with valid spending were found in {source_path.name}.")

    target_count = int(report_config["target_drug_count"])
    ranked = sorted(totals.values(), key=lambda r: (-r["partb_spending"], r["hcpcs"]))
    latest_asp = (pl.read_parquet(asp_path)
                  .sort("quarter")
                  .unique(subset=["hcpcs"], keep="last", maintain_order=True))
    asp_by_code = {row["hcpcs"]: row for row in latest_asp.iter_rows(named=True)}
    digest = sha256(source_path)
    reviews = review_rows(raw / "unit_reviews", digest)
    out = []
    for rank, item in enumerate(ranked[:target_count], start=1):
        asp = asp_by_code.get(item["hcpcs"], {})
        dose = parse_hcpcs_dosage(asp.get("dosage_text"))
        review = reviews.get(item["hcpcs"], {})
        review_unit = (review.get("billing_unit") or review.get("unit") or "").strip().upper()
        try:
            review_qty = float(review.get("billing_unit_qty") or review.get("qty") or "nan")
        except ValueError:
            review_qty = float("nan")
        reviewer = (review.get("reviewed_by") or review.get("reviewer") or "").strip()
        reviewed_by = reviewer if dose and review_unit == dose.unit and review_qty == dose.qty else None
        out.append({
            **item,
            "effective_start": date(spend_year, 1, 1) if spend_year else None,
            "effective_end": date(spend_year, 12, 31) if spend_year else None,
            "billing_qty": dose.qty if dose else None,
            "billing_unit": dose.unit if dose else None,
            "reviewed_by": reviewed_by or None,
            "spend_rank": rank,
            "spend_year": spend_year or None,
            "asp_quarter": asp.get("quarter"),
            "asp_dosage": asp.get("dosage_text"),
            "selection_source": "partb_spending",
            "selection_source_file": source_path.relative_to(Path(__file__).resolve().parent.parent).as_posix()
                if source_path.is_relative_to(Path(__file__).resolve().parent.parent) else source_path.as_posix(),
            "selection_source_member": source_member,
            "selection_source_sha256": digest,
            "unit_review_file": review.get("source_file") or None,
            "unit_review_sha256": review.get("source_sha256") or None,
        })

    locations["ref"].mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    pl.DataFrame(out).write_parquet(temporary, compression="zstd")
    if pl.scan_parquet(temporary).select(pl.len()).collect().item() != len(out) or not out:
        temporary.unlink(missing_ok=True)
        raise ValueError("Drug scope validation failed; existing scope Parquet was preserved.")
    os.replace(temporary, output)
    print(f"Selected {len(out)} HCPCS J-codes from CMS Part B spending ({spend_year or 'latest'}).")
    print(f"Source: {source_path.name} · SHA-256 {digest}")
    print(f"Wrote {output}")
    if duplicate_rows:
        print(f"Note: aggregated {duplicate_rows} additional rows sharing a HCPCS code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
