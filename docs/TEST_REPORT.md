# Verification report

## Checks completed

| Check | Result |
|---|---|
| Backend pytest suite | 70 passed |
| Django system check | Passed: no issues |
| Frontend production build | Passed with Vite 8.3.5; 651.10 kB minified chunk-size warning |
| npm dependency audit | Passed: 0 known vulnerabilities |
| Python dependency audit | Passed: no known vulnerabilities |
| Live API health | HTTP 200; API, SQLite, and Parquet checks report `ok` |
| Live frontend | HTTP 200 at `http://127.0.0.1:5173/` |

Tests run against isolated test-only inputs; the production report reads the
stored Parquet snapshot. The test fixtures are not imported into production.

## Data and release status

The stored market snapshot contains 20 selected HCPCS drugs, 128 hospital
keys, and 153,568 comparison observations. There are 7,783 negotiated-dollar
rows in the current `ok` headline subset. No selected drug currently has the
required external clinical unit review, so the report remains a draft and is
not available to Viewer accounts.

The source CMS Part B file and several other raw inputs are unavailable. The
current Parquet snapshot retains its source lineage and supports dashboard
reads; new source imports or a refreshed top-20 scope require the official
inputs. Hospital identity/coverage is not reconciled to a complete Ohio
universe.

## Not covered by these checks

- A full browser-driven Admin and Viewer end-to-end session.
- A penetration test.
- Production HTTPS/deployment configuration.
- Clinical reviewer identity or clinical judgment; these require a qualified
  human reviewer.
