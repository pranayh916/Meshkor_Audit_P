# Calculation discrepancy report

**Audit date:** 2026-10-31

## Implementations compared

- **Canonical calculation:** `pipeline/build_compare.py` computes rows from
  hospital rates and the matching CMS ASP payment limit using Python `Decimal`.
- **Dashboard/API:** reads `data/mart/comparison.parquet` and aggregates only
  canonical values for the negotiated-dollar `ok` subset.
- **Standalone report:** `build_market_report.py` reads the same comparison
  Parquet and aggregates its canonical `markup_multiple`,
  `price_per_billing_unit`, and `asp_payment_limit` fields.

No separate second calculation implementation or second executable output was
identified in this repository. If the other software result is an external
application, its source code and exact input/output record were not supplied;
that external discrepancy cannot be independently attributed here.

## Reconciliation result

The report and DuckDB dashboard-style median query were compared on all 20
HCPCS codes. Maximum absolute median difference: **4.440892098500626e-16**,
caused by float aggregation/serialization. The values agree at display
precision. Individual per-unit prices and markups originate from the same
canonical Parquet rows; neither frontend nor report recalculates individual
markup figures.

## Exact source-backed calculation

Record from `data/mart/comparison.parquet`:

| Field | Value |
|---|---|
| Hospital | Joint Township District Memorial Hospital |
| HCPCS | J1561 |
| Description | immune globulin intravenous 10% 10 gm vial |
| Source member | `ref_hospital_mrf/360032_2026-10/part-000.parquet` in `data/ref/parquet/ref_hospital_mrf.zip` |
| Hospital priced quantity | 10,000 ME (mg) |
| CMS ASP dosage | 500 MG per HCPCS billing unit |
| Billing units | 10,000 / 500 = 20 |
| Negotiated amount | $2,971.436 |
| Price per HCPCS unit | $2,971.436 / 20 = $148.5718 |
| Hospital file date / selected ASP quarter | 2025-05-15 / 2025Q2 |
| CMS ASP Payment Limit | $48.345 per HCPCS unit (already includes ASP + 6%) |
| Difference | $148.5718 − $48.345 = $100.2268 |
| Markup multiple | $148.5718 / $48.345 = 3.0731575137035888× |
| Percent above benchmark | (multiple − 1) × 100 = 207.31575137035888% |
| Status | `ok` (pending human unit review) |

The CMS payment limit is used as stored; the calculation does **not** add a
second 6%. This numeric result is a software arithmetic check, not clinical
approval of the interpretation of the hospital unit.

## Root cause and regression coverage

With the configured `file_date` rule, the previous code used the latest ASP
quarter whenever the hospital quarter was not loaded or the file date was
missing. This could compare rates from different quarters and fabricate a
numeric result. The fix resolves the requested quarter exactly and returns
`missing_asp` with null comparison fields when its benchmark is unavailable.
Regression coverage verifies exact quarter selection, missing-date behavior,
no fallback, decimal calculations, and that missing ASP never produces a
markup.

## Remaining discrepancy work

The original CMS Part B source file is unavailable; the saved scope checksum
matches the comparison metadata, but a new spend-ranked scope cannot be
recomputed from raw input. No manual review has been recorded for the current
20 billing units. These are data/provenance and review limitations rather than
software output mismatches.
