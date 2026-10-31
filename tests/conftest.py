"""Builds a small TEST data folder and runs the pipeline on it.

ALL NUMBERS HERE ARE MADE-UP TEST VALUES. They are not CMS or hospital prices.
They exist only so each conversion can be checked by hand. They never go
into data/ and are never shown in the app.
"""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

DISCLAIMER = ["TEST FILE - not CMS data"]


def _zip_bytes(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, data)
    return buf.getvalue()


def _csv_text(rows) -> str:
    s = io.StringIO()
    csv.writer(s, lineterminator="\n").writerows(rows)
    return s.getvalue()


ASP_HEADER = ["HCPCS Code", "Short Description", "HCPCS Code Dosage", "Payment Limit",
              "Vaccine AWP%", "Vaccine Limit"]

ASP_Q4 = [  # TEST VALUES
    ["J9271", "Inj pembrolizumab", "1 MG", "60.000", "", ""],
    ["J9299", "Inj nivolumab", "1 MG", "30.000", "", ""],
    ["J2350", "Inj ocrelizumab", "1 MG", "100.000", "", ""],
    ["J1745", "Infliximab not biosimil 10mg", "10 MG", "40.000", "", ""],
    ["J0897", "Inj denosumab", "1 MG", "20.000", "", ""],
    ["99999", "not a drug", "", "1.00", "", ""],
]
ASP_Q3 = [  # TEST VALUES
    ["J9271", "Inj pembrolizumab", "1 MG", "55.000", "", ""],
    ["J9299", "Inj nivolumab", "1 MG", "29.000", "", ""],
    ["J2350", "Inj ocrelizumab", "1 MG", "99.000", "", ""],
    ["J1745", "Infliximab not biosimil 10mg", "10 MG", "39.000", "", ""],
    ["J0897", "Inj denosumab", "1 MG", "19.000", "", ""],
]

XW_HEADER = ["HCPCS Code", "Short Description", "LABELER NAME", "NDC2", "Drug Name",
             "HCPCS dosage", "PKG SIZE", "PKG QTY", "BILLUNITS", "BILLUNITSPKG"]
XW_Q4 = [
    ["J9271", "Inj pembrolizumab", "TEST LABELER", "00006-3026-02", "TESTDRUG A", "1 MG",
     "4", "1", "100", "100"],
    ["J1745", "Infliximab", "TEST LABELER", "57894-030-01", "TESTDRUG B", "10 MG",
     "1", "1", "10", "10"],
]

META = [["hospital_name", "last_updated_on", "version"],
        ["Test General Hospital", "2026-10-01", "2.2.0"]]

TALL_HEADER = ["description", "code|1", "code|1|type", "code|2", "code|2|type", "setting",
               "drug_unit_of_measurement", "drug_type_of_measurement", "standard_charge|gross",
               "standard_charge|discounted_cash", "payer_name", "plan_name",
               "standard_charge|negotiated_dollar", "standard_charge|negotiated_percentage",
               "standard_charge|negotiated_algorithm", "estimated_amount",
               "standard_charge|methodology"]
TALL_ROWS = [
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "Anthem Blue Cross", "PPO", "18000", "", "", "", "fee schedule"],
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "Aetna", "HMO", "", "50", "", "15000", "percent of total billed charges"],
    ["KEYTRUDA 100MG", "123", "CDM", "J9271", "HCPCS", "outpatient", "100", "ME", "30000",
     "15000", "UnitedHealthcare", "Choice", "", "60", "", "", "percent of total billed charges"],
    ["REMICADE 100MG", "124", "CDM", "J1745", "HCPCS", "outpatient", "100", "ME", "5000",
     "2500", "Anthem Blue Cross", "PPO", "2000", "", "", "", "fee schedule"],
    ["OFFICE VISIT", "99213", "CPT", "", "", "outpatient", "", "", "200", "100",
     "Anthem Blue Cross", "PPO", "150", "", "", "", "fee schedule"],
    ["OPDIVO", "125", "CDM", "J9299", "HCPCS", "outpatient", "", "", "9000", "4000",
     "Anthem Blue Cross", "PPO", "5000", "", "", "", "fee schedule"],
    ["PEMBRO NDC LINE", "126", "CDM", "00006302602", "NDC", "outpatient", "200", "ME", "60000",
     "30000", "Cigna", "OAP", "50000", "", "", "", "fee schedule"],
    ["DENOSUMAB SYR", "127", "CDM", "J0897", "HCPCS", "outpatient", "1", "ML", "4000", "2000",
     "Anthem Blue Cross", "PPO", "1500", "", "", "", "fee schedule"],
    ["OCREVUS 300MG", "128", "CDM", "J2350", "HCPCS", "outpatient", "300", "ME", "60000",
     "30000", "Paramount", "Advantage", "300", "", "", "", "fee schedule"],
]

WIDE_HEADER = ["description", "code|1", "code|1|type", "setting", "drug_unit_of_measurement",
               "drug_type_of_measurement", "standard_charge|gross",
               "standard_charge|discounted_cash",
               "standard_charge|Anthem|PPO|negotiated_dollar",
               "standard_charge|Anthem|PPO|negotiated_percentage",
               "standard_charge|Medical Mutual|SuperMed|negotiated_dollar",
               "estimated_amount|Medical Mutual|SuperMed"]
