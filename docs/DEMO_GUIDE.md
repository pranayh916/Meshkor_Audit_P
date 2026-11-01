# Local run guide

The app uses a React/Vite frontend, Django's native ASGI app, SQLite for
authentication/operational records, and Parquet for analytical data.

## Start the backend

From the project root:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m uvicorn auditapi.asgi:application --host 127.0.0.1 --port 8000
```

Check `http://127.0.0.1:8000/api/v1/system/health-check/`. The health response
should report `api`, `database`, and `parquet` as `ok`.

## Start the frontend

In a second terminal:

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`. Sign in with a locally provisioned account.
There are no hardcoded demo credentials. Admins enroll Google Authenticator on
first sign-in; Viewers use password sign-in and can see only a released report.

## Import real source data

Sign in as Admin, upload a source listed in `config/report.json`, and use the
data-source processing action. The worker converts inputs to Parquet and builds
the comparison and report outputs. Raw files are needed to import or refresh;
normal dashboard/report reads use the stored Parquet snapshot.

Do not release the report until all selected drug billing units have external
clinical review, a second Admin releases the report, and the coverage/source
gaps have been reviewed.
