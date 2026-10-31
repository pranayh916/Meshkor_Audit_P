# Storage and data provenance

## Storage boundary

PostgreSQL stores operational application records. Large analytic tables remain
in Parquet and are queried through DuckDB. Imported Parquet is the durable
analytics store; source uploads are used during ingestion and retained for
lineage, but dashboard and comparison reads do not require them. The dashboard's
Reference Data page exposes only a fixed allow-list of Parquet tables and safe
filters; it does not let ordinary users run SQL.

## PostgreSQL models

| Model | Main fields and relationships | Source of truth |
|---|---|---|
| Django User and Group | Username, password hash, active/staff flags; exactly Admin or Viewer application role | Local Root Admin provisioning and managed user accounts |
| `SourceFile` | Source key, original name, relative path, format, source URL, SHA-256, size, reporting period, status/error | Uploaded files and generated inventory; `converted` means the checksum appears in a Parquet artifact |
| `ProcessingJob` | Type, status, progress, timestamps, summary/error, requesting user | API requests and background worker |
| `ReportRecord` | Type, status, output path, source/config hashes, metadata, approver and time | Report generation and sign-off |
| `DrugUnitReview` | HCPCS, selected-scope hash, decimal billing quantity/unit, decision, reviewer, notes | Admin review tied to the exact scope hash |
| `AdminOTPDevice` | User, Fernet-encrypted TOTP seed, enabled flag, replay step, one-time recovery-code hashes | Admin enrollment; encryption key is supplied by `TOTP_ENCRYPTION_KEY` |
| `AuditEvent` | Optional actor, action, entity, JSON details, timestamp | Authentication, review, import, and report actions |

Foreign keys preserve actor/requester/reviewer/approver attribution while allowing
account deletion to retain historical events with a null actor where configured.
OTP secrets are encrypted at rest; recovery codes are one-way password hashes.
Keep `TOTP_ENCRYPTION_KEY` stable and backed up. Losing it makes enrolled seeds
unreadable.

## Parquet datasets

The API and comparison builder resolve canonical artifact paths from
`pipeline.common.paths()` and `pricing.data.files()`. New uploads are converted
during import. Later dashboard reads and comparison rebuilds use these Parquet
snapshots even when the original source file is unavailable. The principal
analytical artifacts are:

| Artifact | Contents |
|---|---|
| `data/ref/ref_asp.parquet` | CMS ASP payment limits by HCPCS and quarter, including dosage/source metadata |
| `data/ref/ref_crosswalk.parquet` | CMS NDC-to-HCPCS mapping |
| `data/ref/drug_scope.parquet` | HCPCS scope selected from CMS Part B drug spending, with source checksum and billing-unit review fields |
| `data/hpt/norm/hpt_drug_rates.parquet` | Normalized hospital-file drug rates and source lineage |
| `data/hpt/norm/hpt_file_quality.parquet` | Per-file parse result, scanned item count, normalized row count, and errors |
| `data/mart/comparison.parquet` | Comparison observations with status, unit, ASP quarter, source hashes, and methodology fields |
| `data/mart/run_info.json` | Pipeline timestamp, source checksum, selected codes, quarter coverage, row count, and calculation version |

The comparison output has one row per qualifying hospital rate/price type. Rows
with missing benchmarks or unresolved units remain explicitly classified rather
than being converted into zero excess. Any saved Parquet snapshot without its
original source file is labeled as an archived snapshot by the API.

