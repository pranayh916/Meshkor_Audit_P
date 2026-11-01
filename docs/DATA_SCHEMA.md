# Data storage and provenance

## Storage boundary

Parquet is the durable store for analytical data. DuckDB reads the curated
Parquet files for dashboard queries and report generation. The local SQLite
database contains user and operational records only; it does not store hospital
rate rows. PostgreSQL is not required by the application.

Original downloads are pipeline ingestion inputs. The dashboard and comparison
queries continue to work from a verified saved Parquet snapshot if raw files
are unavailable. Each analytical artifact retains source file/checksum
lineage where applicable, and run metadata binds the selected drug scope to its
CMS Part B source checksum.

## SQLite operational tables

| Model | Stored information | Source of truth |
|---|---|---|
| Django `User` and `Group` | Username, password hash, active flag, and Admin or Viewer application role | Account provisioning and Admin user management |
| `SourceFile` | Upload name/path, source key, format, checksum, size, and import status | Admin source upload and pipeline conversion |
| `ProcessingJob` | Job type, progress, status, requesting user, timestamps, summary, and error | Admin import/report actions |
| `ReportRecord` | Report status, comparison/config checksums, builder, approver, and release metadata | Report build and independent Admin release |
| `DrugUnitReview` | HCPCS, selected-scope checksum, reviewed unit, external clinical reviewer, decision, notes, and Admin recorder | Admin review tied to the current selected scope |
| `AdminOTPDevice` | Encrypted TOTP seed, enabled state, replay-prevention step, and hashed recovery codes | Admin Google Authenticator enrollment |
| `AuditEvent` | Actor, action, entity, safe metadata, and timestamp | Sign-in, data access, import, review, account, and release events |

Passwords use Django's password hashers. Authenticator seeds are encrypted at
rest with `TOTP_ENCRYPTION_KEY`; recovery codes are one-way hashes. Keep the
encryption key stable and backed up. The database path defaults to
`data/operational/meshkor.sqlite3` and can be changed with
`OPERATIONAL_DB_PATH`.

## Parquet artifacts

| Path | Contents |
|---|---|
| `data/ref/ref_asp.parquet` | CMS ASP payment limits by HCPCS and quarter, dosage, and source lineage |
| `data/ref/ref_crosswalk.parquet` | CMS NDC-to-HCPCS crosswalk |
| `data/ref/ref_ndc_products.parquet` and `ref_ndc_packages.parquet` | FDA NDC product and package references |
| `data/ref/ref_hospitals.parquet` | CMS hospital catalog |
| `data/ref/ref_nadac.parquet` | NADAC acquisition-cost reference; not payer reimbursement |
| `data/ref/ref_providers.parquet` and `ref_enrollments.parquet` | Provider identity and CMS enrollment references |
| `data/ref/drug_scope.parquet` | Part B spend-ranked HCPCS scope and selection-source checksum |
| `data/hpt/norm/hpt_drug_rates.parquet` | Normalized hospital machine-readable-file rates and lineage |
| `data/hpt/norm/hpt_file_quality.parquet` | File parsing results, row counts, and errors |
| `data/mart/comparison.parquet` | Hospital rate observations, billing units, ASP benchmark, comparison status, and source checksums |
| `data/mart/run_info.json` | Run timestamp, drug scope, source checksum, calculation settings, and comparison row count |

The CMS ASP payment limit already includes the statutory 6% add-on. The
comparison does not add the 6% again. Units that cannot be verified remain
unpriced with an explicit status. Percentage-of-charge rows are not converted
to dollar amounts.

## Access boundaries

- Admin can manage sources, jobs, reviews, accounts, quality information, and
  report release.
- Viewer can access only a current released report and the corresponding
  filtered comparisons. Viewer responses omit internal source paths, failed
  rows, unresolved-unit work queues, and operational audit data.
- A report requires every selected drug to have an external clinical unit
  review, an Admin other than its builder to release it, and at least two active
  Admin accounts.

The current dataset may still have visible coverage gaps. Hospital price files
do not establish complete Ohio hospital coverage, and missing payer files or
client claims cannot be inferred from hospital data.
