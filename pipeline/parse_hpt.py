"""Parse hospital price files (CMS template v2.x) into drug rate rows.

Input : data/raw_essential_inputs/hospital_mrf/<system>/<date>/<price files>
        Formats: CMS JSON, CMS CSV "tall", CMS CSV "wide", and ZIPs holding them.
Output: data/hpt/norm/hpt_drug_rates.parquet   one row per item x setting x payer/plan
        data/hpt/norm/hpt_file_quality.parquet one row per file (what was found)

Only rows for drugs in config/drugs_in_scope.yaml are kept. A row is in scope
when it carries an in-scope HCPCS code, or an NDC that the CMS crosswalk maps
to an in-scope HCPCS code.

Run after pipeline.load_asp:  python -m pipeline.parse_hpt
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
import io
import os
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator

import ijson
import polars as pl

from .common import (drugs_in_scope, load_yaml, norm_hcpcs, norm_ndc, paths, payer_group,
                     rel, sha256, to_float)

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

RATE_COLS = ["gross_charge", "discounted_cash", "negotiated_dollar", "negotiated_percentage",
             "estimated_amount", "median_amount", "p10_amount", "p90_amount"]


# ---------- scope ----------

class Scope:
    def __init__(self, ref_dir: Path):
        self.hcpcs = {d["hcpcs"] for d in drugs_in_scope()}
        self.ndc_to_hcpcs: dict[str, str] = {}
        xw = ref_dir / "ref_crosswalk.parquet"
        if xw.exists():
            df = (pl.read_parquet(xw, columns=["hcpcs", "ndc11"])
                  .filter(pl.col("hcpcs").is_in(list(self.hcpcs))).unique())
            self.ndc_to_hcpcs = dict(zip(df["ndc11"], df["hcpcs"]))

    def match(self, codes: list[tuple[str, str]]) -> tuple[str | None, str | None, str | None]:
        """codes = [(code, type)] -> (hcpcs, ndc11, matched_via)."""
        hcpcs = ndc = via = None
        for code, typ in codes:
            t = (typ or "").upper()
            if t in ("HCPCS", "CPT") or (not t and norm_hcpcs(code)):
                c = norm_hcpcs(code)
                if c in self.hcpcs:
                    hcpcs, via = c, "hcpcs"
            elif t == "NDC":
                n = norm_ndc(code)
                if n:
                    ndc = n
        if hcpcs is None and ndc and ndc in self.ndc_to_hcpcs:
            hcpcs, via = self.ndc_to_hcpcs[ndc], "ndc_crosswalk"
        return hcpcs, ndc, via


# ---------- file opening ----------

def _sniff_json(head: bytes) -> bool:
    s = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return s[:1] in (b"{", b"[")


class _PrefixStream:
    """File-like reader that replays a short prefix before the underlying stream."""
    def __init__(self, prefix: bytes, stream):
        self.prefix = prefix
        self.stream = stream

    def read(self, size=-1):
        if size is None or size < 0:
            value, self.prefix = self.prefix, b""
            return value + self.stream.read()
        if not self.prefix:
            return self.stream.read(size)
        value = self.prefix[:size]
        self.prefix = self.prefix[size:]
        if len(value) < size:
            value += self.stream.read(size - len(value))
        return value


@contextmanager
def _json_stream(opener):
    with opener() as stream:
        prefix = stream.read(3)
        if prefix != b"\xef\xbb\xbf":
            yield _PrefixStream(prefix, stream)
        else:
            yield stream


def iter_sources(path: Path) -> Iterator[tuple[str, callable]]:
    """Yield (label, opener) for each price table in a file or ZIP."""
    if zipfile.is_zipfile(path):
        zf = zipfile.ZipFile(path)
        for m in zf.namelist():
            if (m.endswith("/") or m.startswith("__MACOSX") or
                    m.casefold().endswith(".parquet")):
                continue
            yield m, (lambda m=m: zf.open(m))
    else:
        yield path.name, (lambda: path.open("rb"))


# ---------- JSON ----------

def parse_json(opener, scope: Scope, stats: dict) -> Iterator[dict]:
    """Two streaming passes: header fields, then items. Memory stays small."""
    header: dict = {}
    with _json_stream(opener) as fh:
        for prefix, event, value in ijson.parse(fh):
            if prefix == "standard_charge_information" and event == "start_array":
                break
            if "." not in prefix and event in ("string", "number", "boolean"):
                header[prefix] = value
    stats["hospital_name"] = header.get("hospital_name")
    stats["file_last_updated"] = header.get("last_updated_on")
    stats["cms_version"] = header.get("version")
    stats["format"] = "json"
    with _json_stream(opener) as fh:
        yield from _json_items(fh, scope, stats)


def _json_items(fh, scope: Scope, stats: dict) -> Iterator[dict]:
    for item in ijson.items(fh, "standard_charge_information.item", use_float=True):
        stats["items_scanned"] += 1
        codes = [(str(c.get("code", "")), str(c.get("type", "")))
                 for c in item.get("code_information", []) or []]
        hcpcs, ndc, via = scope.match(codes)
        if hcpcs is None:
            continue
        drug = item.get("drug_information") or {}
        base = {
            "hcpcs": hcpcs, "ndc11": ndc, "matched_via": via,
            "description": item.get("description"),
            "drug_unit": to_float(drug.get("unit")),
            "drug_unit_type": drug.get("type"),
        }
        for sc in item.get("standard_charges", []) or []:
            common = {
                **base,
                "setting": sc.get("setting"),
                "billing_class": sc.get("billing_class"),
                "modifiers": ",".join(sc.get("modifier_code") or []) if isinstance(
                    sc.get("modifier_code"), list) else sc.get("modifier_code"),
                "gross_charge": to_float(sc.get("gross_charge")),
                "discounted_cash": to_float(sc.get("discounted_cash")),
            }
            payers = sc.get("payers_information") or []
            if not payers:
                yield {**common, "payer_name": None, "plan_name": None}
            for pi in payers:
                yield {
                    **common,
                    "payer_name": pi.get("payer_name"),
                    "plan_name": pi.get("plan_name"),
                    "negotiated_dollar": to_float(pi.get("standard_charge_dollar")),
                    "negotiated_percentage": to_float(pi.get("standard_charge_percentage")),
                    "negotiated_algorithm": pi.get("standard_charge_algorithm"),
                    "estimated_amount": to_float(pi.get("estimated_amount")),
                    "median_amount": to_float(pi.get("median_amount")),
                    "p10_amount": to_float(pi.get("10th_percentile")),
                    "p90_amount": to_float(pi.get("90th_percentile")),
                    "methodology": pi.get("methodology"),
                }


# ---------- CSV (tall and wide) ----------

def _csv_rows(fh) -> Iterator[list[str]]:
    text = io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace", newline="")
    yield from csv.reader(text)


def parse_csv(opener, scope: Scope, stats: dict) -> Iterator[dict]:
    with opener() as fh:
        yield from _csv_items(fh, scope, stats)


def _csv_items(fh, scope: Scope, stats: dict) -> Iterator[dict]:
    rows = _csv_rows(fh)
    pre: list[list[str]] = []
    header = None
    for _ in range(6):
        r = next(rows, None)
        if r is None:
            break
        if any(c.strip().lower() == "description" for c in r):
            orig = [c.strip() for c in r]       # keeps payer/plan names as written
            header = [c.lower() for c in orig]
            break
        pre.append(r)
    if header is None:
        stats["format"] = "csv_unrecognized"
        stats["error"] = "no 'description' header row in the first 6 rows"
        return
    if len(pre) >= 2:
        meta = {k.strip().lower(): v for k, v in zip(pre[0], pre[1])}
        stats["hospital_name"] = meta.get("hospital_name")
        stats["file_last_updated"] = meta.get("last_updated_on")
        stats["cms_version"] = meta.get("version")

    yield from _tabular_items(orig, rows, scope, stats)


def _cell(row, index):
    if index is None or index >= len(row) or row[index] is None:
        return None
    value = str(row[index]).strip()
    return value or None


def _tabular_items(orig: list[str], rows, scope: Scope, stats: dict) -> Iterator[dict]:
    """Normalize CMS tall/wide rows from CSV or a Parquet-backed table."""
    header = [c.strip().lower() for c in orig]
    idx = {h: i for i, h in enumerate(header)}
    code_cols = []
    for h, i in idx.items():
        m = re.fullmatch(r"code(?:\||_)(\d+)", h)
        if m:
            number = m.group(1)
            type_index = idx.get(f"code|{number}|type", idx.get(f"code_{number}_type"))
            code_cols.append((i, type_index))

    tall = "payer_name" in idx
    prefix = "parquet" if stats.get("source_parquet") else "csv"
    stats["format"] = f"{prefix}_{'tall' if tall else 'wide'}"
    wide = {}
    if not tall:
        for i, h in enumerate(header):
            parts, oparts = h.split("|"), orig[i].split("|")
            if len(parts) == 4 and parts[0] == "standard_charge":
                wide.setdefault((oparts[1], oparts[2]), {})[parts[3]] = i
            elif len(parts) == 3 and parts[0] in ("estimated_amount", "median_amount",
                                                  "10th_percentile", "90th_percentile",
                                                  "additional_payer_notes"):
                wide.setdefault((oparts[1], oparts[2]), {})[parts[0]] = i

    def g(row, key):
        return _cell(row, idx.get(key))

    def gi(row, index):
        return _cell(row, index)

    for row in rows:
        stats["items_scanned"] += 1
        codes = [(gi(row, ci) or "", gi(row, ti) or "") for ci, ti in code_cols]
        hcpcs, ndc, via = scope.match(codes)
        if hcpcs is None:
            continue
        common = {
            "hcpcs": hcpcs, "ndc11": ndc, "matched_via": via,
            "description": g(row, "description"),
            "setting": g(row, "setting"),
            "billing_class": g(row, "billing_class"),
            "modifiers": g(row, "modifiers"),
            "drug_unit": to_float(g(row, "drug_unit_of_measurement")),
            "drug_unit_type": g(row, "drug_type_of_measurement"),
            "gross_charge": to_float(g(row, "standard_charge|gross")),
            "discounted_cash": to_float(g(row, "standard_charge|discounted_cash")),
        }
        if tall:
            yield {
                **common,
                "payer_name": g(row, "payer_name"),
                "plan_name": g(row, "plan_name"),
                "negotiated_dollar": to_float(g(row, "standard_charge|negotiated_dollar")),
                "negotiated_percentage": to_float(g(row, "standard_charge|negotiated_percentage")),
                "negotiated_algorithm": g(row, "standard_charge|negotiated_algorithm"),
                "estimated_amount": to_float(g(row, "estimated_amount")),
                "median_amount": to_float(g(row, "median_amount")),
                "p10_amount": to_float(g(row, "10th_percentile")),
                "p90_amount": to_float(g(row, "90th_percentile")),
                "methodology": g(row, "standard_charge|methodology"),
            }
        else:
            any_payer = False
            for (payer, plan), cols in wide.items():
                vals = {
                    "negotiated_dollar": to_float(gi(row, cols.get("negotiated_dollar"))),
                    "negotiated_percentage": to_float(gi(row, cols.get("negotiated_percentage"))),
                    "negotiated_algorithm": gi(row, cols.get("negotiated_algorithm")),
                    "estimated_amount": to_float(gi(row, cols.get("estimated_amount"))),
                    "median_amount": to_float(gi(row, cols.get("median_amount"))),
                    "p10_amount": to_float(gi(row, cols.get("10th_percentile"))),
                    "p90_amount": to_float(gi(row, cols.get("90th_percentile"))),
                    "methodology": gi(row, cols.get("methodology")),
                }
                if all(v is None for v in vals.values()):
                    continue
                any_payer = True
                yield {**common, "payer_name": payer, "plan_name": plan, **vals}
            if not any_payer:
                yield {**common, "payer_name": None, "plan_name": None}


def parse_parquet(path: Path, scope: Scope, stats: dict) -> Iterator[dict]:
    """Stream a Parquet-converted hospital MRF through the standard normalizer."""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    columns = parquet.schema_arrow.names
    if not any(name.strip().casefold() == "description" for name in columns):
        raise ValueError("Parquet MRF has no description column")
    indexes = {name.strip().casefold(): i for i, name in enumerate(columns)}
    stats["source_parquet"] = True

    def rows():
        first_batch = True
        for batch in parquet.iter_batches(batch_size=4096):
            records = batch.to_pylist()
            if first_batch and records:
                first = records[0]
                for field, output in (("hospital_name", "hospital_name"),
                                      ("last_updated_on", "file_last_updated"),
                                      ("version", "cms_version")):
                    if field in indexes:
                        stats[output] = first.get(columns[indexes[field]])
                first_batch = False
            for record in records:
                yield [record.get(name) for name in columns]

    yield from _tabular_items(columns, rows(), scope, stats)


def parse_normalized_archive(
    archive_path: Path,
    scope: Scope,
    known_sources: set[tuple[str, str, str]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Read the pre-normalized per-hospital Parquets in ref_hospital_mrf.zip.

    The archive contains one tall Parquet table per hospital. Project only the
    fields needed by the comparison and filter batches to HCPCS/NDC candidates
    before converting rows to Python objects; the archive has over 170 million
    service rows, most outside the drug scope.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    selected = [
        "ccn", "hospital_name", "last_updated_on", "mrf_version", "description",
        "code_1", "code_1_type", "code_2", "code_2_type", "code_3", "code_3_type",
        "code_4", "code_4_type", "modifiers", "billing_class", "drug_unit", "drug_type",
        "gross_charge", "discounted_cash", "payer_name", "plan_name",
        "negotiated_dollar", "negotiated_percentage", "negotiated_algorithm",
        "estimated_amount", "median_amount", "pct_10", "pct_90", "methodology",
        "setting", "hcpcs", "ndc", "payer_group", "effective_start", "effective_end",
        "source_file", "source_sha256",
    ]
    hcpcs_values = pa.array(sorted(scope.hcpcs), type=pa.string())
    ndc_values_set = set(scope.ndc_to_hcpcs)
    # Include the dashed 10-digit representations accepted by norm_ndc so the
    # Arrow filter can discard unrelated NDCs before Python-level processing.
    for value in tuple(ndc_values_set):
        if len(value) != 11 or not value.isdigit():
            continue
        ndc_values_set.add(f"{value[:5]}-{value[5:9]}-{value[9:]}")
        if value[0] == "0":
            ndc_values_set.add(f"{value[1:5]}-{value[5:9]}-{value[9:]}")
        if value[5] == "0":
            ndc_values_set.add(f"{value[:5]}-{value[6:9]}-{value[9:]}")
        if value[9] == "0":
            ndc_values_set.add(f"{value[:5]}-{value[5:9]}-{value[10:]}")
    ndc_values = pa.array(sorted(ndc_values_set), type=pa.string())
    rows: list[dict] = []
    quality: list[dict] = []
    with zipfile.ZipFile(archive_path) as zf:
        members = sorted(n for n in zf.namelist() if n.casefold().endswith(".parquet"))
        if not members:
            raise ValueError(f"No Parquet tables found in {archive_path}")
        for member in members:
            info = zf.getinfo(member)
            fingerprint = f"{info.CRC:08x}:{info.file_size}"
            source_key = (rel(archive_path), member, fingerprint)
            if known_sources and source_key in known_sources:
                print(f"  [CMS archive] {member}: unchanged, using saved Parquet rows")
                continue
            stats = {
                "system": "CMS HPT archive", "source_file": rel(archive_path),
                "source_member": member, "source_sha256": None,
                "input_fingerprint": fingerprint, "locations": "",
                "items_scanned": 0, "format": "normalized_parquet", "error": None,
                "hospital_name": None, "file_last_updated": None, "cms_version": None,
            }
            out: list[dict] = []
            try:
                with zf.open(member) as stream:
                    parquet = pq.ParquetFile(stream)
                    available = set(parquet.schema_arrow.names)
                    columns = [name for name in selected if name in available]
                    probe_columns = [name for name in ("hcpcs", "ndc") if name in available]
                    for row_group in range(parquet.num_row_groups):
                        probe = parquet.read_row_group(row_group, columns=probe_columns)
                        stats["items_scanned"] += probe.num_rows
                        mask = pc.is_in(probe.column("hcpcs"), value_set=hcpcs_values)
                        if "ndc" in probe.column_names and len(ndc_values_set):
                            mask = pc.or_(mask, pc.is_in(probe.column("ndc"), value_set=ndc_values))
                        if row_group == 0 and probe.num_rows:
                            meta_cols = [name for name in ("hospital_name", "last_updated_on",
                                        "mrf_version", "source_file", "source_sha256", "ccn")
                                         if name in available]
                            first = parquet.read_row_group(0, columns=meta_cols).slice(0, 1).to_pylist()[0]
                            stats["hospital_name"] = first.get("hospital_name") or _hospital_from_filename(
                                Path(first.get("source_file") or member))
                            stats["file_last_updated"] = first.get("last_updated_on")
                            stats["cms_version"] = first.get("mrf_version")
                            stats["source_sha256"] = first.get("source_sha256")
                            stats["locations"] = str(first.get("ccn") or "")
                        if not pc.any(mask).as_py():
                            continue
                        batch = parquet.read_row_group(row_group, columns=columns)
                        candidates = batch.filter(mask).to_pylist()
                        for raw in candidates:
                            codes = [(raw.get(f"code_{i}") or "", raw.get(f"code_{i}_type") or "")
                                     for i in range(1, 5)]
                            if raw.get("hcpcs"):
                                codes.append((raw["hcpcs"], "HCPCS"))
                            if raw.get("ndc"):
                                codes.append((raw["ndc"], "NDC"))
                            hcpcs, ndc11, via = scope.match(codes)
                            if hcpcs is None:
                                continue
                            hospital_name = raw.get("hospital_name") or _hospital_from_filename(
                                Path(raw.get("source_file") or member))
                            if stats["hospital_name"] is None:
                                stats["hospital_name"] = hospital_name
                                stats["file_last_updated"] = raw.get("last_updated_on")
                                stats["cms_version"] = raw.get("mrf_version")
                                stats["source_sha256"] = raw.get("source_sha256")
                                stats["locations"] = str(raw.get("ccn") or "")
                            out.append({
                                "system": stats["system"], "hospital_name": hospital_name,
                                "locations": str(raw.get("ccn") or ""), "hcpcs": hcpcs,
                                "ndc11": ndc11, "matched_via": via,
                                "description": raw.get("description"), "setting": raw.get("setting"),
                                "billing_class": raw.get("billing_class"),
                                "modifiers": raw.get("modifiers"),
                                "drug_unit": to_float(raw.get("drug_unit")),
                                "drug_unit_type": raw.get("drug_type"),
                                "payer_name": raw.get("payer_name"), "plan_name": raw.get("plan_name"),
                                "payer_group": raw.get("payer_group") or payer_group(raw.get("payer_name")),
                                "gross_charge": to_float(raw.get("gross_charge")),
                                "discounted_cash": to_float(raw.get("discounted_cash")),
                                "negotiated_dollar": to_float(raw.get("negotiated_dollar")),
                                "negotiated_percentage": to_float(raw.get("negotiated_percentage")),
                                "negotiated_algorithm": raw.get("negotiated_algorithm"),
                                "estimated_amount": to_float(raw.get("estimated_amount")),
                                "median_amount": to_float(raw.get("median_amount")),
                                "p10_amount": to_float(raw.get("pct_10")),
                                "p90_amount": to_float(raw.get("pct_90")),
                                "methodology": raw.get("methodology"),
                                "effective_start": raw.get("effective_start"),
                                "effective_end": raw.get("effective_end"),
                                "file_last_updated": _parse_date(raw.get("last_updated_on")),
                                "cms_version": raw.get("mrf_version"),
                                "source_file": rel(archive_path),
                                "source_member": member,
                                "source_sha256": raw.get("source_sha256"),
                            })
                stats["drug_rows"] = len(out)
                stats["hcpcs_found"] = ",".join(sorted({r["hcpcs"] for r in out}))
                quality.append(stats)
                rows.extend(out)
                print(f"  [CMS archive] {member}: {stats['items_scanned']:,} items, "
                      f"{len(out):,} drug rows")
            except Exception as e:  # noqa: BLE001 -- keep source-specific failures visible
                stats["error"] = f"{type(e).__name__}: {e}"[:500]
                stats["drug_rows"] = len(out)
                stats["hcpcs_found"] = ",".join(sorted({r["hcpcs"] for r in out}))
                quality.append(stats)
                rows.extend(out)
                print(f"  [CMS archive] {member}: ERROR {stats['error']}")
    return rows, quality


def parse_normalized_parquet_file(path: Path, scope: Scope, fingerprint: str) -> tuple[list[dict], dict]:
    """Normalize a standalone CMS-shaped Parquet table using the same path as ZIP inputs."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    names_available = set(parquet.schema_arrow.names)
    wanted = [
        "ccn", "hospital_name", "last_updated_on", "mrf_version", "description",
        "code_1", "code_1_type", "code_2", "code_2_type", "code_3", "code_3_type",
        "code_4", "code_4_type", "modifiers", "billing_class", "drug_unit", "drug_type",
        "gross_charge", "discounted_cash", "payer_name", "plan_name", "negotiated_dollar",
        "negotiated_percentage", "negotiated_algorithm", "estimated_amount", "median_amount",
        "pct_10", "pct_90", "methodology", "setting", "hcpcs", "ndc", "payer_group",
        "effective_start", "effective_end", "source_file", "source_sha256",
    ]
    columns = [name for name in wanted if name in names_available]
    if not {"hcpcs", "payer_name", "negotiated_dollar"} <= set(columns):
        raise ValueError("Normalized MRF Parquet is missing HCPCS or negotiated-rate columns")

    ndc_candidates = set(scope.ndc_to_hcpcs)
    for value in tuple(ndc_candidates):
        if len(value) != 11 or not value.isdigit():
            continue
        ndc_candidates.add(f"{value[:5]}-{value[5:9]}-{value[9:]}")
        if value[0] == "0":
            ndc_candidates.add(f"{value[1:5]}-{value[5:9]}-{value[9:]}")
        if value[5] == "0":
            ndc_candidates.add(f"{value[:5]}-{value[6:9]}-{value[9:]}")
        if value[9] == "0":
            ndc_candidates.add(f"{value[:5]}-{value[5:9]}-{value[10:]}")
    hcpcs_values = pa.array(sorted(scope.hcpcs), type=pa.string())
    ndc_values = pa.array(sorted(ndc_candidates), type=pa.string())
    stats = {
        "system": "Parquet reference", "source_file": rel(path), "source_member": path.name,
        "source_sha256": fingerprint, "input_fingerprint": fingerprint, "locations": "",
        "items_scanned": 0, "format": "normalized_parquet", "error": None,
        "hospital_name": None, "file_last_updated": None, "cms_version": None,
    }
    rows = []
    probe_columns = [name for name in ("hcpcs", "ndc") if name in names_available]
    for row_group in range(parquet.num_row_groups):
        probe = parquet.read_row_group(row_group, columns=probe_columns)
        stats["items_scanned"] += probe.num_rows
        mask = pc.is_in(probe.column("hcpcs"), value_set=hcpcs_values)
        if "ndc" in probe.column_names and ndc_candidates:
            mask = pc.or_(mask, pc.is_in(probe.column("ndc"), value_set=ndc_values))
        if row_group == 0 and probe.num_rows:
            meta_cols = [name for name in ("hospital_name", "last_updated_on", "mrf_version", "ccn")
                         if name in names_available]
            first = parquet.read_row_group(0, columns=meta_cols).slice(0, 1).to_pylist()[0]
            stats["hospital_name"] = first.get("hospital_name") or _hospital_from_filename(path)
            stats["file_last_updated"] = first.get("last_updated_on")
            stats["cms_version"] = first.get("mrf_version")
            stats["locations"] = str(first.get("ccn") or "")
            stats["source_sha256"] = first.get("source_sha256") or fingerprint
        if not pc.any(mask).as_py():
            continue
        batch = parquet.read_row_group(row_group, columns=columns)
        candidates = batch.filter(mask).to_pylist()
        for raw in candidates:
            codes = [(raw.get(f"code_{i}") or "", raw.get(f"code_{i}_type") or "")
                     for i in range(1, 5)]
            if raw.get("hcpcs"):
                codes.append((raw["hcpcs"], "HCPCS"))
            if raw.get("ndc"):
                codes.append((raw["ndc"], "NDC"))
            hcpcs, ndc11, via = scope.match(codes)
            if hcpcs is None:
                continue
            hospital_name = raw.get("hospital_name") or _hospital_from_filename(path)
            rows.append({
                "system": stats["system"], "hospital_name": hospital_name,
                "locations": str(raw.get("ccn") or ""), "hcpcs": hcpcs, "ndc11": ndc11,
                "matched_via": via, "description": raw.get("description"),
                "setting": raw.get("setting"), "billing_class": raw.get("billing_class"),
                "modifiers": raw.get("modifiers"), "drug_unit": to_float(raw.get("drug_unit")),
                "drug_unit_type": raw.get("drug_type"), "payer_name": raw.get("payer_name"),
                "plan_name": raw.get("plan_name"),
                "payer_group": raw.get("payer_group") or payer_group(raw.get("payer_name")),
                "gross_charge": to_float(raw.get("gross_charge")),
                "discounted_cash": to_float(raw.get("discounted_cash")),
                "negotiated_dollar": to_float(raw.get("negotiated_dollar")),
                "negotiated_percentage": to_float(raw.get("negotiated_percentage")),
                "negotiated_algorithm": raw.get("negotiated_algorithm"),
                "estimated_amount": to_float(raw.get("estimated_amount")),
                "median_amount": to_float(raw.get("median_amount")),
                "p10_amount": to_float(raw.get("pct_10")), "p90_amount": to_float(raw.get("pct_90")),
                "methodology": raw.get("methodology"), "effective_start": raw.get("effective_start"),
                "effective_end": raw.get("effective_end"),
                "file_last_updated": _parse_date(raw.get("last_updated_on")),
                "cms_version": raw.get("mrf_version"), "source_file": rel(path),
                "source_member": path.name,
                "source_sha256": raw.get("source_sha256") or fingerprint,
            })
    stats["drug_rows"] = len(rows)
    stats["hcpcs_found"] = ",".join(sorted({r["hcpcs"] for r in rows}))
    return rows, stats


