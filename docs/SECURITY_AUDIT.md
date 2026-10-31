# Security audit

**Audit date:** 2026-10-31

## Findings fixed

- **Authorization bypass:** Django `is_staff` alone previously granted all
  application capabilities. It no longer grants API access. Only explicit
  Admin/Viewer membership works; Django superusers are Admin.
- **Role over-provisioning:** the app exposed a third Data Analyst role. A
  non-destructive data migration now leaves exactly Admin and Viewer groups.
  Existing Data Analyst users move to Viewer, the least-privileged mapping.
- **Root account protection:** Django superuser accounts cannot be deleted or
  have their username, active/staff/superuser flags, groups, or permissions
  changed through the user admin. Bulk user deletion is disabled.

## Controls verified in code

- Password login requires CSRF for browser sessions, has per-user/IP failure
  throttling, and issues short-lived JWTs. Refresh requires the HttpOnly Django
  session, not a bearer token.
- Admin OTP uses Fernet-encrypted TOTP seeds, one-time hashed recovery codes,
  replay-step tracking, and rate-limited challenges.
- File upload validates source keys, extensions, signatures, maximum bytes,
  ZIP paths, member count, encrypted members, expansion size, and compression
  ratio. File names are normalized and saved below configured roots.
- Analytical query tables and sortable columns are allow-listed. Values use
  bound query parameters. Reference browsing does not expose arbitrary SQL.
- Production settings require a secret key and database password; `.env` is
  ignored and is not a tracked Git file. Credentials were not printed.
- Production CORS defaults to no allowed origins unless explicitly configured.

## Checks and open work

- Django `check`: passed.
- Django `check --deploy`: five warnings in the current development config:
  `DEBUG=True`, HTTP allowed for local use, HSTS unset, and session/CSRF secure
  cookies disabled for HTTP development. Production requires TLS, `DEBUG=0`,
  secure cookies, correct host/origin configuration, and HSTS after verifying
  the deployment is HTTPS-only.
- Static review and application tests were run. No third-party dependency
  vulnerability database scan (`pip-audit`, OSV, or `npm audit`) was completed.
- A full browser-driven security/E2E review was not completed. Recheck role
  assignments and OTP enrollment in the actual demonstration browser.
