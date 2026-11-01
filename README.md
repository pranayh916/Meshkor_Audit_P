# MeshKor Infusion Drug Markup Audit

An Ohio hospital price transparency analysis that compares published hospital
drug rates with quarter-specific Medicare Part B ASP payment limits, using the
HCPCS billing unit. The CMS ASP payment limit already includes its statutory
6% add-on; the comparison must not add another 6%.

## Data flow

```text
Admin uploads official source files
             │
             ▼
    configured ingestion pipeline
             │
             ▼
 Reference + normalized + comparison Parquet
             │
       ┌─────┴─────┐
       ▼           ▼
    DuckDB API   Report/PDF/CSV
       │
       ▼
  React dashboard
```

The pipeline converts supported source files into Parquet. Dashboard reads,
comparisons, and report generation use the saved Parquet artifacts; raw files
are only needed to ingest or refresh source data. Source file names and SHA-256
lineage are kept with the Parquet outputs. The SQLite database stores
authentication and operational records only. Hospital rate rows and other
analytics are not stored in SQLite or PostgreSQL.

## Storage

- `data/ref/`: CMS ASP, crosswalk, FDA NDC, hospital, provider, and selected
  drug scope reference Parquet.
- `data/hpt/norm/`: normalized hospital price rows and file-quality Parquet.
- `data/mart/`: comparison Parquet and run metadata.
- `data/operational/meshkor.sqlite3`: user accounts, roles, encrypted Admin
  TOTP seeds, import jobs, report approvals, clinical unit reviews, and audit
  events.
- `data/raw_essential_inputs/`: optional retained source files for import and
  provenance. Data files and local secrets are excluded from Git.

See [`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md) for the storage contract and
[`config/report.json`](config/report.json) for required and supplemental input
file patterns.

## Run locally on Windows

Install Python 3.11+ and Node.js 20.19+ (or 22.12+). From the project root:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a stable `DJANGO_SECRET_KEY` and `TOTP_ENCRYPTION_KEY` in `.env` before
using Admin authentication. Generate values with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Apply the SQLite schema and provision an account if the database is new:

```powershell
python backend\manage.py migrate
python backend\manage.py initialize_roles
python backend\manage.py createsuperuser
```

Start the API and UI in separate terminals from the project root:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn auditapi.asgi:application --host 127.0.0.1 --port 8000
```

```powershell
Set-Location frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Uvicorn serves Django's
native ASGI application and the existing API routes directly.

## Import or refresh data

Place official files in the source folders described in `config/report.json`,
or use the Admin Data Sources upload page. Run the configured pipeline and
report builder:

```powershell
python -m pipeline.run_all
python build_market_report.py
```

The pipeline reads source files during ingestion, then writes Parquet. Once a
valid snapshot is present, the dashboard can continue to read and compare it
without the original downloads. A new CMS Part B spending file is required to
change the spend-ranked drug scope; the saved, checksum-linked scope remains
available until then. Missing or unverified sources, incomplete hospital
coverage, unresolved units, and unavailable payer or claims inputs are surfaced
as gaps. The application does not fill them with sample data.

## Roles and report release

- **Admin** can manage accounts and imports, run the pipeline, review drug
  billing units, view operational data, and prepare reports. Admin sign-in
  requires Google Authenticator TOTP.
- **Viewer** can access only a released report and its safe comparisons. Viewer
  sign-in does not use TOTP.

Report release requires a current complete Parquet build, clinical review for
every selected drug, a different Admin from the report builder, and at least
two active Admin accounts. The product does not provide plan-specific claims
analysis, payer-file analysis, or multi-organization workspaces.

## Verification

```powershell
python -m pytest
Set-Location frontend
npm run build
```

The tests build isolated test-only data. Those records are not used by the
running application or included in production reports.
