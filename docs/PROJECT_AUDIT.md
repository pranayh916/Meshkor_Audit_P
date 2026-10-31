# MeshKor project audit

## Current audit update — 2026-10-31

This section supersedes the older data counts and implementation status below;
those entries are retained as dated history only.

### Current run

- The working tree contained extensive existing user changes. They were preserved.
- Full `python -m pipeline.run_all` completed with exit code 0 and reported no
  failed independent input. The CMS Part B original file and several raw
  reference sources are not present, so their checksum-verified saved Parquet
  snapshots were reused. The configured NADAC importer skipped an unrelated
  hospital CSV and retained the saved NADAC table.
- `parse_hpt` used the consolidated CMS hospital archive under `data/ref`:
  154 normalized Parquet members plus 49 older tables marked
  `covered_by_hospital_archive`. The normalized table contains 140,800 drug
  rate rows and the comparison contains 153,568 rows.
- Current comparison coverage is 128 hospital keys (115 distinct hospital
  names), 20 HCPCS codes, and one source system. The 123-row Ohio CMS hospital
  catalog shares 95 CCNs with the comparison; 33 comparison CCNs are absent
  from that catalog and 28 catalog CCNs have no matching comparison CCN. The
  sources do not provide enough evidence to assign reasons to these unmatched
  identifiers. Do not present this as a reconciled Ohio-hospital census.
- Quality Parquet contains 203 source records with no parser errors. Of these,
  154 are normalized archive tables and 49 are covered older copies; 75 have
  zero in-scope rows. `validate_parquet` inspected 623 files and passed its
  readable-footer and comparison-metadata checks.
- Comparison statuses: 123,859 `unit_unresolved`; 13,309 `algorithm_only`;
  8,459 `ok`; 3,596 `percent_of_charges`; 3,096 `review_range`; and 1,249
  `missing_asp`. Only 7,783 negotiated-dollar rows are in the `ok` headline
  subset. None of the 20 drug billing units has reviewer sign-off, and the
  report remains a draft.

### Confirmed fixes in this audit

1. `file_date` benchmark selection no longer substitutes the latest ASP quarter
   when the hospital quarter is missing. Unpriced rows are marked `missing_asp`.
2. Report JSON now serializes Parquet effective dates as ISO strings; before the
   fix, report export failed with `date is not JSON serializable`.
3. Application authorization now has exactly Admin and Viewer roles. A Django
   `is_staff` flag alone no longer grants application permissions. The safe
   migration maps legacy Data Analyst memberships to Viewer and preserves user
   and audit rows. Django superuser accounts are protected from routine admin
   deletion and role/activation changes.
4. The Windows CSV test fixture now writes stable LF rows. Doubled carriage
   returns had hidden missing metadata and accidentally relied on the old ASP
   fallback.
5. The earlier `build_market_report.py` / API median outputs agree to within
   `4.45e-16` on all 20 drug summaries because both aggregate the canonical
   comparison Parquet.
6. The existing `MeshKor` account is the single protected Root Admin; other
   superuser accounts were retained as ordinary Admins. The local PostgreSQL
   migration/configuration completed without resetting the database. The
   frontend-to-backend health proxy returned HTTP 200.

### Remaining release blockers

- 123,859 comparison records still lack a verified comparable unit; they carry
  null numeric comparisons. No drug unit has been clinically reviewed.
- 1,249 rows have no ASP for the hospital file's exact quarter; no other quarter
  was substituted.
- Hospital CCN coverage is not reconciled to the Ohio catalog/NPI registry.
- The original CMS Part B spending source is unavailable. Its 20-drug Parquet
  snapshot is checksum-verified, but rebuilding a new spend-ranked scope needs
  the official input.
- The report is draft-only; do not present its comparisons as clinically
  reviewed or as realized employer savings.
- Full browser-driven review and third-party dependency vulnerability scans
  were not completed. Production deployment checks in the local development
  environment report five expected HTTPS/DEBUG warnings.

**Inspection date:** 2026-10-29  
**Scope:** Stages A–C inspection and the user-approved fixes. Analytics remain in Parquet/DuckDB; PostgreSQL is for application/operational data. The hospital pipeline itself was not rerun because its raw MRF source directory is absent.

