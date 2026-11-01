# Current project status

## Application design

- React 18/Vite frontend on port `5173`.
- Django's native ASGI application served by Uvicorn on port `8000`.
- SQLite stores user/authentication and operational records only.
- Parquet is the durable analytical store; DuckDB powers comparisons and
  dashboard/report reads. PostgreSQL is not used by this application.
- The pipeline reads newly added source files during import, writes Parquet,
  then the app can read the saved Parquet snapshot without the raw files.

## Current stored snapshot

- 20 selected HCPCS drugs from the checksum-linked CMS Part B scope.
- 128 hospital keys and 153,568 comparison observations.
- 7,783 negotiated-dollar observations are in the `ok` headline subset.
- No selected drug has the required external clinical unit review yet.
- The market report is draft-only. Viewers cannot see this draft.
- The Ohio hospital catalog has 123 records, but hospital identifier matches
  and overall machine-readable-file coverage have not been fully reconciled.
- CMS Part B and several raw reference inputs are unavailable. The current
  stored Parquet snapshot is usable; refreshing those data requires the source
  downloads.

These counts describe the saved dataset. They do not prove a complete Ohio
hospital census, payer network availability, hospital acquisition costs,
member utilization, or plan savings.

## Release requirements

Before Viewer access can be enabled, the current report must be built from a
verified Parquet snapshot, each selected drug must have an external clinical
review of its CMS billing unit, and a second active Admin must release the
report. The Admin who built the report cannot release it; the system requires
at least two active Admin accounts.

## Checks performed for this change

- Backend tests: 70 passed.
- Django system check: no issues.
- Frontend production build: passed on Vite 8.3.5; the 651.10 kB minified
  chunk triggers a non-blocking size warning.
- npm and Python dependency audits: zero known vulnerabilities.
- Live API health endpoint: HTTP 200; API, SQLite, and Parquet all report
  `ok`.
- Live frontend root: HTTP 200.

The local UI and API are available at `http://127.0.0.1:5173/` and
`http://127.0.0.1:8000/`. A full browser workflow and penetration test remain
unverified.
