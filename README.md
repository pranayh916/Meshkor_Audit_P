# Infusion Drug Markup Audit — Phase 1 (Ohio market report)

Compares Ohio hospital negotiated prices for infusion drugs with the Medicare
benchmark (CMS ASP payment limit = ASP + 6%), per HCPCS billing unit.

```
pipeline/   Python: CMS + hospital files  ->  Parquet
backend/    Django + Django REST Framework API (reads Parquet with DuckDB)
frontend/   React + Vite dashboard
config/     processing rules, review range, and source catalog
scripts/    download_mrfs.py, build_manifest.py
tests/      pytest on made-up TEST files (never shown in the app)
data/       your downloads and outputs (not in Git)
```

## 1. Set up (Windows, once)

Copy this folder next to your existing data, so `data\raw\...` sits inside it:

```
E:\infusion-audit\
    data\raw\cms_asp\...  data\raw\hospital_mrf\...   (what you already have)
    pipeline\  backend\  frontend\  config\ ...      (this project)
```

```powershell
cd E:\infusion-audit
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
```

Node.js 18 or later is needed for the frontend.
For API address overrides, copy `frontend/.env.example` to
`frontend/.env.local` and edit its values.

## 2. Build the data

```powershell
python -m pipeline.run_all
python backend\manage.py ingest_raw_data
python backend\manage.py validate_parquet
python backend\manage.py run_comparison
python backend\manage.py pipeline_status
```

`ingest_raw_data` runs the configured source pipeline; `validate_parquet` checks
readable Parquet footers and reconciles the comparison count with run metadata;
`run_comparison` rebuilds comparisons from the saved ASP, scope, and normalized-rate
Parquet tables; and
`pipeline_status` reports raw-file count, output artifacts, and recent database jobs.

Parquet artifacts are the durable analytics store. Once a source has been
imported, the dashboard, API, report builder, and comparison rebuild can use the
saved Parquet datasets without the original CSV, JSON, ZIP, or Excel files. A
new upload is read during **Import data and rebuild dashboard**, converted into
the corresponding Parquet tables, and recorded with its source checksum. Hospital
and NADAC uploads are merged into the saved Parquet snapshots so a later upload
does not erase previously imported data. The original uploads remain stored for
audit lineage but are not needed to view or compare imported data.

| Step | Reads | Writes |
|---|---|---|
| `load_asp` | `data/raw_essential_inputs/cms_asp/**/*.zip`, `data/raw_essential_inputs/cms_crosswalk/**/*.zip` | `data/ref/ref_asp.parquet`, `ref_crosswalk.parquet` |
| `load_reference` | FDA NDC product/package files, NADAC snapshots, CMS Hospital General Information | `ref_ndc_products.parquet`, `ref_ndc_packages.parquet`, `ref_nadac.parquet`, `ref_hospitals.parquet` |
| `select_drugs` | `data/raw_essential_inputs/partb_spending/**/*.csv` or ZIP + loaded ASP | `data/ref/drug_scope.parquet` (spend-ranked HCPCS J-codes) |
| `parse_hpt` | Hospital MRFs in `data/raw_essential_inputs/hospital_mrf/` and supported files placed anywhere under `data/ref/` | `data/hpt/norm/hpt_drug_rates.parquet`, `hpt_file_quality.parquet` |
| `build_compare` | selected scope + ASP + parsed hospital rates | `data/mart/comparison.parquet`, `run_info.json` |

Hospital MRF intake is schema-discovered. Add a CMS price file as CSV, JSON,
Parquet, or a ZIP containing supported MRF files under `data/ref/` or the
hospital input folder, then run `python -m pipeline.run_all`. The pipeline
recognizes raw tall/wide MRF tables and normalized MRF Parquets, skips unrelated
reference tables and incomplete files, records source fingerprints, and only
reprocesses new or changed inputs. It writes normalized hospital rates to
Parquet before rebuilding the comparison Parquet used by the API and dashboard.
The loader records malformed or unsupported hospital files in the file-quality
table instead of silently counting them as usable prices.

The market scope comes from the CMS Medicare Part B Spending by Drug file; there
is no production fallback list. Add the official file under
`data/raw_essential_inputs/partb_spending/` to create or change the scope. When
the source file is unavailable, the pipeline reuses the stored scope only when
its checksum agrees with the saved comparison metadata; it never substitutes
sample data.

