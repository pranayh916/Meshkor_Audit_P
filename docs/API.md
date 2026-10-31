# API reference

The project has a versioned API under `/api/v1/` and compatibility endpoints
under `/api/`. The application has exactly two roles: Admin and Viewer. Unless
listed as public, endpoints require an authenticated account in one of those
roles. Authorization is checked
by Django REST Framework on the server; hiding a UI control is not the security
boundary.

## Public and authentication

| Method and path | Access | Purpose |
|---|---|---|
| `GET /api/health/` | Public | API, PostgreSQL, and saved comparison availability |
| `GET /api/v1/auth/csrf/` | Public | CSRF cookie/token for password login |
| `POST /api/v1/auth/login/` | Public | Password login; admin OTP accounts receive only a short-lived challenge |
| `POST /api/v1/auth/otp/complete/` | Public challenge | Complete TOTP or consume a one-time recovery code |
| `GET /api/v1/auth/me/` | Authenticated | Current user and application roles |
| `POST /api/v1/auth/refresh/` | Authenticated Django session only | Issue a short-lived access token; bearer tokens cannot refresh themselves |
| `POST /api/v1/auth/logout/` | Authenticated | Close the browser session |
| `GET /api/v1/auth/otp/` | Admin | Read OTP enrollment state and remaining recovery-code count |
| `POST /api/v1/auth/otp/setup/` | Admin | Start encrypted TOTP enrollment |
| `POST /api/v1/auth/otp/confirm/` | Admin | Confirm enrollment and receive one-time recovery codes |
| `POST /api/v1/auth/otp/disable/` | Admin | Disable OTP with a fresh authenticator code |

## Analytics and datasets

| Method and path | Access | Purpose |
|---|---|---|
| `GET /api/v1/dashboard/summary/` | Viewer+ | Data-backed KPIs and coverage caveats |
| `GET /api/v1/dashboard/price-trends/` | Viewer+ | Server-aggregated trend series |
| `GET /api/v1/drugs/`, `GET /api/v1/drugs/{hcpcs}/` | Viewer+ | Drug comparisons and details |
| `GET /api/v1/hospitals/`, `GET /api/v1/hospitals/{key}/` | Viewer+ | Hospital price files and comparisons |
| `GET /api/v1/comparisons/` | Viewer+ | Filtered, paginated comparison records |
| `GET /api/v1/comparisons.csv` | Viewer+ | CSV export of the same filtered rows |
| `GET /api/v1/comparisons.xlsx` | Viewer+ | Batched Excel export; workbook formula-like text is escaped |
| `GET /api/v1/reference/` | Viewer+ | Allow-listed Parquet dataset catalog and schemas |
| `GET /api/v1/reference/{table}/` | Viewer+ | Bounded Parquet preview/search for allow-listed datasets |
| `GET /api/v1/quality/` | Viewer+ | Hospital-file parsing and data-quality findings |
| `GET /api/v1/settings/` | Viewer+ | Read-only methodology/configuration |

The reference catalog is a Parquet/DuckDB browser. It does not expose arbitrary
SQL and is distinct from PostgreSQL application tables.

## Source processing, reports, and review

| Method and path | Access | Purpose |
|---|---|---|
| `GET /api/v1/sources/` | Admin | Configured source requirements and discovered files |
| `POST /api/v1/sources/upload/` | Admin | Validate and store an input file |
| `GET, POST /api/v1/sources/jobs/` | Admin | Job history; queue a refresh or report job |
| `GET /api/v1/sources/jobs/{id}/` | Admin | Job progress and error details |
| `GET /api/v1/unit-validations/` | Viewer+ | Billing-unit validation queue |
| `POST /api/v1/drug-scope/{hcpcs}/review/` | Admin | Record unit-review outcome |
| `GET /api/v1/reports/` | Viewer+ | Report history |
| `GET /api/v1/reports/market.pdf` | Viewer+ | Draft or approved PDF report |
| `POST /api/v1/reports/signoff/` | Admin | Approve the current source-hashed report |
| `GET /api/v1/audit-logs/` | Admin | Application audit events |

Long-running jobs are persisted in PostgreSQL and processed by the management
worker. The upload flow stores original files and their hashes; it does not claim
that data is imported until a pipeline job succeeds.

