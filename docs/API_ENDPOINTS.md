# API and page routes

The React frontend calls the versioned API under `/api/v1/`. Canonical paths
use descriptive resource names. Older short paths remain for compatibility;
new clients should use the canonical routes below. Uvicorn serves Django's
native ASGI application directly.

## Authentication and account management

| Method | Endpoint | Access and behavior |
|---|---|---|
| `GET` | `/api/v1/system/health-check/` | Public; checks API, SQLite, and Parquet/DuckDB availability |
| `GET` | `/api/v1/authentication/csrf-token/` | Public; begins browser sign-in flow |
| `POST` | `/api/v1/authentication/sign-in/` | Public; password sign-in; Admin accounts receive an OTP enrollment or verification challenge; Viewers sign in without OTP |
| `GET` | `/api/v1/authentication/current-user/` | Public; reports current session identity when signed in |
| `GET` | `/api/v1/authentication/totp/status/` | Authenticated Admin; reads authenticator state |
| `POST` | `/api/v1/authentication/totp/setup/` | Admin enrollment challenge; returns QR provisioning URI and setup secret |
| `POST` | `/api/v1/authentication/totp/confirmation/` | Admin enrollment challenge; confirms setup and returns one-time recovery codes |
| `POST` | `/api/v1/authentication/totp/sign-in-verification/` | Admin challenge; completes sign-in with a TOTP or unused recovery code |
| `POST` | `/api/v1/authentication/totp/deactivation/` | Retained compatibility endpoint; returns `403`, Admin OTP is mandatory |
| `POST` | `/api/v1/authentication/access-token/refresh/` | Authenticated Django session only; bearer token alone cannot refresh |
| `POST` | `/api/v1/authentication/sign-out/` | Authenticated; ends the session |
| `GET`, `POST` | `/api/v1/user-accounts/` | Admin; list accounts or create an Admin/Viewer |
| `POST` | `/api/v1/user-accounts/{user_id}/management/` | Admin; update account role, active status, or password |

## Released analytics

Admin endpoints can read the current Parquet build. Viewer endpoints expose the
current report only after release and filter out unresolved or unreviewed rows.

| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/api/v1/dashboard/summary/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/dashboard/price-trends/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/medicare-part-b-drugs/` and `/{hcpcs}/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/hospitals/` and `/{hospital_key}/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/hospital-drug-price-comparisons/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/hospital-drug-price-comparisons/exports/csv/` | Admin; Viewer with a current release |
| `GET` | `/api/v1/hospital-drug-price-comparisons/exports/excel/` | Admin only |
| `GET` | `/api/v1/reports/` | Admin report history; Viewer current released report only |
| `GET` | `/api/v1/reports/market-analysis/pdf/` | Admin; Viewer with a current release |
| `POST` | `/api/v1/reports/approval/sign-off/` | Admin; requires a different builder, two active Admins, and all clinical unit reviews |

## Admin data operations

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/data-sources/` | Configured inputs and discovered source files |
| `POST` | `/api/v1/data-sources/uploads/` | Validate and store an input file |
| `GET`, `POST` | `/api/v1/data-sources/processing-jobs/` | List or queue pipeline/report jobs |
| `GET` | `/api/v1/data-sources/processing-jobs/{job_id}/` | Read job progress and result |
| `GET` | `/api/v1/reference-data-sets/` | Allow-listed reference Parquet catalog |
| `GET` | `/api/v1/reference-data-sets/{dataset_name}/` | Bounded search and pagination over an allow-listed table |
| `GET` | `/api/v1/drug-selection-scope/` | Current Part B drug scope and review state |
| `POST` | `/api/v1/drug-selection-scope/{hcpcs}/unit-review/` | Record external clinical reviewer, evidence, and unit decision |
| `GET` | `/api/v1/drug-unit-validations/` | Unit validation work queue |
| `GET` | `/api/v1/hospital-file-quality/` | File parsing and data-quality findings |
| `GET` | `/api/v1/application-settings/` | Versioned report, unit, and geography configuration |
| `GET` | `/api/v1/audit-logs/` | Admin audit history |

Analytics are queried from Parquet with DuckDB. Operational identity and job
records are in SQLite; rate rows are not stored in a relational database.

## Frontend page routes

| Page | Route | Visibility |
|---|---|---|
| Overview | `/` | Admin; Viewer with current release |
| Hospitals | `/hospitals` | Admin; Viewer with current release |
| Hospital detail | `/hospitals/{hospital_key}` | Admin; Viewer with current release |
| Drug detail | `/medicare-part-b-drugs/{hcpcs}` | Admin; Viewer with current release |
| Price comparisons | `/hospital-drug-price-comparisons` | Admin; Viewer with current release |
| Reports and exports | `/reports` | Admin; Viewer with current release |
| Methodology | `/methodology` | Signed-in users |
| Drug selection scope | `/drug-selection-scope` | Admin only |
| Drug unit review | `/drug-unit-validations` | Admin only |
| Data sources and imports | `/data-sources` | Admin only |
| Reference data | `/reference-data-sets` | Admin only |
| Hospital price files | `/hospital-price-transparency-files` | Admin only |
| Hospital file quality | `/hospital-file-quality` | Admin only |
| Audit logs | `/audit-logs` | Admin only |
| User management | `/user-management` | Admin only |
| Application settings | `/application-settings` | Signed-in users; configuration is Admin-only |
