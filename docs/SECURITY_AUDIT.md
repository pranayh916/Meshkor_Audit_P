# Security controls and limits

**Audit date:** 2026-11-01

## Implemented controls

- Application API permissions are based on explicit Admin/Viewer roles;
  `is_staff` alone does not grant application access.
- Admin sign-in requires Google Authenticator TOTP. Viewer sign-in does not
  require OTP. Seeds are encrypted with a configured Fernet key, OTP replay is
  checked, recovery codes are stored as hashes and consumed once, and login
  challenges are rate limited.
- Browser sign-in is CSRF protected. Passwords use Django password hashers,
  failed passwords are throttled, and bearer access tokens expire.
- Viewer analytics responses require a current released report and filter out
  unresolved, ambiguous, mismatched, and unreviewed rows. Admin-only source,
  quality, unit-review, user, job, configuration, and audit endpoints are
  protected server-side.
- Uploads are constrained by configured source keys, extensions, signatures,
  byte limits, and archive checks before storage.
- Analytical queries use allow-listed tables/columns and bound parameters.
  Reference browsing does not allow arbitrary SQL.
- SQLite stores operational/authentication records. Analytics are read from
  Parquet using DuckDB.
- CSV exports prefix spreadsheet formula-like text cells so imported hospital
  labels or reviewer notes cannot execute as formulas when opened in Excel.
- Login, MFA challenge/setup, recovery-code, and token-refresh responses are
  marked non-cacheable.
- npm and Python package advisory scans report zero known vulnerabilities after
  upgrading the affected locked dependencies.

## Important operating requirements

- Set stable, private `DJANGO_SECRET_KEY` and `TOTP_ENCRYPTION_KEY` values in
  the ignored `.env` file before Admin enrollment. Losing the TOTP encryption
  key prevents enrolled seeds from being decrypted.
- The local HTTP setup is intended for development on loopback. Keep the local
  `.env` file private and outside Git.
- Report release is a separate approval: the builder cannot approve their own
  report, two active Admin accounts are required, and every selected drug needs
  external clinical unit review.

## Verification limits

The backend tests, Django checks, and dependency advisory scans pass. This is a
code-level review, not a penetration test. A full browser-driven workflow has
not been completed.
