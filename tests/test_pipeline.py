"""Pipeline tests on made-up TEST data (see conftest.py). Expected values are hand-computed."""
from datetime import date
from io import BytesIO
import csv
import hashlib
import json
from pathlib import Path
from decimal import Decimal

import polars as pl
import pytest

from pipeline.common import (Dose, billing_units, csv_safe_cell, hospital_dose, norm_hcpcs, norm_ndc,
                             parse_hcpcs_dosage, payer_group, quarter_from_filename)
from pipeline.load_asp import classify
from pipeline.select_drugs import apply_saved_scope_reviews
from pipeline.build_compare import comparison_metrics, resolve_benchmark_quarter
from pipeline.parse_hpt import _json_stream


# ---------- unit helpers ----------


def test_comparison_financial_math_uses_decimal_and_rejects_invalid_inputs():
    per_unit, multiple, percent = comparison_metrics("10.00", "2", "4.24")
    assert per_unit == Decimal("5")
    assert multiple == Decimal("1.179245283018867924528301887")
    assert percent == Decimal("17.92452830188679245283018870")
    with pytest.raises(ValueError, match="greater than zero"):
        comparison_metrics("10", "1", "0")


@pytest.mark.parametrize("raw", ["=HYPERLINK(\"https://bad.example\")", "+1+1", "@SUM(1,1)", "\t=1+1", "\r\n-1+1"])
def test_csv_exports_neutralize_spreadsheet_formulas(raw):
    assert csv_safe_cell(raw) == "'" + raw


def test_csv_safe_cell_leaves_numbers_and_plain_text_unchanged():
    assert csv_safe_cell(-1.25) == -1.25
    assert csv_safe_cell("ordinary text") == "ordinary text"


def test_file_date_quarter_does_not_fall_back_to_latest_asp():
    assert resolve_benchmark_quarter(date(2027, 1, 15), "file_date",
                                     ["2026Q3", "2026Q4"]) == "2027Q1"
    assert resolve_benchmark_quarter(None, "file_date", ["2026Q4"]) is None
    assert resolve_benchmark_quarter(None, "latest", ["2026Q3", "2026Q4"]) == "2026Q4"

@pytest.mark.parametrize("raw,expected", [
    ("00006-3026-02", "00006302602"),   # 5-4-2
    ("0006-3026-02", "00006302602"),    # 4-4-2
    ("57894-030-01", "57894003001"),    # 5-3-2
    ("57894-0030-1", "57894003001"),    # 5-4-1
    ("00006302602", "00006302602"),     # already 11
    ("0006302602", None),               # undashed 10 digits: ambiguous
    ("", None), (None, None), ("abc", None),
])
def test_norm_ndc(raw, expected):
    assert norm_ndc(raw) == expected


def test_norm_hcpcs():
    assert norm_hcpcs(" j9271 ") == "J9271"
    assert norm_hcpcs("Note:") is None
    assert norm_hcpcs("123456") is None


def test_quarter_parser_accepts_official_month_abbreviations():
    assert quarter_from_filename("apr_2025_asp_pricing_file_updated_022526.zip") == "2025Q2"
    assert quarter_from_filename("jul-2024-noc-pricing-file-060624.zip") == "2024Q3"


def test_json_stream_ignores_utf8_bom():
    with _json_stream(lambda: BytesIO(b"\xef\xbb\xbf{\"hospital_name\":\"Test\"}")) as stream:
        assert json.load(stream) == {"hospital_name": "Test"}


def test_noc_payment_files_are_not_treated_as_hcpcs_asp_files():
    assert classify(Path("April_2024_NOC_Pricing_File_030624___Final_File.zip")) is None


def test_dosage_parse():
    assert parse_hcpcs_dosage("10 MG") == Dose(10, "MG")
    assert parse_hcpcs_dosage("1 MG") == Dose(1, "MG")
    assert parse_hcpcs_dosage("100 UNITS") == Dose(100, "UNIT")
    assert parse_hcpcs_dosage("0.5 G") == Dose(500, "MG")


def test_billing_units():
    bu10 = Dose(10, "MG")
    assert billing_units(hospital_dose("100", "ME"), bu10)[0] == 10
    assert billing_units(hospital_dose("1", "GR"), bu10)[0] == 100
    assert billing_units(hospital_dose("1", "ML"), bu10)[0] is None
    assert billing_units(None, bu10)[0] is None
    assert billing_units(hospital_dose("100", "UN"), bu10)[0] is None   # unit mismatch