## Repository and stack

Relevant project structure:

```text
backend/                 Django and DRF API, auth, models and migrations
config/                  source URLs, pipeline rules, drug scope, report and taxonomy
data/hpt/norm/           normalized hospital drug rates and file quality Parquet
data/mart/               comparison Parquet, run metadata and inventory snapshots
data/raw_essential_inputs/ downloaded source inputs (raw_data/ is absent)
data/ref/                CMS/FDA reference and hospital-file Parquet datasets
data/processed_parquet_backup/ prior Parquet copies
frontend/                React 18 + Vite application; source files are JSX, not TypeScript
pipeline/                reference loaders, hospital parser, scope selection and comparison
reports/                 current draft Markdown/CSV/JSON outputs
scripts/                 source download and inventory helpers
tests/                   pytest pipeline and API tests
docs/                    created for this audit; no audit document existed before inspection
```

The backend uses Django 5.2.18, Django REST Framework 3.16.1, and psycopg 3.2.10 (see `requirements.txt`). The frontend uses React 18, React Router, Recharts and Vite (see `frontend/package.json`). `pytest.ini` points to `tests/` and `auditapi.settings`.

## Current data and database state

- The app settings require PostgreSQL and load connection settings from the ignored project `.env` (`backend/auditapi/settings.py`). The password was not printed or copied into this report.
- The local PostgreSQL server responds at `127.0.0.1:5432`. The configured `meshkor` login role was missing, so it was created using the password already configured in `.env`; access was granted to the existing `infusion_audit` database without dropping or resetting tables.
- Before adding the new administrator login, the PostgreSQL database contained 3 users, 3 groups, 22 audit events, 1 report record, and no source files, processing jobs, or unit reviews. Django reported no pending migrations. Existing users and operational rows were preserved.
- The legacy `backend/db.sqlite3` was removed on the user's earlier request to eliminate SQLite from the application. It contained 2 users, 3 groups and 23 audit events; those rows were not copied into PostgreSQL. The existing PostgreSQL rows were preserved.
- The project currently has Django models for source-file metadata, processing jobs, report records, unit reviews and audit events (`backend/pricing/models.py`).
- The checked-in working tree is already extensively modified/untracked. Preserve unrelated edits and review the current diff before any implementation.

### Available Parquet evidence

| Dataset | Rows | Other evidence |
|---|---:|---|
| Comparison (`data/mart/comparison.parquet`) | 60,867 | 45 hospital keys, 7 systems, 20 HCPCS codes |
| Normalized hospital rates (`data/hpt/norm/hpt_drug_rates.parquet`) | 56,579 | 45 source files, 36 hospital names, 7 systems, 20 HCPCS codes |
| Hospital file quality (`data/hpt/norm/hpt_file_quality.parquet`) | 75 | 8 systems; 22 rows have an error |
| ASP (`data/ref/ref_asp.parquet`) | 9,900 | Quarterly benchmark reference |
| NDC-HCPCS crosswalk (`data/ref/ref_crosswalk.parquet`) | 80,823 | Reference joins |
| NADAC (`data/ref/ref_nadac.parquet`) | 4,374,650 | Largest canonical reference table |
| NDC packages / products | 219,045 / 116,501 | FDA reference tables |
| Hospital catalog / enrollments / providers | 123 / 118 / 1,277 | Distinct datasets are present |
| Drug scope | 20 | Latest `run_info.json` identifies CMS Part B spending as its source |

There are 86 Parquet files under `data/ref/` totaling 8,100,483 rows, including repeated and `.incomplete.parquet` files. The data tree also contains Parquet backups and inventory snapshots; the current app does not query every Parquet file. `data/raw_essential_inputs/` contains 101 files: 24 CSV, 44 ZIP, 2 text and 31 SHA sidecars. The latest run metadata lists 45 hospital source files. These are inventory facts, not a validated census of eligible Ohio hospitals.