The ASP files can stay where they are now. The loader finds the quarter from the
file name (`october_2026_...` = 2026Q4) and skips seasonal vaccine files.
Hospital `.part` files (unfinished downloads) are skipped.

## 3. Run the app

First configure PostgreSQL in the project-root `.env`. Set `POSTGRES_PASSWORD`.
Start the installed PostgreSQL service, then prepare the app schema and an
account (there is no default or hardcoded password):

```powershell
cd D:\infusion-audit
..\.venv\Scripts\python.exe backend\manage.py migrate
..\.venv\Scripts\python.exe backend\manage.py createcachetable django_cache
..\.venv\Scripts\python.exe backend\manage.py initialize_roles
..\.venv\Scripts\python.exe backend\manage.py createsuperuser
..\.venv\Scripts\python.exe backend\manage.py configure_root_admin --username <root-admin-username>
```

Create or select the system-owner account with `createsuperuser`, then run
`configure_root_admin` with that account's username. This preserves all other
accounts and converts any extra superusers to ordinary Admins. The Root Admin
is protected from deletion and role/activation changes in Django admin. The
application has exactly two roles: Admin and Viewer. Admins can manage normal
accounts and role groups; legacy Data Analyst memberships are migrated to
Viewer to avoid an unreviewed privilege increase.

`POSTGRES_USER` must name a PostgreSQL login role that already exists, and
`POSTGRES_PASSWORD` must be that role's password. The example `.env` uses the
role `meshkor`; a standard PostgreSQL installation does not create that role
automatically. Create it in pgAdmin as a login role, or change `POSTGRES_USER`
to the existing role you intend to use. Also ensure the database named by
`POSTGRES_DB` exists and that the role owns it or has permission to connect and
create tables. Django migrations create the app tables; they do not create the
PostgreSQL role or database.

To run the checks without connecting to PostgreSQL, use `pytest`; tests use the
isolated `auditapi.test_settings` SQLite database. The normal app settings
remain PostgreSQL-only.

Then use three terminals in the project folder with the virtual environment active:

```powershell
# terminal 1 - API on http://127.0.0.1:8000/api/
cd D:\infusion-audit\backend
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000

# terminal 2 - UI on http://localhost:5173
cd D:\infusion-audit\frontend
npm run dev

# optional terminal 3 - keep a worker running for queued jobs
cd D:\infusion-audit\backend
..\.venv\Scripts\python.exe manage.py process_jobs
```

Open the Vite URL printed in terminal 2. The React application is protected by
the local account created above. The API and UI must both be running.
Uploading stores a source file; choose **Import data and rebuild dashboard** to run
the pipeline. The API starts a one-job worker automatically. An always-running worker
is optional and can be used to process queued jobs continuously.

Admins can optionally enable authenticator-app OTP in Settings. Add the
displayed account key to an authenticator app, confirm with a current six-digit code,
then save the one-time recovery codes and use a fresh authenticator code after the
password at sign-in. Set a Fernet key in `TOTP_ENCRYPTION_KEY` before enrollment;
generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
Keep the same key backed up securely. Losing it makes existing OTP seeds unreadable.
Database migrations create the PostgreSQL schema; existing account and audit
records are transferred separately and should be verified before removing the
previous local database file.

Pages include Overview, Data Sources, Reference Data, Hospital Files, Hospitals,
Drug Scope, ,Unit Validation, Price Comparison, Reports, Audit Logs, Settings,
Data Quality, and Methodology. Plan-specific claims auditing is marked planned.

API: `/api/health/`, `/api/meta`, `/api/drugs`, `/api/drugs/<hcpcs>`, `/api/hospitals`,
`/api/hospitals/<key>`, `/api/rates?hcpcs=&payer_group=&status=&price_type=&q=&sort=&order=`,
`/api/rates.csv`, `/api/rates.xlsx`, `/api/quality`. The full current endpoint
and role table is in [docs/API.md](docs/API.md); storage ownership and data lineage
are described in [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md).

## 4. Build the Ohio market report from the latest Parquet outputs

From the project root, run:

```powershell
python build_market_report.py
```

This writes a Markdown market report plus hospital-by-drug and source-provenance CSV
files and dashboard data under `reports/`. Input patterns, scope requirements, status
labels, and output filenames are configured in `config/report.json`. The dashboard
charts read row counts and quarter coverage from loaded reference Parquet tables;
market comparison charts only appear after a current drug scope and comparison build exist.

