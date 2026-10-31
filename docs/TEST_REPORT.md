# Test and execution report

**Audit date:** 2026-10-31

## Results

| Check | Result |
|---|---|
| `python -m pytest -q` | 61 passed, 0 failed, 0 skipped |
| Django `manage.py check` | Passed, no issues |
| Django `makemigrations --check --dry-run` | No model changes detected; migration-history lookup warned when run without local DB permission |
| Safe PostgreSQL migration | `pricing.0005_two_application_roles` applied successfully after local DB authorization |
| Frontend `npm run build` | Passed; Vite warns entry chunk is 604.09 kB minified (175.36 kB gzip) |
| `pipeline.run_all` | Exit 0; no independent source failed |
| `manage.py validate_parquet` | Passed; 623 Parquet files inspected |
| `python build_market_report.py` | Passed; generated Markdown, CSVs, and dashboard JSON |
| Live frontend-to-backend health proxy | HTTP 200; API, PostgreSQL, Parquet all `ok` |
| Django `check --deploy` | Ran; five development-environment HTTPS/DEBUG warnings remain by design |

The pytest API suite uses the isolated SQLite test settings and the marked
TEST-only fixtures. The application settings remain PostgreSQL-only. The
successful migration output confirms the live local PostgreSQL role migration
was applied; no database reset was run. The existing `MeshKor` account is the
single protected Root Admin. `admin` and `meshkor-admin` remain Admins; the
existing `viewer` and `analyst` accounts are Viewers. No password was changed
or disclosed.

## Coverage

Pipeline tests cover Decimal calculations, no second 6%, unit conversion,
HCPCS/NDC normalization, exact file-quarter selection, unresolved unit status,
source parsing, and Parquet outputs. API tests cover route responses,
authentication, role permissions, JWT/session refresh, CSRF, invalid tokens,
and protected Root Admin behavior. OTP tests are included in the 61 passing
tests.

## Not run / remaining

- No frontend unit/component test runner is configured; `npm run` exposes build
  and dev scripts only. TypeScript checks do not apply because the app is JSX.
- No full browser-driven end-to-end session was executed.
- No third-party vulnerability database scan was run.
- The report remains draft pending clinical unit review and hospital identifier
  reconciliation.