The Master Prompt asks why roughly 250 hospitals in raw data appear as only 2–4 in reports. The current comparison has 45 hospital keys, not 2–4. The latest inventory contains 299 datasets across four source categories, including 84 hospital price-transparency file entries; it is not a count of hospital sites. Those 84 entries include 42 readable/profiled files, 32 failed, 8 unsupported and 2 skipped due to processing limits. All 84 have `audit_eligible=false`. The current data does not substantiate a 250-hospital source count.

The saved report (`reports/ohio_market_report_draft.md`, generated 2026-10-28) reported zero because its configured input globs pointed under `data/raw/`, which does not exist. The downloaded sources are under `data/raw_essential_inputs/`. The paths are now aligned. After rebuilding the report on 2026-10-29, it reports 20 current HCPCS codes, 45 hospital sites, 7 systems, and 60,867 comparison rows. It remains a draft because the hospital MRF inputs are missing from the current raw tree and none of the 20 drug units has manual review sign-off. This does not explain a separate 2–4-hospital result in another report.

The pipeline and downloader now use `data/raw_essential_inputs/`. `parse_hpt.price_files()` will stop with a clear error if its `hospital_mrf/` directory is missing or contains no price files, preserving prior Parquet. The currently available HPT normalized output is therefore a prior build, not reproducible from the raw MRF files currently present. The raw-input directory contains CMS/FDA/reference sources but no `hospital_mrf/` directory.

All 22 error rows in the existing `data/hpt/norm/hpt_file_quality.parquet` are JSON lexical errors caused by a leading UTF-8 BOM. The parser now strips the BOM in a streaming reader; the test fixture has a BOM regression case. The old production error rows remain in the previous Parquet because the source MRF files needed to rebuild them are currently absent.

The API reference catalog mappings now use the available `ref_providers.parquet` and `ref_enrollments.parquet` filenames. `build_market_report.py` uses the same canonical names and resolves legacy run metadata paths against `raw_essential_inputs/` when validating the source hash.

## Existing data flow and commands

`pipeline/run_all.py` runs ASP/reference imports, Part B drug selection, hospital parsing and comparison in dependency order. The pipeline writes Parquet outputs and `data/mart/run_info.json`. The API uses DuckDB/Parquet for analytical queries. The attached Developer Guide keeps PostgreSQL for persistent app/operational records.

Commands documented in `README.md`:

```powershell
python -m pipeline.run_all
python build_market_report.py
python backend\manage.py migrate
python backend\manage.py initialize_roles
python backend\manage.py createsuperuser
python backend\manage.py runserver 127.0.0.1:8000
cd frontend; npm run dev
```

PostgreSQL mirroring edits were briefly started before the Master Prompt was supplied. After you selected the guide's storage design, I restored the DuckDB/Parquet query path, removed the unrun `load_analytics` command, and removed the automatic PostgreSQL sync from `pipeline/run_all.py` and `README.md`. No analytics rows were loaded into PostgreSQL. The PostgreSQL application configuration remains in place.

## API, frontend and tests

- Two API surfaces are registered: legacy `/api/` and the newer `/api/v1/` (`backend/pricing/urls.py`, `backend/pricing/v1_urls.py`). They expose authentication, overview/dashboard, drug, hospital, comparison, quality, source/import, reference, unit review, audit log and report routes.
- The React shell registers 16 page components, including `PlanAudit`. The guide limits the Ohio market-report frontend to six sections and defers plan-specific claims work to Phase 4.
- Authorization currently defines Administrator, Data Analyst and Report Viewer groups (`backend/pricing/permissions.py`); the prompt describes ADMIN and VIEWER unless the existing workflow requires a third role.
- Tests cover API auth, drug/hospital/rate endpoints, reference pagination and several parser/unit cases. The inspected test names do not show dedicated coverage for add/change/remove reconciliation, the 1% null-rate rule, CCN/NPI mapping, three-year coverage, five hand-checked ASP values or complete counts through every stage.
- `pytest -q --basetemp .pytest-tmp` completed: **38 passed**. The default system temp directory was unavailable in this sandbox, so the run placed pytest temporary files inside the workspace. Tests use `backend/auditapi/test_settings.py` (temporary in-memory SQLite); production app settings remain PostgreSQL-only. `python backend/manage.py check` completed without errors, and `npm run build` completed with a non-blocking large-bundle warning.

