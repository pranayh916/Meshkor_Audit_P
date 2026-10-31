# Bug fix report

**Audit date:** 2026-10-31

## Fixed

| Issue | Cause and impact | Fix | Verification |
|---|---|---|---|
| Incorrect benchmark quarter on undated or out-of-range hospital files | Under the `file_date` rule, a missing ASP quarter silently selected the latest loaded quarter and could create a false markup. | Select the quarter from the hospital file date exactly. Preserve the row with `missing_asp` and null benchmark/markup if that quarter is unavailable. | New unit and pipeline regression tests; `1,249` current rows are marked `missing_asp`. |
| Ohio report JSON export failed | Arrow/Parquet effective dates were inserted into JSON as Python `date` values. | Convert source effective dates to ISO strings. | `python build_market_report.py` completed and wrote all four report artifacts. |
| Staff account could inherit application privileges | `has_any_role` treated all Django staff accounts as Admin. | Only a superuser gets the Root Admin/Admin bypass; other users require an explicit Admin or Viewer group. | Viewer/admin API permission tests pass. |
| Three role groups conflicted with the two-role policy | `Administrator`, `Data Analyst`, and `Report Viewer` were treated as separate roles. | Added migration `0005_two_application_roles`; maps `Administrator` to Admin, Data Analyst and Report Viewer to Viewer, then removes legacy groups. | Migration applied to local PostgreSQL; API tests and role checks pass. |
| Root superuser could be changed or deleted through Django admin | Default user admin did not protect a system-owner account. | Superuser identity and privilege fields are read-only; individual deletion is denied; bulk deletion is disabled. | Django admin protection regression test passes. |
| Windows CSV fixture silently lost metadata dates | `csv.writer` emitted CRLF and Windows text output translated it again, creating blank rows. Old quarter fallback hid the problem. | Fixture writes LF explicitly. | Pipeline tests now verify hospital file date and exact quarter. |

## Remaining issues

- 123,859 rows have unresolved units; 1,249 rows lack ASP for their exact
  quarter; 20/20 drug units need reviewer sign-off.
- CCN reconciliation leaves 33 rate CCNs outside the 123-row Ohio CMS catalog
  and 28 catalog CCNs without a rate CCN. The raw sources do not explain the
  difference.
- The CMS Part B source file is absent. The checksum-matched saved scope is
  used; an updated scope cannot be independently rebuilt.
- The production deployment environment is not configured here. The local
  `check --deploy` command reports HTTPS, secure-cookie, HSTS, and DEBUG
  warnings because this is configured as a development environment.
- Frontend build succeeds with a 604 kB minified entry chunk (175 kB gzip),
  above Vite's 500 kB warning threshold.
