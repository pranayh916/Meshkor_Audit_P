"""Load FDA NDC product/package and CMS Ohio acute-care hospital references."""
from __future__ import annotations

import csv
import re
from pathlib import Path
import sys

import polars as pl
import yaml

from .common import load_yaml, paths, rel, sha256, write_sha256_sidecar


def _latest(pattern: str) -> Path | None:
    candidates = [p for p in paths()["raw"].glob(pattern) if p.is_file() and not p.name.endswith(".part")]
    return max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.as_posix())) if candidates else None


def _write_atomic(frame: pl.LazyFrame, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    try:
        frame.sink_parquet(tmp, compression="zstd", maintain_order=True)
        count = pl.scan_parquet(tmp).select(pl.len()).collect().item()
        if count <= 0:
            raise ValueError(f"Refusing to replace {target.name} with an empty dataset")
        tmp.replace(target)
        return count
    finally:
        tmp.unlink(missing_ok=True)


def load_fda_ndc() -> bool:
    product_path = _latest("fda_ndc/**/product.txt")
    package_path = _latest("fda_ndc/**/package.txt")
    if not product_path or not package_path:
        print("FDA NDC: source product.txt/package.txt not both present; skipped")
        return False

    product = pl.scan_csv(product_path, separator="\t", infer_schema=False,
                          encoding="utf8-lossy", truncate_ragged_lines=True)
    package = pl.scan_csv(package_path, separator="\t", infer_schema=False,
                          encoding="utf8-lossy", truncate_ragged_lines=True)
    product_columns = set(product.collect_schema().names())
    package_columns = set(package.collect_schema().names())
    product_required = {"PRODUCTID", "PRODUCTNDC", "PROPRIETARYNAME", "NONPROPRIETARYNAME",
                        "DOSAGEFORMNAME", "ROUTENAME", "ACTIVE_NUMERATOR_STRENGTH",
                        "ACTIVE_INGRED_UNIT", "STARTMARKETINGDATE", "ENDMARKETINGDATE"}
    package_required = {"PRODUCTID", "NDCPACKAGECODE", "PACKAGEDESCRIPTION",
                        "STARTMARKETINGDATE", "ENDMARKETINGDATE"}
    if not product_required <= product_columns or not package_required <= package_columns:
        raise ValueError("FDA NDC files do not match the verified product/package schema")

    product_digest, package_digest = sha256(product_path), sha256(package_path)
    write_sha256_sidecar(product_path, product_digest)
    write_sha256_sidecar(package_path, package_digest)
    product_ref = product.select(
        pl.col("PRODUCTID").alias("product_id"), pl.col("PRODUCTNDC").alias("product_ndc"),
        pl.col("PROPRIETARYNAME").alias("brand_name"),
        pl.col("NONPROPRIETARYNAME").alias("generic_name"),
        pl.col("DOSAGEFORMNAME").alias("dosage_form"), pl.col("ROUTENAME").alias("route"),
        pl.col("ACTIVE_NUMERATOR_STRENGTH").alias("active_strength"),
        pl.col("ACTIVE_INGRED_UNIT").alias("active_ingredient_unit"),
        pl.col("LABELERNAME").alias("labeler"), pl.col("SUBSTANCENAME").alias("substance"),
        pl.col("STARTMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("product_start_marketing_date"),
        pl.col("ENDMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("product_end_marketing_date"),
        pl.col("STARTMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("effective_start"),
        pl.col("ENDMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("effective_end"),
        pl.lit(rel(product_path)).alias("source_file"),
        pl.lit(product_digest).alias("source_sha256"),
    )
    ndc_expression = pl.col("NDCPACKAGECODE").map_elements(
        lambda value: _norm_ndc(value), return_dtype=pl.String, skip_nulls=False)
    package_ref = package.select(
        pl.col("PRODUCTID").alias("product_id"),
        pl.col("NDCPACKAGECODE").alias("ndc_package_code"), ndc_expression.alias("ndc11"),
        pl.col("PACKAGEDESCRIPTION").alias("package_description"),
        pl.col("STARTMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("package_start_marketing_date"),
        pl.col("ENDMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("package_end_marketing_date"),
        pl.col("STARTMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("effective_start"),
        pl.col("ENDMARKETINGDATE").str.to_date("%Y%m%d", strict=False).alias("effective_end"),
        pl.lit(rel(package_path)).alias("source_file"),
        pl.lit(package_digest).alias("source_sha256"),
    ).join(product_ref.select("product_id", "product_ndc", "brand_name", "generic_name",
                              "dosage_form", "route", "active_strength", "active_ingredient_unit",
                              "labeler", "substance"), on="product_id", how="left")
    out = paths()["ref"]
    n_products = _write_atomic(product_ref, out / "ref_ndc_products.parquet")
    n_packages = _write_atomic(package_ref, out / "ref_ndc_packages.parquet")
    print(f"FDA NDC: {n_products:,} product rows and {n_packages:,} package rows; "
          f"source hashes {product_digest[:12]} / {package_digest[:12]}")
    return True


def load_nadac() -> bool:
    """Load actual CMS NADAC snapshots while retaining file/date lineage."""
    candidates = sorted(p for p in paths()["raw"].glob("nadac/**/*.csv")
                        if p.is_file() and not p.name.endswith(".part"))
    target = paths()["ref"] / "ref_nadac.parquet"
    known_hashes = set()
    if target.is_file():
        known_hashes = set(pl.read_parquet(target, columns=["source_sha256"])
                           ["source_sha256"].drop_nulls().unique().to_list())
    new_candidates = [(source, sha256(source)) for source in candidates]
    new_candidates = [(source, digest) for source, digest in new_candidates
                      if digest not in known_hashes]
    if not new_candidates:
        if target.is_file():
            print("NADAC: no new source snapshots; using the saved Parquet table")
            return False
        print("NADAC: no source CSV files; skipped")
        return False

    frames = []
    for source, source_digest in new_candidates:
        lazy = pl.scan_csv(source, infer_schema=False, encoding="utf8-lossy",
                           truncate_ragged_lines=True)
        columns = set(lazy.collect_schema().names())
        required = {"NDC Description", "NDC", "NADAC Per Unit", "Effective Date", "Pricing Unit", "As of Date"}
        if not required <= columns:
            print(f"NADAC: skipped unrecognized CSV layout {source.name}")
            continue
        write_sha256_sidecar(source, source_digest)
        frames.append(lazy.select(
            pl.col("NDC Description").alias("description"),
            pl.col("NDC").alias("ndc_raw"),
            pl.col("NDC").map_elements(_norm_ndc, return_dtype=pl.String, skip_nulls=True).alias("ndc11"),
            pl.col("NADAC Per Unit").cast(pl.Float64, strict=False).alias("nadac_per_unit"),
            pl.col("Effective Date").str.to_date("%m/%d/%Y", strict=False).alias("effective_date"),
            pl.col("Effective Date").str.to_date("%m/%d/%Y", strict=False).alias("effective_start"),
            pl.lit(None, dtype=pl.Date).alias("effective_end"),
            pl.col("Pricing Unit").alias("pricing_unit"),
            pl.col("As of Date").str.to_date("%m/%d/%Y", strict=False).alias("as_of_date"),
            pl.lit(rel(source)).alias("source_file"),
            pl.lit(source_digest).alias("source_sha256"),
        ))
    if not frames:
        if target.is_file():
            print("NADAC: new files did not match the CMS schema; existing Parquet table preserved")
            return False
        raise ValueError("NADAC CSV files were found, but none matched the official CMS schema")
    combined = pl.concat(frames, how="vertical_relaxed")
    if target.is_file():
        combined = pl.concat([pl.scan_parquet(target), combined], how="diagonal_relaxed")
    count = _write_atomic(combined, target)
    print(f"NADAC: {count:,} reference rows from {len(frames)} CMS snapshots")
    return True


def load_nppes() -> bool:
    """Load the latest local NPPES full-replacement file, retaining Ohio providers."""
    candidates = [p for p in paths()["raw"].glob("NPPES/npidata_pfile_*.csv")
                  if p.is_file() and "fileheader" not in p.name.casefold() and not p.name.endswith(".part")]
    if not candidates:
        print("NPPES: no provider full-replacement CSV; skipped")
        return False
    source = max(candidates, key=lambda p: p.name)
    lazy = pl.scan_csv(source, infer_schema=False, encoding="utf8-lossy",
                       truncate_ragged_lines=True, null_values=[""])
    cols = set(lazy.collect_schema().names())
    required = {"NPI", "Entity Type Code", "Provider Organization Name (Legal Business Name)",
                "Provider Last Name (Legal Name)", "Provider First Name", 
                "Provider Business Practice Location Address State Name",
                "Provider Business Practice Location Address Postal Code",
                "Provider Business Practice Location Address City Name",
                "Provider Business Mailing Address State Name", "Provider Enumeration Date",
                "NPI Deactivation Reason Code", "NPI Deactivation Date", "NPI Reactivation Date"}
    if not required <= cols:
        raise ValueError(f"NPPES file missing required columns: {sorted(required - cols)}")
    taxonomy = sorted((c for c in cols if re.fullmatch(r"Healthcare Provider Taxonomy Code_\d+", c)),
                      key=lambda c: int(c.rsplit("_", 1)[1]))
    switches = {c.rsplit("_", 1)[1]: c for c in cols
                if re.fullmatch(r"Healthcare Provider Primary Taxonomy Switch_\d+", c)}
    if not taxonomy:
        raise ValueError("NPPES file has no taxonomy-code fields")
    if not switches:
        raise ValueError("NPPES file has no primary-taxonomy switch fields")
    primary = pl.coalesce([
        pl.when(pl.col(switches[c.rsplit("_", 1)[1]]) == "Y").then(pl.col(c))
        for c in taxonomy if c.rsplit("_", 1)[1] in switches
    ])
    organization = pl.col("Provider Organization Name (Legal Business Name)").str.strip_chars()
    individual = pl.concat_str([
        pl.col("Provider First Name"), pl.col("Provider Middle Name"),
        pl.col("Provider Last Name (Legal Name)"),
    ], separator=" ", ignore_nulls=True).str.strip_chars()
    practice_state = pl.col("Provider Business Practice Location Address State Name").str.strip_chars().str.to_uppercase()
    practice_zip3 = pl.col("Provider Business Practice Location Address Postal Code").str.strip_chars().str.extract(r"^(\d{3})", 1)
    geography = load_yaml("geography.yaml")
    hospital_taxonomies = load_yaml("hospital_taxonomies.yaml")
    state_code = str(geography.get("state_code", "OH")).upper()
    border_zip3 = [str(value).zfill(3) for value in geography.get("include_border_zip3", [])]
    accepted_taxonomies = [str(value).upper() for value in hospital_taxonomies.get("primary_taxonomy_codes", [])]
    market_filter = (practice_state == state_code)
    if border_zip3:
        market_filter = market_filter | practice_zip3.is_in(border_zip3)
    source_hash = sha256(source)
    write_sha256_sidecar(source, source_hash)
    frame = lazy.filter(
        (pl.col("Entity Type Code").str.strip_chars() == str(hospital_taxonomies.get("provider_entity_type", "2")))
        & market_filter
        & primary.is_in(accepted_taxonomies)
    ).select(
        pl.col("NPI").str.strip_chars().alias("npi"),
        pl.col("Entity Type Code").alias("entity_type"),
        pl.when(pl.col("Entity Type Code") == "2").then(organization).otherwise(individual).alias("provider_name"),
        pl.col("Provider Business Practice Location Address City Name").alias("practice_city"),
        practice_state.alias("practice_state"), mailing_state.alias("mailing_state"),
        primary.alias("primary_taxonomy"), pl.concat_list([pl.col(c) for c in taxonomy]).alias("taxonomy_codes"),
        pl.col("Provider Enumeration Date").str.to_date("%m/%d/%Y", strict=False).alias("enumeration_date"),
        pl.col("NPI Deactivation Reason Code").alias("deactivation_reason"),
        pl.col("NPI Deactivation Date").str.to_date("%m/%d/%Y", strict=False).alias("deactivation_date"),
        pl.col("NPI Reactivation Date").str.to_date("%m/%d/%Y", strict=False).alias("reactivation_date"),
        pl.col("NPI Deactivation Date").str.to_date("%m/%d/%Y", strict=False).alias("effective_end"),
        pl.lit(None, dtype=pl.Date).alias("effective_start"),
        pl.lit(rel(source)).alias("source_file"), pl.lit(source_hash).alias("source_sha256"),
    )
    count = _write_atomic(frame, paths()["ref"] / "ref_providers.parquet")
    print(f"NPPES: {count:,} {state_code} Type 2 providers in configured hospital taxonomies; source SHA-256 {source_hash}")
    return True


def load_hospital_enrollments() -> bool:
    """Load the latest CMS hospital-enrollment snapshot without coercing CCN/NPI."""
    candidates = [p for p in paths()["raw"].glob("Hospital Enrollments/**/*.csv")
                  if p.is_file() and not p.name.endswith(".part")]
    if not candidates:
        print("CMS hospital enrollments: no source CSV; skipped")
        return False
    def period(path: Path):
        match = re.search(r"(20\d{2})[._-](\d{2})[._-](\d{2})", path.name)
        return tuple(map(int, match.groups())) if match else (0, 0, 0)
    source = max(candidates, key=lambda p: (period(p), p.name))
    lazy = pl.scan_csv(source, infer_schema=False, encoding="utf8-lossy",
                       truncate_ragged_lines=True, null_values=[""])
    cols = set(lazy.collect_schema().names())
    required = {"NPI", "CCN", "ORGANIZATION NAME", "STATE", "SUBGROUP - ACUTE CARE"}
    if not required <= cols:
        raise ValueError(f"Hospital enrollment file missing required columns: {sorted(required - cols)}")
    source_hash = sha256(source)
    write_sha256_sidecar(source, source_hash)
    frame = lazy.filter(
        (pl.col("STATE").str.strip_chars().str.to_uppercase() == "OH")
        & (pl.col("SUBGROUP - ACUTE CARE").str.strip_chars().str.to_uppercase() == "Y")
        & pl.col("CCN").is_not_null() & (pl.col("CCN").str.strip_chars() != "")
        & pl.col("NPI").is_not_null() & (pl.col("NPI").str.strip_chars() != "")
        & (pl.col("CCN").str.strip_chars() != pl.col("NPI").str.strip_chars())
    ).select(
        pl.col("CCN").str.strip_chars().alias("ccn"), pl.col("NPI").str.strip_chars().alias("npi"),
        pl.col("ENROLLMENT ID").alias("enrollment_id"), pl.col("ORGANIZATION NAME").alias("organization_name"),
        pl.col("PROVIDER TYPE TEXT").alias("provider_type"), pl.col("STATE").alias("state"),
        pl.col("CITY").alias("city"), pl.col("ZIP CODE").alias("zip_code"),
        pl.col("SUBGROUP - ACUTE CARE").alias("acute_care"),
        pl.lit(None, dtype=pl.Date).alias("effective_start"), pl.lit(None, dtype=pl.Date).alias("effective_end"),
        pl.lit(rel(source)).alias("source_file"), pl.lit(source_hash).alias("source_sha256"),
    ).unique(subset=["ccn", "npi"], maintain_order=True)
    count = _write_atomic(frame, paths()["ref"] / "ref_enrollments.parquet")
    print(f"CMS hospital enrollments: {count:,} Ohio acute-care CCN/NPI records; "
          f"source SHA-256 {source_hash}")
    return True


def _norm_ndc(value: str | None) -> str | None:
    from .common import norm_ndc
    return norm_ndc(value)


def load_hospital_catalog() -> bool:
    config_path = Path(__file__).resolve().parent.parent / "config" / "report.json"
    config = __import__("json").loads(config_path.read_text(encoding="utf-8"))
    source_spec = next((s for s in config["required_inputs"] + config["supplemental_inputs"]
                        if s["key"] == "hospital_list"), None)
    if not source_spec:
        print("CMS hospital catalog: no configured input pattern; skipped")
        return False
    candidates = set()
    project_root = paths()["raw"].parent.parent
    for pattern in source_spec.get("patterns", []):
        candidates.update(p for p in project_root.glob(pattern)
                          if p.is_file() and p.suffix.casefold() == ".csv")
    if not candidates:
        print("CMS hospital catalog: no source CSV; skipped")
        return False
    source = max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.as_posix()))
    lazy = pl.scan_csv(source, infer_schema=False, encoding="utf8-lossy",
                       truncate_ragged_lines=True)
    cols = set(lazy.collect_schema().names())
    required = {"Facility ID", "Facility Name", "Address", "City/Town", "State",
                "ZIP Code", "County/Parish", "Telephone Number", "Hospital Type",
                "Hospital Ownership", "Emergency Services"}
    if not required <= cols:
        raise ValueError(f"CMS hospital file is missing columns: {sorted(required - cols)}")
    taxonomy = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" /
                               "hospital_taxonomy.yaml").read_text(encoding="utf-8"))
    source_hash = sha256(source)
    write_sha256_sidecar(source, source_hash)
    frame = lazy.filter(
        (pl.col("State").str.strip_chars().str.to_uppercase() == taxonomy["state_code"])
        & pl.col("Hospital Type").is_in(taxonomy["hospital_types"])
    ).select(
        pl.col("Facility ID").alias("ccn"), pl.col("Facility Name").alias("hospital_name"),
        pl.col("Address").alias("address"), pl.col("City/Town").alias("city"),
        pl.col("State").alias("state"), pl.col("ZIP Code").alias("zip_code"),
        pl.col("County/Parish").alias("county"), pl.col("Telephone Number").alias("phone"),
        pl.col("Hospital Type").alias("hospital_type"),
        pl.col("Hospital Ownership").alias("ownership"),
        pl.col("Emergency Services").alias("emergency_services"),
        pl.lit(None, dtype=pl.Date).alias("effective_start"),
        pl.lit(None, dtype=pl.Date).alias("effective_end"),
        pl.lit(None, dtype=pl.String).alias("npi"),
        pl.lit(rel(source)).alias("source_file"), pl.lit(source_hash).alias("source_sha256"),
    )
    enrollment_path = paths()["ref"] / "ref_enrollments.parquet"
    provider_path = paths()["ref"] / "ref_providers.parquet"
    if enrollment_path.is_file():
        enrollment = (pl.scan_parquet(enrollment_path).group_by("ccn").agg(pl.col("npi").first()))
        frame = frame.join(enrollment, on="ccn", how="left", suffix="_enrollment")
        frame = frame.with_columns(pl.coalesce("npi_enrollment", "npi").alias("npi")).drop("npi_enrollment")
        if provider_path.is_file():
            providers = pl.scan_parquet(provider_path).select(
                "npi", pl.col("provider_name").alias("provider_registry_name"),
                pl.col("primary_taxonomy").alias("provider_taxonomy"),
            ).unique(subset=["npi"], keep="first")
            frame = frame.join(providers, on="npi", how="left")
    if "provider_registry_name" not in frame.collect_schema().names():
        frame = frame.with_columns(pl.lit(None, dtype=pl.String).alias("provider_registry_name"),
                                   pl.lit(None, dtype=pl.String).alias("provider_taxonomy"))
    count = _write_atomic(frame, paths()["ref"] / "ref_hospitals.parquet")
    matched = pl.scan_parquet(paths()["ref"] / "ref_hospitals.parquet").filter(pl.col("npi").is_not_null()).select(pl.len()).collect().item()
    print(f"CMS hospital catalog: {count:,} {taxonomy['state_code']} acute-care hospitals; "
          f"{matched:,} matched to enrollment NPI; SHA-256 {source_hash}")
    return True


def main() -> int:
    errors = []
    for name, loader in (("FDA NDC", load_fda_ndc), ("NADAC", load_nadac),
                         ("NPPES", load_nppes), ("CMS hospital enrollments", load_hospital_enrollments),
                         ("CMS hospital catalog", load_hospital_catalog)):
        try:
            loader()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"ERROR {name}: {exc}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