def test_quarter_and_payer():
    assert quarter_from_filename("october_2026_medicare_part_b_payment_limit_file.zip") == "2026Q4"
    assert quarter_from_filename("january_2026_ndc_hcpcs_crosswalk_updated_033026.zip") == "2026Q1"
    assert quarter_from_filename("2026-2027-seasonal-vaccine.zip") is None
    assert payer_group("Anthem Blue Cross") == "Anthem"
    assert payer_group("UMR") == "UnitedHealthcare"
    assert payer_group(None) == "Not stated"


# ---------- end to end ----------

def _cmp(built):
    return pl.read_parquet(built / "data/mart/comparison.parquet")


def _one(df, **eq):
    sub = df
    for k, v in eq.items():
        sub = sub.filter(pl.col(k) == v)
    assert len(sub) == 1, f"expected 1 row for {eq}, got {len(sub)}"
    return sub.row(0, named=True)


def test_asp_loaded(built):
    asp = pl.read_parquet(built / "data/ref/ref_asp.parquet")
    assert sorted(asp["quarter"].unique()) == ["2026Q3", "2026Q4"]
    q4 = _one(asp, hcpcs="J9271", quarter="2026Q4")
    assert q4["payment_limit"] == 60.0          # stored as is, no extra 6%
    assert q4["effective_start"] == date(2026, 10, 1)
    assert q4["effective_end"] == date(2026, 12, 31)
    assert asp["payment_limit"].null_count() == 0
    assert asp["source_sha256"].null_count() == 0
    assert "Note:" not in asp["hcpcs"].to_list()


def test_crosswalk_ndc_11(built):
    xw = pl.read_parquet(built / "data/ref/ref_crosswalk.parquet")
    assert set(xw["ndc11"]) == {"00006302602", "57894003001"}


def test_tall_dollar_rate(built):
    r = _one(_cmp(built), hcpcs="J9271", payer_name="Anthem Blue Cross",
             price_type="negotiated_dollar", source_member="tall__aaaa1111.csv")
    # 18000 for 100 mg -> 180 per mg; ASP Q4 60 -> 3.0x
    assert r["file_last_updated"] == date(2026, 10, 1)
    assert r["billing_units"] == 100
    assert r["price_per_billing_unit"] == pytest.approx(180)
    assert r["markup_multiple"] == pytest.approx(3.0)
    assert r["benchmark_quarter"] == "2026Q4"
    assert r["status"] == "ok"


def test_ten_mg_billing_unit(built):
    r = _one(_cmp(built), hcpcs="J1745", price_type="negotiated_dollar")
    # 2000 for 100 mg = 10 billing units of 10 mg -> 200 per unit; ASP 40 -> 5.0x
    assert r["billing_units"] == 10
    assert r["markup_multiple"] == pytest.approx(5.0)


def test_percent_only_and_estimate(built):
    df = _cmp(built)
    est = _one(df, payer_name="Aetna", price_type="estimated_amount")
    assert est["markup_multiple"] == pytest.approx(2.5)        # 15000/100/60
    uhc = _one(df, payer_name="UnitedHealthcare", source_member="tall__aaaa1111.csv")
    assert uhc["status"] == "percent_of_charges"
    assert uhc["markup_multiple"] is None
    assert uhc["negotiated_percentage"] == 60


def test_unresolved_units_are_not_priced(built):
    df = _cmp(built)
    op = _one(df, hcpcs="J9299", price_type="negotiated_dollar")
    assert op["status"] == "unit_unresolved" and op["markup_multiple"] is None
    den = _one(df, hcpcs="J0897", price_type="negotiated_dollar")
    assert den["status"] == "unit_unresolved" and "ML" in den["unit_note"]


def test_ndc_only_row_matched_through_crosswalk(built):
    r = _one(_cmp(built), payer_name="Cigna", price_type="negotiated_dollar")
    assert r["hcpcs"] == "J9271" and r["matched_via"] == "ndc_crosswalk"
    assert r["markup_multiple"] == Decimal("4.166666666666666666666666667")


def test_out_of_range_flagged(built):
    r = _one(_cmp(built), hcpcs="J2350", price_type="negotiated_dollar")
    assert r["markup_multiple"] == Decimal("0.010000000000000000000000000")
    assert r["status"] == "review_range"


