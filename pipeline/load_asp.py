"""Load CMS ASP payment limit files and NDC-HCPCS crosswalks into Parquet.

Input : every *.zip under data/raw_essential_inputs/cms_asp/ and data/raw_essential_inputs/cms_crosswalk/
        whose name has a quarter month + year (january_2026, october_2026, ...).
        Seasonal vaccine files are ignored.
Output: data/ref/ref_asp.parquet        one row per HCPCS per quarter
        data/ref/ref_crosswalk.parquet  one row per NDC-HCPCS pair per quarter

Rules (developer guide 1.2):
  * "Payment Limit" is already 106% of ASP. It is stored as is.
  * The header row is found by searching for the HCPCS column, not assumed.
  * The script fails if more than 1% of payment limits are null.

Run: python -m pipeline.load_asp
"""
from __future__ import annotations

import csv
import io
import re
import os
import sys
import zipfile
from datetime import date
from pathlib import Path

import polars as pl

from .common import (norm_hcpcs, norm_ndc, parse_hcpcs_dosage, paths, quarter_bounds,
                     quarter_from_filename, rel, sha256, to_float, write_sha256_sidecar)


def _key(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# ---------- reading tables out of a ZIP ----------

def _rows_from_member(zf: zipfile.ZipFile, member: str) -> list[list[str]]:
    data = zf.read(member)
    low = member.lower()
    if low.endswith((".xlsx", ".xls")):
        df = pl.read_excel(io.BytesIO(data), engine="calamine", has_header=False,
                           infer_schema_length=0)
        return [["" if v is None else str(v) for v in row] for row in df.iter_rows()]
    if low.endswith((".csv", ".txt")):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    return []


def _find_header(rows: list[list[str]], must: list[str]) -> int | None:
    """Index of the first row whose cells include every key in `must`."""
    for i, row in enumerate(rows[:40]):
        keys = {_key(c) for c in row}
        if all(any(m(k) for k in keys) for m in must):
            return i
    return None


def _is_hcpcs_col(k: str) -> bool:
    return k in ("hcpcs", "hcpcscode") or bool(re.fullmatch(r"\d{4}code", k))


def _pick(header: list[str], *options) -> int | None:
    keys = [_key(h) for h in header]
    for opt in options:
        for i, k in enumerate(keys):
            if (callable(opt) and opt(k)) or k == opt:
                return i
    return None


def _best_table(zip_path: Path, must) -> tuple[str, list[str], list[list[str]]]:
    """The member + header + data rows of the table that matches `must`."""
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [m for m in zf.namelist()
                      if m.lower().endswith((".xlsx", ".xls", ".csv", ".txt"))
                      and not m.startswith("__MACOSX")]
        best = None
        for member in candidates:
            rows = _rows_from_member(zf, member)
            h = _find_header(rows, must)
            if h is None:
                continue
            data = rows[h + 1:]
            if best is None or len(data) > len(best[2]):
                best = (member, rows[h], data)
    if best is None:
        raise ValueError(f"No table with the expected columns in {zip_path.name}")
    return best


# ---------- loaders ----------

def load_payment_limit(zip_path: Path, quarter: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    member, header, rows = _best_table(
        zip_path, [_is_hcpcs_col, lambda k: k == "paymentlimit"])
    i_code = _pick(header, _is_hcpcs_col)
    i_desc = _pick(header, "shortdescription", "description")
    i_dose = _pick(header, "hcpcscodedosage", "hcpcsdosage", "dosage")
    i_lim = _pick(header, "paymentlimit")
    start, end = quarter_bounds(quarter)
    digest = sha256(zip_path)
    write_sha256_sidecar(zip_path, digest)
    out, bad_codes = [], 0
    for r in rows:
        if len(r) <= max(i_code, i_lim):
            continue
        code = norm_hcpcs(r[i_code])
        if code is None:
            if r[i_code].strip():
                bad_codes += 1   # notes, footers, disclaimers
            continue
        dose_text = r[i_dose].strip() if i_dose is not None else ""
        dose = parse_hcpcs_dosage(dose_text)
        out.append({
            "hcpcs": code,
            "short_description": r[i_desc].strip() if i_desc is not None else None,
            "dosage_text": dose_text or None,
            "billing_qty": dose.qty if dose else None,
            "billing_unit": dose.unit if dose else None,
            "payment_limit": to_float(r[i_lim]),
            "quarter": quarter,
            "effective_start": start,
            "effective_end": end,
            "source_file": rel(zip_path),
            "source_member": member,
            "source_sha256": digest,
        })
    df = pl.DataFrame(out)
    active, excluded = _split_unpriced_asp(df, zip_path.name)
    print(f"  ASP {quarter}: {len(active):,} priced codes "
          f"({len(excluded)} rows without a published payment limit excluded, "
          f"{bad_codes} non-code rows skipped) from {member}")
    return active, excluded


def _split_unpriced_asp(df: pl.DataFrame, source: str
                        ) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Exclude missing CMS limits from comparisons without losing their source rows."""
    if df.is_empty():
        raise ValueError(f"{source}: no ASP rows were found")
    nulls = df["payment_limit"].null_count()
    if len(df) == 0 or nulls / len(df) > 0.01:
        raise ValueError(f"{source}: {nulls} of {len(df)} payment limits are null "
                         f"(over 1%). Check the source file and column mapping.")
    excluded = (df.filter(pl.col("payment_limit").is_null())
                .with_columns(pl.lit("missing_payment_limit").alias("exclusion_reason")))
    active = df.filter(pl.col("payment_limit").is_not_null())
    return active, excluded


def load_crosswalk(zip_path: Path, quarter: str) -> pl.DataFrame:
    member, header, rows = _best_table(
        zip_path, [_is_hcpcs_col, lambda k: k.startswith("ndc")])
    i_code = _pick(header, _is_hcpcs_col)
    i_ndc = _pick(header, "ndc2", "ndc", "ndc11", lambda k: k.startswith("ndc"))
    i_name = _pick(header, "drugname")
    i_lab = _pick(header, "labelername", "labeler")
    i_dose = _pick(header, "hcpcsdosage", "hcpcscodedosage", "dosage")
    i_size = _pick(header, "pkgsize")
    i_pqty = _pick(header, "pkgqty")
    i_bu = _pick(header, "billunits")
    i_bup = _pick(header, "billunitspkg")
    start, end = quarter_bounds(quarter)
    digest = sha256(zip_path)
    write_sha256_sidecar(zip_path, digest)

    def cell(r, i):
        return r[i].strip() if i is not None and i < len(r) else ""

    out, bad_ndc = [], 0
    for r in rows:
        code = norm_hcpcs(cell(r, i_code))
        if code is None:
            continue
        ndc = norm_ndc(cell(r, i_ndc))
        if ndc is None:
            bad_ndc += 1
            continue
        out.append({
            "hcpcs": code,
            "ndc11": ndc,
            "drug_name": cell(r, i_name) or None,
            "labeler": cell(r, i_lab) or None,
            "dosage_text": cell(r, i_dose) or None,
            "pkg_size": to_float(cell(r, i_size)),
            "pkg_qty": to_float(cell(r, i_pqty)),
            "bill_units": to_float(cell(r, i_bu)),
            "bill_units_pkg": to_float(cell(r, i_bup)),
            "quarter": quarter,
            "effective_start": start,
            "effective_end": end,
            "source_file": rel(zip_path),
            "source_member": member,
            "source_sha256": digest,
        })
    df = pl.DataFrame(out)
    print(f"  Crosswalk {quarter}: {len(df):,} NDC rows ({bad_ndc} rows with unusable NDC) "
          f"from {member}")
    return df


def classify(zip_path: Path) -> str | None:
    n = zip_path.name.lower()
    if "seasonal" in n or "vaccine" in n:
        return None
    if "crosswalk" in n:
        return "crosswalk"
    # NOC tables are not keyed by HCPCS and cannot support the code-level ASP
    # comparison. Do not let them replace the quarterly ASP pricing file.
    if re.search(r"(?:^|[_-])noc(?:[_-]|$)", n):
        return None
    if "payment_limit" in n or "payment-limit" in n or "asp_pricing" in n or "pricing_file" in n:
        return "asp"
    return None


def _revision_key(path: Path) -> tuple:
    """Prefer explicit CMS revised files and the latest valid MMDDYY suffix."""
    dates = []
    for token in re.findall(r"(?<!\d)(\d{6})(?!\d)", path.stem):
        try:
            dates.append(date(2000 + int(token[4:]), int(token[:2]), int(token[2:4])))
        except ValueError:
            continue
    return ("updated" in path.stem.casefold(), max(dates, default=date.min),
            path.stat().st_mtime_ns, path.name.casefold())


def _merge_unpriced(frames: list[pl.DataFrame], replaced_quarters: list[str]
                    ) -> pl.DataFrame:
    """Combine exclusions while dropping stale exceptions for replaced quarters."""
    kept = []
    empty_template = None
    for frame in frames:
        if "exclusion_reason" not in frame.columns:
            frame = frame.with_columns(
                pl.lit("missing_payment_limit").alias("exclusion_reason"))
        if empty_template is None:
            empty_template = frame.head(0)
        if frame.is_empty():
            continue
        if replaced_quarters:
            frame = frame.filter(~pl.col("quarter").is_in(replaced_quarters))
        if not frame.is_empty():
            kept.append(frame)
    if not kept:
        return empty_template if empty_template is not None else pl.DataFrame()
    return pl.concat(kept, how="diagonal_relaxed").unique(maintain_order=True)


def _commit_parquets(outputs: list[tuple[Path, Path]]) -> None:
    """Replace a related set of Parquet files with rollback if any replace fails."""
    backups: dict[Path, Path] = {}
    existed = {target: target.exists() for _, target in outputs}
    try:
        for _, target in outputs:
            if target.exists():
                backup = target.with_name(target.name + ".bak")
                import shutil
                shutil.copy2(target, backup)
                backups[target] = backup
        try:
            for tmp, target in outputs:
                os.replace(tmp, target)
        except Exception:
            for _, target in outputs:
                if target in backups:
                    os.replace(backups[target], target)
                elif not existed[target]:
                    target.unlink(missing_ok=True)
            raise
    finally:
        for tmp, _ in outputs:
            tmp.unlink(missing_ok=True)
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def main() -> int:
    p = paths()
    raw = p["raw"]
    zips = sorted({*raw.glob("cms_asp/**/*.zip"), *raw.glob("cms_crosswalk/**/*.zip")})
    chosen: dict[tuple[str, str], Path] = {}
    for z in zips:
        kind, q = classify(z), quarter_from_filename(z.name)
        if kind is None or q is None:
            print(f"  skip (not an ASP/crosswalk quarter file): {z.name}")
            continue
        prior = chosen.get((kind, q))
        if prior is None:
            chosen[(kind, q)] = z
        elif _revision_key(z) > _revision_key(prior):
            print(f"  NOTE two {kind} files for {q}; using {z.name} over {prior.name}")
            chosen[(kind, q)] = z
        else:
            print(f"  NOTE two {kind} files for {q}; keeping {prior.name} over {z.name}")

    if not chosen:
        asp_snapshot = p["ref"] / "ref_asp.parquet"
        if asp_snapshot.is_file():
            snapshot = pl.read_parquet(asp_snapshot)
            active, newly_excluded = _split_unpriced_asp(snapshot, asp_snapshot.name)
            excluded_path = p["ref"] / "ref_asp_excluded.parquet"
            old_excluded = ([pl.read_parquet(excluded_path)]
                            if excluded_path.is_file() else [])
            all_excluded = _merge_unpriced(
                [*old_excluded, newly_excluded], replaced_quarters=[])
            if len(newly_excluded):
                p["ref"].mkdir(parents=True, exist_ok=True)
                active_tmp = asp_snapshot.with_name(asp_snapshot.name + ".part")
                active.write_parquet(active_tmp, compression="zstd")
                outputs = [(active_tmp, asp_snapshot)]
                if len(all_excluded) or excluded_path.exists():
                    excluded_tmp = excluded_path.with_name(excluded_path.name + ".part")
                    all_excluded.write_parquet(excluded_tmp, compression="zstd")
                    outputs.append((excluded_tmp, excluded_path))
                _commit_parquets(outputs)
                print(f"Removed {len(newly_excluded)} unpriced rows from ref_asp.parquet; "
                      f"preserved them in {excluded_path.name}.")
            print("No new ASP/crosswalk source files; using the saved Parquet snapshots.")
            return 0
        print("No ASP or crosswalk ZIPs found under", raw)
        return 1

    asp_results = [load_payment_limit(z, q) for (k, q), z in sorted(chosen.items())
                   if k == "asp"]
    asp = [active for active, _ in asp_results]
    asp_excluded = [excluded for _, excluded in asp_results]
    xw = [load_crosswalk(z, q) for (k, q), z in sorted(chosen.items()) if k == "crosswalk"]

    p["ref"].mkdir(parents=True, exist_ok=True)
    outputs = []
    asp_target = p["ref"] / "ref_asp.parquet"
    excluded_target = p["ref"] / "ref_asp_excluded.parquet"
    if asp or asp_target.is_file():
        replaced_quarters = (pl.concat(asp, how="vertical_relaxed")["quarter"].unique().to_list()
                             if asp else [])
        prior_exclusions = ([pl.read_parquet(excluded_target)]
                            if excluded_target.is_file() else [])
        if asp_target.is_file():
            prior_active = pl.read_parquet(asp_target)
            prior_active, legacy_exclusions = _split_unpriced_asp(
                prior_active, asp_target.name)
            prior_exclusions.append(legacy_exclusions)
            if replaced_quarters:
                prior_active = prior_active.filter(
                    ~pl.col("quarter").is_in(replaced_quarters))
        else:
            prior_active = None

        active_frames = ([prior_active] if prior_active is not None else []) + asp
        if active_frames:
            combined_active = pl.concat(active_frames, how="vertical_relaxed").sort("quarter")
            if combined_active.is_empty():
                raise ValueError("Refusing to replace ref_asp.parquet with an empty dataset")
            asp_tmp = asp_target.with_name(asp_target.name + ".part")
            combined_active.write_parquet(asp_tmp, compression="zstd")
            outputs.append((asp_tmp, asp_target))

        all_excluded = _merge_unpriced(
            [*prior_exclusions, *asp_excluded], replaced_quarters=replaced_quarters)
        if len(all_excluded) or excluded_target.exists():
            excluded_tmp = excluded_target.with_name(excluded_target.name + ".part")
            all_excluded.write_parquet(excluded_tmp, compression="zstd")
            outputs.append((excluded_tmp, excluded_target))

    for frames, filename in ((xw, "ref_crosswalk.parquet"),):
        if not frames:
            continue
        target = p["ref"] / filename
        tmp = target.with_name(target.name + ".part")
        incoming = pl.concat(frames, how="vertical_relaxed")
        if target.is_file():
            existing_xw = pl.read_parquet(target)
            incoming_quarters = incoming["quarter"].unique().to_list()
            existing_xw = existing_xw.filter(~pl.col("quarter").is_in(incoming_quarters))
            incoming = pl.concat([existing_xw, incoming], how="vertical_relaxed").sort("quarter")
        incoming.write_parquet(tmp, compression="zstd")
        count = pl.scan_parquet(tmp).select(pl.len()).collect().item()
        if count <= 0:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Refusing to replace {filename} with an empty dataset")
        outputs.append((tmp, target))
    if outputs:
        _commit_parquets(outputs)
    print(f"Wrote {len(asp)} ASP quarters and {len(xw)} crosswalk quarters to {rel(p['ref'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