## Implemented, missing and known issues

**Present:** source URL configuration; ASP/reference loaders; Part B-spend-based scope selection; hospital MRF parsing; normalized rates and quality output; comparison generation; source hashes in the analytical schema; Django records for reviews, jobs, reports and audit events; API and React UI; report draft and CSV artifacts.

**Missing or not evidenced:** `config/hospital_sites.csv`, a geography config, validated counts for eligible hospitals versus files versus in-scope rows versus comparable prices, a complete proof of the 250-to-2–4 discrepancy, full tests-backed source-to-report reconciliation, and pharmacist/clinical sign-off for the first 20-drug release. A new `data/manifests/file_inventory.csv` now records the 101 current raw input files, including checksums, relative path, size, format, source period, and inventory/processing statuses; it preserves `data/manifest.csv` and its hand-entered metadata. It will classify added/changed/unchanged/removed files on subsequent runs.

**Log evidence:** The old 2.7 MB `backend/django_error.log` contained SQL debug output (including password hashes) and repeated admin URL-resolution/template errors. The file has been removed, Django logging is now warning-only to console with no file handler, and `*.log` files are ignored by Git. The empty Vite/runserver log files were removed. The admin URL-resolution issue still needs separate investigation if Django admin is used.

## Storage decision

On 2026-10-29 you selected the supplied guide's design: Parquet + DuckDB for analytical rows; PostgreSQL for persistent application and operational data. The previous request to copy all structured data into PostgreSQL is superseded for this project check. No bulk data copy or database reset was performed.

## Approved plan and implementation status

1. **Done:** pipeline/report/downloader/API upload and source-display paths now use `data/raw_essential_inputs/`; the existing raw inputs were left in place.
2. **Done:** added `data/manifests/file_inventory.csv`, preserving the legacy manifest, with atomic writing and added/changed/unchanged/removed/manual statuses. The current inventory contains 101 files.
3. **Done:** corrected provider/enrollment Parquet names and legacy source-path hash resolution. Broader CMS reference-method review remains open.
4. **Done:** parser skips UTF-8 BOM in a streaming reader; parser writes temp Parquet, validates row counts and restores old output if promotion fails. Added BOM test fixture. **Blocked on source data:** no current `raw_essential_inputs/hospital_mrf/` files, so the real MRF parser cannot be rerun; the older 22 production parse errors remain visible in its existing quality artifact.
5. **Partial:** source listing and upload now use configured input root; wider role/API-surface review is not complete.
6. **Not done:** Phase 3 frontend pruning and Phase 4 deferral review were not part of this approved fix.
7. **Done for report path:** rebuilt report after fixing source globs and hash resolution. It reports 20 drugs / 45 sites / 7 systems / 60,867 comparison rows, and remains draft due missing hospital MRF inputs and 0/20 unit reviews.

The project continues to use DuckDB/Parquet for analytics and PostgreSQL for app data. The missing `meshkor` login role was created, database access granted, migrations checked (no pending changes), and the Django CSRF API endpoint returned successfully. The user requested an administrator login; a new one was created without replacing existing accounts. The API tests validate behavior against an isolated in-memory SQLite test database, and the live API was separately started against PostgreSQL. The legacy SQLite application database was removed at the user's request; analytics were not copied into PostgreSQL.

On 2026-10-29, the available raw reference files were refreshed through `pipeline.run_all`: 11 ASP quarters, 12 crosswalk quarters, 116,501 NDC products, 219,045 packages, 4,374,650 NADAC rows, 1,277 NPPES providers, 118 hospital enrollments, 123 hospital catalog rows, and the 20-code CMS-spend-derived drug scope. The pipeline stopped at `parse_hpt` because no hospital MRF source files exist under `data/raw_essential_inputs/hospital_mrf/`; it did not replace the previous 56,579 normalized rates or 60,867 comparison rows. The report was rebuilt against these available references and remains a draft with the existing 20 drugs, 45 hospital keys, 7 systems, and 60,867 comparison rows.