# ---------- driver ----------

def _parse_date(s: object) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _download_log(raw: Path) -> dict[str, str]:
    log = raw / "hospital_mrf" / "mrf_download_log.csv"
    if not log.exists():
        return {}
    with log.open(newline="", encoding="utf-8") as f:
        return {r["file_name"]: r.get("locations", "") for r in csv.DictReader(f)
                if r.get("file_name")}


def price_files(raw: Path, skip: set[str]) -> Iterable[tuple[str, Path]]:
    root = raw / "hospital_mrf"
    for system_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if system_dir.name in skip:
            continue
        for f in sorted(system_dir.rglob("*")):
            if f.is_file() and f.name != "cms-hpt.txt" and not f.name.endswith((".part", ".sha256")):
                yield system_dir.name, f


def _parquet_is_hpt(path: Path) -> bool:
    """Classify a Parquet table by its columns, independent of its filename."""
    try:
        import pyarrow.parquet as pq
        names = {name.strip().casefold() for name in pq.ParquetFile(path).schema_arrow.names}
    except Exception:  # invalid/partial Parquet files are not sources
        return False
    normalized = {"hcpcs", "payer_name", "plan_name", "negotiated_dollar"} <= names
    code_columns = any(re.fullmatch(r"code\|\d+", n) or re.fullmatch(r"code_\d+", n)
                       for n in names)
    rates = bool(names & {"gross_charge", "standard_charge|gross", "negotiated_dollar",
                          "standard_charge|negotiated_dollar"})
    raw_table = "description" in names and code_columns and rates
    return normalized or raw_table