def test_wide_csv(built):
    df = _cmp(built).filter(pl.col("source_member") == "wide__bbbb2222.csv")
    a = _one(df, payer_name="Anthem", price_type="negotiated_dollar")
    m = _one(df, payer_name="Medical Mutual", price_type="negotiated_dollar")
    assert a["markup_multiple"] == pytest.approx(3.0)    # 9000/50/60
    assert m["markup_multiple"] == pytest.approx(2.0)    # 6000/50/60
    assert m["payer_group"] == "Medical Mutual"


def test_json_in_zip_uses_file_quarter(built):
    r = _one(_cmp(built), source_member="test_standardcharges.json",
             price_type="negotiated_dollar")
    assert r["benchmark_quarter"] == "2026Q3"             # file dated 2026-08-01
    assert r["markup_multiple"] == pytest.approx(11000 / 100 / 55)
    assert r["hospital_label"] == "Test JSON Hospital"


def test_missing_asp_quarter_is_unpriced(built):
    r = _one(_cmp(built), source_member="missing_quarter__eeee5555.csv",
             price_type="negotiated_dollar")
    assert r["benchmark_quarter"] == "2027Q1"
    assert r["asp_payment_limit"] is None
    assert r["price_per_billing_unit"] is None
    assert r["markup_multiple"] is None
    assert r["status"] == "missing_asp"


def test_gross_and_cash_not_repeated_per_payer(built):
    df = _cmp(built).filter((pl.col("source_member") == "tall__aaaa1111.csv")
                            & (pl.col("description") == "KEYTRUDA 100MG"))
    assert len(df.filter(pl.col("price_type") == "gross_charge")) == 1
    assert len(df.filter(pl.col("price_type") == "cash")) == 1


def test_non_drug_rows_and_part_files_skipped(built):
    rates = pl.read_parquet(built / "data/hpt/norm/hpt_drug_rates.parquet")
    assert "OFFICE VISIT" not in rates["description"].to_list()
    assert "MRI BRAIN" not in rates["description"].to_list()
    q = pl.read_parquet(built / "data/hpt/norm/hpt_file_quality.parquet")
    assert not any(s.endswith(".part") for s in q["source_file"])
    assert q["error"].null_count() == len(q)


def test_saved_scope_applies_validated_and_rejected_reviews_without_raw_spend_file(tmp_path):
    selection_hash = "a" * 64
    scope_path = tmp_path / "drug_scope.parquet"
    review_dir = tmp_path / "unit_reviews"
    review_dir.mkdir()
    pl.DataFrame({
        "hcpcs": ["J1234", "J2345"],
        "billing_qty": [10.0, 5.0],
        "billing_unit": ["MG", "MG"],
        "selection_source_sha256": [selection_hash, selection_hash],
        "reviewed_by": [None, "Old approval"],
        "review_status": [None, "validated"],
        "review_date": [None, "old-date"],
        "review_notes": [None, "old approval note"],
        "unit_review_file": [None, "old.csv"],
        "unit_review_sha256": [None, "old-hash"],
    }).write_parquet(scope_path)

    review_path = review_dir / "app_reviews.csv"
    with review_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "HCPCS_Cd", "reviewed_by", "billing_unit", "billing_unit_qty",
            "selection_source_sha256", "review_status", "review_notes",
        ])
        writer.writeheader()
        writer.writerow({"HCPCS_Cd": "J1234", "reviewed_by": "External Pharmacist",
                         "billing_unit": "MG", "billing_unit_qty": "10",
                         "selection_source_sha256": selection_hash, "review_status": "validated",
                         "review_notes": "Verified against the CMS ASP dosage."})
        writer.writerow({"HCPCS_Cd": "J2345", "reviewed_by": "External Pharmacist",
                         "billing_unit": "MG", "billing_unit_qty": "5",
                         "selection_source_sha256": selection_hash, "review_status": "rejected",
                         "review_notes": "The unit evidence does not support approval."})

    assert apply_saved_scope_reviews(scope_path, review_dir) == 2
    output = pl.read_parquet(scope_path).sort("hcpcs").to_dicts()
    assert output[0]["reviewed_by"] == "External Pharmacist"
    assert output[0]["review_status"] == "validated"
    assert output[0]["review_notes"] == "Verified against the CMS ASP dosage."
    assert len(output[0]["unit_review_sha256"]) == 64
    assert output[1]["reviewed_by"] is None
    assert output[1]["review_status"] == "rejected"
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() == output[1]["unit_review_sha256"]
