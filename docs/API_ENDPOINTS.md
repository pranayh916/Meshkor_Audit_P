# API endpoint reference

The frontend uses the versioned API under `/api/v1/`. Canonical paths use descriptive resource names and end in `/`. The older short paths remain available as compatibility aliases; new integrations should use the canonical paths below.

## Service health

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/system/health-check/` | Check API, PostgreSQL, and Parquet/DuckDB availability |
| `GET` | `/api/system/health-check/` | Unversioned health-check alias |

## Authentication and TOTP

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/authentication/csrf-token/` | Start a CSRF-protected sign-in flow |
| `POST` | `/api/v1/authentication/sign-in/` | Verify username and password; may return a TOTP enrollment or verification challenge |
| `GET` | `/api/v1/authentication/totp/status/` | Read the current account’s authenticator status |
| `POST` | `/api/v1/authentication/totp/setup/` | Start authenticator enrollment and return its provisioning URI and key |
| `POST` | `/api/v1/authentication/totp/confirmation/` | Confirm enrollment with a current six-digit code |
| `POST` | `/api/v1/authentication/totp/sign-in-verification/` | Complete sign-in with a TOTP or one-time recovery code |
| `POST` | `/api/v1/authentication/access-token/refresh/` | Refresh the short-lived API access token using the session |
| `POST` | `/api/v1/authentication/sign-out/` | End the current session |
| `GET` | `/api/v1/authentication/current-user/` | Read the signed-in account and application role |

TOTP is mandatory for both application roles. The legacy TOTP deactivation route is retained for compatibility but responds with `403` because accounts cannot disable required sign-in protection.

## Dashboard and comparison data

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/dashboard/summary/` | Dashboard totals, coverage, and data-evidence state |
| `GET` | `/api/v1/dashboard/price-trends/` | Price-trend series for the dashboard |
| `GET` | `/api/v1/medicare-part-b-drugs/` | List drugs in the current Medicare Part B selection |
| `GET` | `/api/v1/medicare-part-b-drugs/{hcpcs}/` | Read one selected drug and its comparisons |
| `GET` | `/api/v1/hospitals/` | List hospitals represented in the comparison data |
| `GET` | `/api/v1/hospitals/{hospital_key}/` | Read one hospital and its reported rates |
| `GET` | `/api/v1/hospital-drug-price-comparisons/` | Filter and page through hospital drug-price comparisons |
| `GET` | `/api/v1/hospital-drug-price-comparisons/exports/csv/` | Download filtered comparisons as CSV |
| `GET` | `/api/v1/hospital-drug-price-comparisons/exports/excel/` | Download filtered comparisons as Excel |
| `GET` | `/api/v1/hospital-file-quality/` | Read hospital-file processing and quality records |
| `GET` | `/api/v1/reports/market-analysis/pdf/` | Generate the market-analysis PDF |
| `GET` | `/api/v1/reports/` | List saved report records |
| `POST` | `/api/v1/reports/approval/sign-off/` | Sign off the current comparison as an Admin |

Analytics continue to be read from Parquet through DuckDB. PostgreSQL contains authentication and application records.

## Reference data and drug-unit review

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/reference-data-sets/` | List available reference datasets |
| `GET` | `/api/v1/reference-data-sets/{dataset_name}/` | Search and page through one allow-listed reference dataset |
| `GET` | `/api/v1/drug-selection-scope/` | Read the current source-backed drug selection and unit review state |
| `POST` | `/api/v1/drug-selection-scope/{hcpcs}/unit-review/` | Record an Admin’s review of the selected drug’s billing unit |
| `GET` | `/api/v1/drug-unit-validations/` | List unit validation findings |

## Data-source operations and application settings

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/data-sources/` | List supported source types and stored source records |
| `POST` | `/api/v1/data-sources/uploads/` | Upload a source file |
| `GET` | `/api/v1/data-sources/processing-jobs/` | List import and processing jobs |
| `POST` | `/api/v1/data-sources/processing-jobs/` | Queue a data import or refresh |
| `GET` | `/api/v1/data-sources/processing-jobs/{job_id}/` | Read one processing-job status |
| `GET` | `/api/v1/application-settings/` | Read application and comparison configuration |
| `GET` | `/api/v1/audit-logs/` | Read Admin-visible audit events |

## Django administrative console

The Django administrative console is at `/admin/`. Application API endpoints are rooted at `/api/v1/`.

## Dashboard page URLs

The frontend uses these descriptive page URLs. Previous short page paths such as `/rates`, `/drug-scope`, `/reference`, and `/settings` redirect to their canonical URL.

| Page | Canonical URL |
|---|---|
| Dashboard overview | `/` |
| Hospital catalog | `/hospitals` |
| Hospital detail | `/hospitals/{hospital_key}` |
| Medicare Part B drug detail | `/medicare-part-b-drugs/{hcpcs}` |
| Drug selection scope | `/drug-selection-scope` |
| Drug unit validations | `/drug-unit-validations` |
| Hospital drug price comparisons | `/hospital-drug-price-comparisons` |
| Report history and exports | `/reports` |
| Hospital price transparency files | `/hospital-price-transparency-files` |
| Reference data sets | `/reference-data-sets` |
| Hospital file quality | `/hospital-file-quality` |
| Data sources and imports | `/data-sources` |
| Application settings and authenticator | `/application-settings` |
| Audit logs | `/audit-logs` |
| Plan-specific audit | `/plan-specific-audit` |
| Methodology | `/methodology` |
