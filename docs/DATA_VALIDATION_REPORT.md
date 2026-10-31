# Data validation report

**Audit date:** 2026-10-31

## Pipeline and Parquet

- `python -m pipeline.run_all`: exit 0; summary says no independent inputs
  failed. New CMS ASP/crosswalk, Part B, NDC/FDA, NPPES, hospital enrollment,
  and hospital-list sources were absent where noted; saved Parquet snapshots
  were preserved/reused. The unrelated hospital CSV under the NADAC directory
  was skipped as an unrecognized NADAC layout.
- Hospital intake discovered `data/ref/parquet/ref_hospital_mrf.zip`; 154
  normalized hospital Parquet members were unchanged and reused. Forty-nine
  older duplicate tables were recorded as covered by that consolidated
  archive.
- `hpt_drug_rates.parquet`: 140,800 rows, 32 columns.
- `hpt_file_quality.parquet`: 203 records, 14 columns, zero recorded parser
  errors; 75 records have zero in-scope drug rows.
- `comparison.parquet`: 153,568 rows, 36 columns, 128 hospital keys, 20
  HCPCS codes, and source hashes on all comparison rows.
- ASP reference: 10,721 rows across 12 quarters (2024Q1–2026Q4). NDC/HCPCS
  crosswalk: 81,390 rows. CMS Ohio hospital catalog: 123 rows. Saved drug
  scope: 20 codes, year 2024, checksum-verified snapshot; raw CMS Part B source
  unavailable.
- `validate_parquet` inspected 623 Parquet files and passed readability and
  comparison/run-metadata checks. This validates file integrity/count
  consistency; it is not a complete semantic validation of every CMS field.

## Hospital coverage reconciliation

| Measure | Count |
|---|---:|
| CMS Ohio catalog CCNs | 123 |
| HPT comparison CCNs | 128 |
| Exact CCN intersection | 95 |
| HPT CCNs absent from catalog | 33 |
| Catalog CCNs with no comparison CCN | 28 |
| Distinct HPT hospital names | 115 |
| Distinct HPT source/archive members | 154 |

The HPT archive supplies CCNs but not NPI fields in the normalized comparison
schema. No CCN/NPI reconciliation or taxonomy-based explanation is available
for the 33/28 difference. A file/member count is not a hospital census. Do not
claim that all Ohio hospitals are covered until these identifiers and missing
prices are classified against the correct hospital population.

## Comparison statuses

| Status | Rows | Meaning |
|---|---:|---|
| `unit_unresolved` | 123,859 | No safe billing-unit conversion; no numeric markup |
| `algorithm_only` | 13,309 | Contract terms without a dollar amount |
| `ok` | 8,459 | Numeric comparison inside the review range |
| `percent_of_charges` | 3,596 | Contract is percentage based; no dollar comparison |
| `review_range` | 3,096 | Numeric value outside 0.5×–20×; inspect manually |
| `missing_asp` | 1,249 | No ASP payment limit for the exact hospital quarter |

Within negotiated-dollar rows, 7,783 are `ok`, 2,155 are `review_range`,
109,511 are `unit_unresolved`, and 1,143 are `missing_asp`. Zero of the 20
scope billing units are manually reviewed. The report is correctly marked
draft.

## Known source exclusions

- Normalized archive tables with no in-scope CMS Part B HCPCS/NDC rows remain
  in quality inventory with zero drug rows; they do not contribute a price
  comparison.
- Older nested tables whose content is covered by the consolidated archive
  are labelled `covered_by_hospital_archive` to avoid double counting.
- No ASP is substituted across quarters. Missing quarters remain explicitly
  unpriced as `missing_asp`.
- The scope and hospital files preserve source fingerprints. Original input
  files were not deleted or overwritten by the run.