def parquet_price_files(ref_dir: Path) -> list[Path]:
    """Find hospital MRF Parquets recursively by schema; skip unrelated CMS refs."""
    candidates = []
    seen: set[str] = set()
    for path in sorted(ref_dir.rglob("*.parquet")):
        name = path.name.casefold()
        if (".incomplete." in name or name.endswith((".part.parquet", ".bak.parquet")) or
                path.name.startswith("_")):
            continue
        if not _parquet_is_hpt(path):
            continue
        digest = sha256(path)
        if digest in seen:
            continue
        seen.add(digest)
        candidates.append(path)
    return candidates


def _csv_is_hpt(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            for line_no, row in enumerate(csv.reader(f)):
                keys = {c.strip().casefold() for c in row}
                if "description" in keys:
                    return any(re.fullmatch(r"code(?:\||_)\d+", k) for k in keys) and any(
                        "standard_charge" in k or k == "payer_name" for k in keys)
                if line_no >= 20:
                    break
    except (OSError, csv.Error):
        return False
    return False


def reference_raw_price_files(ref_dir: Path) -> list[Path]:
    """Discover raw CMS MRF files placed anywhere under data/ref."""
    found = []
    for path in sorted(ref_dir.rglob("*")):
        if not path.is_file() or ".incomplete." in path.name.casefold() or path.name.endswith((".part", ".sha256")):
            continue
        suffix = path.suffix.casefold()
        if suffix == ".csv" and _csv_is_hpt(path):
            found.append(path)
        elif suffix == ".json":
            try:
                with path.open("rb") as f:
                    if b"standard_charge_information" in f.read(65536):
                        found.append(path)
            except OSError:
                continue
        elif suffix == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    if any(n.casefold().endswith((".csv", ".json")) and
                           ("standardcharge" in n.casefold() or "mrf" in n.casefold())
                           for n in zf.namelist()):
                        found.append(path)
            except (OSError, zipfile.BadZipFile):
                continue
    return found


def normalized_parquet_archives(ref_dir: Path) -> list[Path]:
    """Find ZIPs containing CMS-ready normalized hospital Parquet tables."""
    import pyarrow.parquet as pq

    found = []
    for path in sorted(ref_dir.rglob("*.zip")):
        try:
            with zipfile.ZipFile(path) as zf:
                member = next((m for m in zf.namelist() if m.casefold().endswith(".parquet")), None)
                if member is None:
                    continue
                with zf.open(member) as stream:
                    names = {n.casefold() for n in pq.ParquetFile(stream).schema_arrow.names}
                if {"hospital_name", "hcpcs", "ndc", "payer_name", "negotiated_dollar"} <= names:
                    found.append(path)
        except Exception:  # invalid or unrelated ZIP files are not hospital MRF archives
            continue
    return found


def _hospital_from_filename(path: Path) -> str:
    name = re.sub(r"\.parquet$", "", path.name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\(\d+\)$", "", name)
    name = re.sub(r"(?:_standardcharges|_standard_charges|_mrf)$", "", name,
                  flags=re.IGNORECASE)
    # CMS filenames often start with a numeric CCN/EIN. Keep the remainder as
    # a useful display label when the source file has no embedded metadata.
    name = re.sub(r"^[0-9-]+_", "", name)
    return re.sub(r"[_-]+", " ", name).strip() or path.stem


def parse_file(
    system: str,
    path: Path,
    scope: Scope,
    locations: str,
    known_sources: set[tuple[str, str, str]] | None = None,
) -> tuple[list[dict], list[dict]]:
    rows, quality = [], []
    digest = sha256(path)
    if path.suffix.casefold() == ".parquet" and _parquet_is_hpt(path):
        try:
            import pyarrow.parquet as pq
            names = {n.casefold() for n in pq.ParquetFile(path).schema_arrow.names}
            if {"hcpcs", "payer_name", "plan_name", "negotiated_dollar"} <= names:
                key = (rel(path), path.name, digest)
                if known_sources and key in known_sources:
                    return [], []
                out, stats = parse_normalized_parquet_file(path, scope, digest)
                stats["system"] = system
                stats["locations"] = locations or stats.get("locations", "")
                print(f"  [{system}] {path.name[:70]}: normalized_parquet, "
                      f"{stats['items_scanned']:,} items, {len(out):,} drug rows")
                return out, [stats]
        except Exception as e:  # noqa: BLE001 -- logged below as a source quality error
            stats = {"system": system, "source_file": rel(path), "source_member": path.name,
                     "source_sha256": digest, "input_fingerprint": digest,
                     "locations": locations, "items_scanned": 0,
                     "format": "normalized_parquet", "error": f"{type(e).__name__}: {e}"[:500],
                     "hospital_name": _hospital_from_filename(path), "file_last_updated": None,
                     "cms_version": None, "drug_rows": 0, "hcpcs_found": ""}
            return [], [stats]
    for label, opener in iter_sources(path):
        if known_sources and (rel(path), label, digest) in known_sources:
            continue
        stats = {"system": system, "source_file": rel(path), "source_member": label,
                 "source_sha256": digest, "locations": locations, "items_scanned": 0,
                 "input_fingerprint": digest, "format": None, "error": None, "hospital_name": None,
                 "file_last_updated": None, "cms_version": None}
        out = []
        try:
            if path.suffix.casefold() == ".parquet":
                for r in parse_parquet(path, scope, stats):
                    out.append(r)
                stats["hospital_name"] = stats.get("hospital_name") or _hospital_from_filename(path)
            else:
                with opener() as fh:
                    head = fh.read(4096)
                parser = parse_json if _sniff_json(head) else parse_csv
                parsed = parser(opener, scope, stats)
                for r in parsed:
                    out.append(r)
        except Exception as e:  # noqa: BLE001  -- logged, never silently dropped
            stats["error"] = f"{type(e).__name__}: {e}"[:500]
        for r in out:
            for c in RATE_COLS:
                r.setdefault(c, None)
            r.setdefault("negotiated_algorithm", None)
            r.setdefault("methodology", None)
            # Hospital MRFs do not consistently provide contract-effective
            # dates. Keep the columns and represent unavailable periods as null;
            # file_last_updated remains the observed source snapshot date.
            r.setdefault("effective_start", None)
            r.setdefault("effective_end", None)
            r.update({
                "system": system,
                "hospital_name": stats["hospital_name"],
                "locations": locations,
                "file_last_updated": _parse_date(stats["file_last_updated"]),
                "cms_version": stats["cms_version"],
                "payer_group": payer_group(r.get("payer_name")),
                "source_file": rel(path),
                "source_member": label,
                "source_sha256": digest,
            })
        stats["drug_rows"] = len(out)
        stats["hcpcs_found"] = ",".join(sorted({r["hcpcs"] for r in out}))
        quality.append(stats)
        rows.extend(out)
        safe_label = label[:70].encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace")
        print(f"  [{system}] {safe_label}: {stats['format']}, "
              f"{stats['items_scanned']:,} items, {len(out):,} drug rows"
              + (f"  ERROR {stats['error']}" if stats["error"] else ""))
    return rows, quality


def _quality_key(row: dict) -> tuple[str, str, str] | None:
    fingerprint = row.get("input_fingerprint")
    if not fingerprint:
        return None
    return (str(row.get("source_file") or ""), str(row.get("source_member") or ""),
            str(fingerprint))


def _known_quality_sources(path: Path) -> set[tuple[str, str, str]]:
    if not path.is_file():
        return set()
    quality = pl.read_parquet(path)
    if not {"source_file", "source_member", "input_fingerprint"} <= set(quality.columns):
        return set()
    return {key for row in quality.select(
        "source_file", "source_member", "input_fingerprint").to_dicts()
        if (key := _quality_key(row)) is not None}


def _covered_source_quality(system: str, path: Path, fingerprint: str) -> dict:
    """Remember an older reference table covered by the consolidated HPT archive."""
    return {
        "system": system, "source_file": rel(path), "source_member": path.name,
        "source_sha256": fingerprint, "input_fingerprint": fingerprint,
        "locations": "", "items_scanned": 0, "format": "covered_by_hospital_archive",
        "error": None, "hospital_name": _hospital_from_filename(path),
        "file_last_updated": None, "cms_version": None, "drug_rows": 0,
        "hcpcs_found": "",
    }


SCHEMA = {
    "system": pl.Utf8, "hospital_name": pl.Utf8, "locations": pl.Utf8,
    "hcpcs": pl.Utf8, "ndc11": pl.Utf8, "matched_via": pl.Utf8, "description": pl.Utf8,
    "setting": pl.Utf8, "billing_class": pl.Utf8, "modifiers": pl.Utf8,
    "drug_unit": pl.Float64, "drug_unit_type": pl.Utf8,
    "payer_name": pl.Utf8, "plan_name": pl.Utf8, "payer_group": pl.Utf8,
    **{c: pl.Float64 for c in RATE_COLS},
    "negotiated_algorithm": pl.Utf8, "methodology": pl.Utf8,
    "effective_start": pl.Date, "effective_end": pl.Date,
    "file_last_updated": pl.Date, "cms_version": pl.Utf8,
    "source_file": pl.Utf8, "source_member": pl.Utf8, "source_sha256": pl.Utf8,
}


def main() -> int:
    p = paths()
    cfg = load_yaml("pipeline.yaml")
    scope = Scope(p["ref"])
    if not scope.ndc_to_hcpcs:
        print("NOTE: no crosswalk loaded; NDC-only rows cannot be matched. "
              "Run python -m pipeline.load_asp first.")
    source_root = p["raw"] / "hospital_mrf"
    rates_final = p["hpt_norm"] / "hpt_drug_rates.parquet"
    quality_final = p["hpt_norm"] / "hpt_file_quality.parquet"
    known_sources = _known_quality_sources(quality_final)
    archives = normalized_parquet_archives(p["ref"])
    primary_archive = max(archives, key=lambda path: path.stat().st_mtime_ns) if archives else None
    archive_mtime = primary_archive.stat().st_mtime_ns if primary_archive else None
    source_files: list[tuple[str, Path]] = []
    if source_root.is_dir():
        source_files.extend(price_files(p["raw"], set(cfg.get("skip_systems") or [])))
    ref_parquets = parquet_price_files(p["ref"])
    ref_raw = reference_raw_price_files(p["ref"])
    covered_quality = []
    ref_sources = [("reference_parquet", f) for f in ref_parquets]
    ref_sources.extend(("reference_upload", f) for f in ref_raw)
    seen_paths = {path.resolve() for _, path in source_files}
    for system, source in ref_sources:
        if source.resolve() in seen_paths:
            continue
        seen_paths.add(source.resolve())
        if archive_mtime is not None and source.stat().st_mtime_ns <= archive_mtime:
            fingerprint = sha256(source)
            key = (rel(source), source.name, fingerprint)
            if key not in known_sources:
                covered_quality.append(_covered_source_quality(system, source, fingerprint))
            continue
        source_files.append((system, source))

    replace_snapshot = bool(primary_archive and
                            not any(source_file == rel(primary_archive)
                                    for source_file, _, _ in known_sources))
    if primary_archive:
        print(f"Auto-discovered normalized hospital Parquet archive: {primary_archive}")
    if not source_files and not primary_archive and rates_final.is_file() and quality_final.is_file():
        print("No new hospital reference files; using the saved normalized Parquet snapshots.")
        return 0
    if not source_files and not primary_archive:
        if not source_root.is_dir():
            raise FileNotFoundError(f"Hospital MRF source folder is missing: {source_root}")
        raise ValueError("No supported hospital MRF reference files were found; existing outputs were preserved.")
    logs = _download_log(p["raw"])
    all_rows, all_q = [], []
    for archive in archives:
        rows, quality_rows = parse_normalized_archive(archive, scope, known_sources)
        all_rows.extend(rows)
        all_q.extend(quality_rows)
    for system, f in source_files:
        rows, q = parse_file(system, f, scope, logs.get(f.name, ""), known_sources)
        all_rows.extend(rows)
        all_q.extend(q)
    all_q.extend(covered_quality)
    if not all_q:
        print("No new hospital reference files; using the saved normalized Parquet snapshots.")
        return 0
    if replace_snapshot and not all_rows:
        raise ValueError("New consolidated hospital archive yielded no in-scope drug rows; "
                         "existing Parquet snapshots were preserved.")
    p["hpt_norm"].mkdir(parents=True, exist_ok=True)
    rates = pl.DataFrame(all_rows, schema=SCHEMA) if all_rows else pl.DataFrame(schema=SCHEMA)
    # A Parquet snapshot is the durable analytical store. Replacing just one
    # newly uploaded MRF must not discard rows converted from earlier uploads.
    # Reprocessing the same source replaces its rows by source path/member.
    source_keys = sorted({(row["source_file"], row["source_member"]) for row in all_q})
    keys = pl.DataFrame(source_keys, schema={"source_file": pl.Utf8, "source_member": pl.Utf8},
                        orient="row")

    def merge_snapshot(path: Path, incoming: pl.DataFrame) -> pl.DataFrame:
        if path.is_file():
            existing = pl.read_parquet(path).join(
                keys, on=["source_file", "source_member"], how="anti")
            incoming = pl.concat([existing, incoming], how="diagonal_relaxed")
        return incoming

    quality = pl.DataFrame(all_q, infer_schema_length=None)
    if not replace_snapshot:
        rates = merge_snapshot(rates_final, rates)
        quality = merge_snapshot(quality_final, quality)
    p["hpt_norm"].mkdir(parents=True, exist_ok=True)
    rates_tmp = rates_final.with_name(rates_final.name + ".part")
    quality_tmp = quality_final.with_name(quality_final.name + ".part")
    rates.write_parquet(rates_tmp, compression="zstd")
    quality.write_parquet(quality_tmp, compression="zstd")
    # Parse into temporary files first. Preserve existing outputs if validation or promotion fails.
    try:
        if pl.read_parquet(rates_tmp).height != rates.height:
            raise ValueError("Temporary rates Parquet row count validation failed.")
        if pl.read_parquet(quality_tmp).height != quality.height:
            raise ValueError("Temporary quality Parquet row count validation failed.")
        backups = {}
        existing = {rates_final: rates_final.exists(), quality_final: quality_final.exists()}
        for final in (rates_final, quality_final):
            if final.exists():
                backup = final.with_name(final.name + ".bak")
                import shutil
                shutil.copy2(final, backup)
                backups[final] = backup
        try:
            os.replace(rates_tmp, rates_final)
            os.replace(quality_tmp, quality_final)
        except Exception:
            for final in (rates_final, quality_final):
                if final in backups:
                    os.replace(backups[final], final)
                elif not existing[final]:
                    final.unlink(missing_ok=True)
            raise
        for backup in backups.values():
            backup.unlink(missing_ok=True)
    finally:
        rates_tmp.unlink(missing_ok=True)
        quality_tmp.unlink(missing_ok=True)
    source_label = ("new or changed reference tables" if source_files or archives else
                    "covered reference tables")
    print(f"Updated Parquet with {len(rates):,} drug rate rows and {len(quality):,} file-quality rows; "
          f"processed {len(all_q)} {source_label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
