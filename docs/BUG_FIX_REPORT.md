# Fixes and current blockers

## Fixed in the current work

- Viewer password sign-in now completes without an Admin-only TOTP challenge;
  Admin enrollment and OTP verification remain mandatory.
- Account management validates role and active-state input, prevents self
  demotion/deactivation, enforces the active-Admin release requirement, and
  applies account changes transactionally.
- Manual unit review requires the external clinical reviewer name and evidence
  before a drug can count as reviewed.
- Report generation now validates source lineage in the saved Parquet artifacts
  and can run from a valid archived Parquet snapshot without requiring the raw
  downloads to remain present. Missing raw files remain visible in provenance.
- The non-existent plan-audit route redirects to Methodology, and the Admin
  unit-review endpoint no longer says its workflow is unavailable.
- The destructive PostgreSQL reset management command and contradictory
  PostgreSQL setup documentation were removed from the supported workflow.
- The login and report page descriptions state the Admin/Viewer and release
  boundaries more accurately.
- CSV exports neutralize spreadsheet formula prefixes in imported text.
- Authentication challenge, QR setup, recovery-code, and token-refresh
  responses are marked non-cacheable.
- Vulnerable npm and Python dependencies were upgraded; both advisory scans are
  clean. Uvicorn now serves Django's native ASGI app without an unused FastAPI
  wrapper or empty OpenAPI endpoint.

## Still unresolved

- None of the 20 selected drugs has external clinical unit sign-off.
- Hospital CCN/NPI and full Ohio hospital coverage are not reconciled.
- The CMS Part B source file is not present, so a fresh top-20 scope cannot be
  computed from the current folder; the checksum-linked saved scope remains in
  use.
- The current report stays draft until its clinical review and independent
  Admin release requirements are complete.
- A full browser workflow and penetration test have not been completed.