The standalone market-report dashboard is also available without signing in.
Rebuild the report from saved outputs and start the dashboard with:

```powershell
.\run_audit.ps1
```

Open `http://127.0.0.1:8765/dashboard/`. To rerun source processing first, use
`.\run_audit.ps1 -RefreshData`; it rebuilds the draft report even when an official
input is missing, then reports the incomplete pipeline. It does not substitute sample
values. The server redirects an accidental `/dashboard/**` URL to `/dashboard/` after
you start the updated script.

## 5. Tests

```powershell
python -m pytest
```

The tests build an isolated folder of made-up files (CSV tall, CSV wide, JSON
in a ZIP, ASP as CSV and as Excel with junk header rows) and check every
conversion against hand-computed values.

## How a markup is computed

1. Hospital quantity from `drug_unit_of_measurement` + `drug_type_of_measurement`
   (ME = mg, GR = g, UN/F2 = units, ML, EA).
2. Billing units = hospital quantity ÷ HCPCS billing unit from the current CMS ASP
   dosage data and selected CMS Part B spending scope.
3. Price per billing unit = rate ÷ billing units.
4. Markup = price per billing unit ÷ ASP payment limit for the quarter of the hospital
   file's `last_updated_on` date. With the default `file_date` rule, a missing ASP
   quarter is `missing_asp`; the pipeline does not substitute a different quarter.

Row status: `ok`, `review_range` (outside 0.5×–20×), `unit_unresolved`,
`billing_unit_mismatch`, `missing_asp`, `no_benchmark`, `percent_of_charges`, `algorithm_only`.
Only `ok` negotiated-dollar rows go into medians. No unit is guessed: rows priced
per ML or EA, or with no unit, are listed but not priced.

## Current limits (Phase 1 slice)

- The current 20-drug scope is a saved Parquet snapshot. Its original CMS Part B
  spending file is unavailable, so the saved comparisons can be used but a new
  spend-ranked scope requires uploading the official source file.
- No drug has a `reviewed_by` yet. The UI marks every drug "not yet reviewed".
- Hospitals are keyed by price file, not CCN. NPPES + Hospital Enrollments add CCN/NPI later.
- Hospital-file presence does not establish Ohio acute-care coverage; CCN/NPI
  reconciliation with provider enrollment data remains incomplete.
- The supplied ASP files currently load 2024Q2–2026Q4; 2024Q1 has no usable HCPCS ASP file.
- Three official NADAC snapshots are loaded as 4,374,650 reference rows. NADAC is an
  acquisition-cost reference, not an employer plan reimbursement rate.
- A new CMS Part B spend file is required to recalculate the top-20 drug selection.
  Until then, the dashboard uses the checksum-verified scope and comparison Parquet
  snapshot already stored in the project.
- NPPES and CMS hospital-enrollment inputs are absent. The 123-record Ohio hospital
  catalog is not yet reconciled to provider identity or price-file coverage.
- Payer rate files and client claims are absent. Lower-cost physician-office rates and
  plan-specific savings are therefore not available; the plan claims audit is planned.
- PDF, CSV, and filtered Excel exports are available. Excel text cells that could
  be interpreted as formulas are escaped.
- Percent-of-charges contracts are shown, not priced.

## Authentication

The existing username/password login now issues a 15-minute HS256 bearer JWT.
The browser holds the access token in memory and uses the existing HttpOnly,
CSRF-protected Django session to obtain another token after a page reload. API
authorization continues to use the same report-viewer, analyst, and administrator
roles. Set `JWT_ACCESS_TOKEN_SECONDS` to change the development access-token life.

“Sign in with ChatGPT” is not enabled in this checkout: OpenAI currently limits
website identity sign-in to selected commercial partners. It requires a client ID,
registered callback URL, issuer endpoints, and configured token authentication.
Do not substitute an OpenAI API key for a user identity credential.

The versioned API uses descriptive, resource-based paths under `/api/v1/`.
See [the API endpoint reference](docs/API_ENDPOINTS.md) for the full route names,
HTTP methods, and purpose. Earlier abbreviated API paths remain as compatibility
aliases for existing clients.
#   M e s h k o r _ A u d i t _ P 
 
 