WIDE_ROWS = [["PEMBROLIZUMAB 50MG", "J9271", "HCPCS", "outpatient", "50", "ME", "20000", "9000",
              "9000", "", "6000", ""]]

JSON_FILE = {
    "hospital_name": "Test JSON Hospital",
    "last_updated_on": "2026-08-01",     # Q3 -> benchmark uses Q3 ASP
    "version": "2.0.0",
    "hospital_location": ["Test JSON Hospital"],
    "standard_charge_information": [
        {"description": "PEMBROLIZUMAB 100 MG",
         "code_information": [{"code": "J9271", "type": "HCPCS"}],
         "drug_information": {"unit": 100, "type": "ME"},
         "standard_charges": [{
             "setting": "outpatient", "gross_charge": 25000, "discounted_cash": 12000,
             "payers_information": [{"payer_name": "UnitedHealthcare", "plan_name": "Choice",
                                     "standard_charge_dollar": 11000,
                                     "methodology": "fee schedule"}]}]},
        {"description": "MRI BRAIN",
         "code_information": [{"code": "70551", "type": "CPT"}],
         "standard_charges": [{"setting": "outpatient", "gross_charge": 3000}]},
    ],
}


@pytest.fixture(scope="session")
def data_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ia_test_data")
    raw = root / "data" / "raw_essential_inputs"
    (raw / "cms_asp" / "2026_Q4").mkdir(parents=True)
    (raw / "cms_asp" / "2026_Q3").mkdir(parents=True)
    (raw / "cms_crosswalk" / "2026_Q4").mkdir(parents=True)
    (raw / "partb_spending").mkdir(parents=True)

    # Q4 as CSV with junk lines before the header (like real CMS files)
    q4 = _csv_text([DISCLAIMER, ["CPT codes copyright AMA"], [], ASP_HEADER, *ASP_Q4,
                    ["Note: footer text"]])
    (raw / "cms_asp/2026_Q4/october_2026_medicare_part_b_payment_limit_file_TEST.zip"
     ).write_bytes(_zip_bytes("Oct 2026 ASP Pricing File.csv", q4.encode()))

    # Q3 as Excel with 4 junk rows
    wb = Workbook()
    ws = wb.active
    for r in [DISCLAIMER, ["x"], ["y"], ["z"], ASP_HEADER, *ASP_Q3]:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    (raw / "cms_asp/2026_Q3/july_2026_medicare_part_b_payment_limit_file_TEST.zip"
     ).write_bytes(_zip_bytes("July 2026 ASP Pricing File.xlsx", b.getvalue()))

    xw = _csv_text([DISCLAIMER, XW_HEADER, *XW_Q4])
    (raw / "cms_crosswalk/2026_Q4/october_2026_asp_ndc_hcpcs_crosswalk_TEST.zip"
     ).write_bytes(_zip_bytes("crosswalk.csv", xw.encode()))
    # TEST ONLY: production scope is selected from the real CMS Part B file.
    partb = _csv_text([
        ["HCPCS_Cd", "HCPCS_Desc", "Brnd_Name", "Gnrc_Name", "Tot_Spndng_2023"],
        ["J9271", "Test description A", "Test brand A", "Test drug A", "500"],
        ["J9299", "Test description B", "Test brand B", "Test drug B", "400"],
        ["J2350", "Test description C", "Test brand C", "Test drug C", "300"],
        ["J1745", "Test description D", "Test brand D", "Test drug D", "200"],
        ["J0897", "Test description E", "Test brand E", "Test drug E", "100"],
    ])
    (raw / "partb_spending/medicare_part_b_spending_by_drug_TEST.csv").write_text(partb)
    # seasonal vaccine file must be ignored
    (raw / "cms_asp/2026_Q4/2026-2027-seasonal-vaccine-price-file-TEST.zip"
     ).write_bytes(_zip_bytes("v.csv", b"x"))

    sysdir = raw / "hospital_mrf" / "test_system" / "2026-10-21"
    sysdir.mkdir(parents=True)
    (sysdir / "cms-hpt.txt").write_text("location-name: Test\nmrf-url: http://x\n")
    (sysdir / "tall__aaaa1111.csv").write_text(_csv_text([*META, TALL_HEADER, *TALL_ROWS]))
    (sysdir / "wide__bbbb2222.csv").write_text(_csv_text([*META, WIDE_HEADER, *WIDE_ROWS]))
    (sysdir / "json__cccc3333.zip").write_bytes(
        _zip_bytes("test_standardcharges.json", b"\xef\xbb\xbf" + json.dumps(JSON_FILE).encode()))
    missing_quarter = [["hospital_name", "last_updated_on", "version"],
                       ["Test Missing Quarter Hospital", "2027-01-15", "2.2.0"],
                       TALL_HEADER, TALL_ROWS[0]]
    (sysdir / "missing_quarter__eeee5555.csv").write_text(_csv_text(missing_quarter))
    (sysdir / "half__dddd4444.csv.part").write_text("partial download - must be ignored")
    return root


@pytest.fixture(scope="session")
def built(data_root, monkeypatch_session):
    monkeypatch_session.setenv("IA_DATA_ROOT", str(data_root))
    from pipeline import build_compare, load_asp, parse_hpt, select_drugs
    assert load_asp.main() == 0
    assert select_drugs.main() == 0
    assert parse_hpt.main() == 0
    assert build_compare.main() == 0
    return data_root


@pytest.fixture(scope="session")
def monkeypatch_session():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()
