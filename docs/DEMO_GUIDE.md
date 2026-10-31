# Demonstration guide

## Start

1. Ensure the installed PostgreSQL service is running and the existing
   PostgreSQL configuration in `.env` is valid.
2. From the project root, run `python -m pipeline.run_all` when the source data
   has changed. The pipeline reuses unchanged fingerprinted Parquet inputs.
3. Run `python build_market_report.py` to refresh the draft report artifacts.
4. Ensure the single protected Root Admin has been selected with
   `python backend\manage.py configure_root_admin --username <root-admin-username>`.
   Existing account passwords and operational records are preserved.
5. In one terminal, run `python backend\manage.py runserver 127.0.0.1:8000`.
6. In another, run `cd frontend` then `npm run dev` and open the printed Vite
   URL (normally `http://127.0.0.1:5173`).

## Review flow

1. Sign in with the existing Admin account. Do not use a shared or default
   password. If Admin OTP is enabled, enter a current authenticator code.
2. Inspect the Overview, Data Sources, Hospital Files, and Drug Scope pages.
   The current Parquet snapshot contains 128 hospital keys across 20 HCPCS
   codes.
3. Open a J1561 hospital row and inspect its source member, hospital quantity,
   HCPCS dosage, ASP quarter, payment limit, unit price, and status.
4. Demonstrate an unresolved row and a `missing_asp` row as unpriced. Do not
   replace their values with another quarter or infer package concentration.
5. Show that the report is marked DRAFT. The current 20 drug units have no
   manual review sign-off and 33 HPT CCNs do not match the Ohio catalog.
6. Sign out and use a Viewer account. Confirm report/analytics pages are
   available and source import, processing jobs, unit review, OTP settings,
   and audit-log operations are blocked.

## Expected limitation to state

This is an Ohio market report draft, not a clinical recommendation or
utilization-weighted employer savings calculation. Only 7,783 negotiated
dollar rows are currently `ok`; most records have unresolved units. Do not
approve or publish until billing units and hospital coverage are reviewed.
