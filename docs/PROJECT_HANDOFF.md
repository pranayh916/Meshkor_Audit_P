# MeshKor Project Handoff

## Current status and historical notes (2026-11-07)

This file contains dated implementation records, including earlier findings
that were later fixed. When sections conflict, use the newest dated disposition
for that issue; older `BEFORE`, baseline, and independent-review sections are
historical evidence, not the current status. The 2026-11-04 repository review
identified 23 findings. MK-01 through MK-23 have code/documentation changes
recorded here or in the current README and extractor guide. Deployment,
real-data, browser, and production-database checks are separate acceptance
steps and must not be inferred from synthetic regression results.

### MK-23 through MK-30 disposition (2026-11-07)

This is the latest verified engineering status. Test counts in older dated
sections, including 135 and 141, are historical snapshots and are not current
baselines. The non-browser backend baseline is **148 passed** using pytest's
disposable synthetic-data fixture and database. Real operational/reference
files and customer databases were not changed. Browser and genuine
clinical/business acceptance remain separate from this technical result.

- **MK-23 — FIXED AND VERIFIED.** `excluded_records` remains a claim-record
  count and aggregate-cell exclusions remain in `excluded_aggregate_cells`.
  Complementary-suppression and record/cell regressions pass.
- **MK-24 — FIXED AND VERIFIED.** The active branch has no unmerged index
  entries, merge-in-progress state, or conflict markers in tracked application
  source. No merge, reset, or index operation was performed. Pre-existing
  deletions under tracked `tmp_pytest/` artifacts remain untouched.
- **MK-25 — FIXED AND VERIFIED.** Both paginated serializers compute
  Client-only status once per request and omit source references for Client-only
  users. Captured SQL query counts for 1-row and 50-row pages are equal across
  all four roles.
- **MK-26 — FIXED AND VERIFIED.** Analyst reads and plan-level summary/roster
  imports remain available. Platform source uploads and platform-wide
  processing-job POSTs require Super Admin. Analyst reference, hospital catalog,
  data-quality, and source-status pages are read-only in the UI; Reviewer and
  Client import inventory access is denied. Direct API role regressions pass.
- **MK-27 — FIXED AND VERIFIED for application tests.** Application tests use
  disposable generated fixtures and do not depend on gitignored customer or
  reference datasets. Genuine full-data integration was not run and remains a
  separate data-acceptance requirement.
- **MK-28 — FIXED AND VERIFIED.** Client market CSV downloads use the current
  released payload and exclude source provenance. Legacy CSV aliases are
  internal-only; XLSX remains Super Admin-only. Plan-specific downloads retain
  current published-version authorization. Authorization regressions pass.
- **MK-29 — FIXED AND VERIFIED.** General import list, detail, and quality
  endpoints require Analyst or Super Admin. Reviewer review remains scoped to
  review APIs; Reviewer and Client import inventory requests are denied.
- **MK-30 — FIXED AND VERIFIED.** This section is the current dated status;
  prior implementation records and historical failures are retained below.

Technical tests do not grant clinical signoff or business acceptance. Clinical
approval status remains **NOT PROVIDED**. Commercial release remains **NOT
READY** until genuine data, clinical, business, security, and browser acceptance
requirements pass.

### Latest verification commands (2026-11-07)

- `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --ignore=tests/test_browser_e2e.py --basetemp=.pytest-tmp\mk30-final` — **148 passed in 24.67s**.
- `.venv\Scripts\python.exe backend\manage.py check` — **passed**.
- `.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run` — **no changes detected**.
- `.venv\Scripts\python.exe backend\manage.py migrate --check` — **passed**.
- `npm --prefix frontend test` — **4 passed**.
- `npm --prefix frontend run build` — **passed**.
- `git diff --check` — **exit 0**; Git printed access warnings for pre-existing deletions under tracked `tmp_pytest/` paths. The scoped check over changed implementation, test, and handoff files was clean. The tracked application-source conflict-marker scan found no markers; `git ls-files -u` returned no entries.
- Headless: `.venv\Scripts\python.exe -m pytest tests\test_browser_e2e.py -q -p no:cacheprovider --tb=short --basetemp=.pytest-tmp\mk30-headless-selection` with `MESHKOR_TEST_DB_PATH` set to `.pytest-tmp\mk30-browser-headless-selection.sqlite3` — **1 passed in 67.44s**.
- Headed: `.venv\Scripts\python.exe -m pytest tests\test_browser_e2e.py -q -p no:cacheprovider --headed --slowmo=50 --tb=short --basetemp=.pytest-tmp\mk30-headed-selection` with `MESHKOR_TEST_DB_PATH` set to `.pytest-tmp\mk30-browser-headed-selection.sqlite3` — **1 passed in 73.46s**.
- Genuine full-data acceptance was not run. Both browser attempts used disposable SQLite databases and synthetic fixtures; neither used operational/customer databases.

### Browser audit-creation blocker closed (2026-11-07)

**Disposition: FIXED AND VERIFIED.** The import API and its role policy were
correct. `isReviewer(user)` intentionally returns true for Admins as well as
Reviewers, but the Plan Audits loader used that predicate to skip the import
request. Consequently, a Super Admin received `Promise.resolve([])` for
imports even though their direct `GET /plan-audits/imports/?plan_id=…` returned
the accepted synthetic row. The UI now loads imports for `analyst` capability
(which includes Super Admin) and skips that endpoint for Reviewer-only users.

The next browser render exposed a component-scope error: `acceptedImports` was
derived in `PlanAudits` but referenced inside `PlanSetupSection` without being
passed. `PlanSetupSection` now derives its accepted options from its scoped
`imports` prop. Rejected imports are not offered in the selector, and the create
request submits the selected accepted import ID. The backend already required
an active, authorized organization and plan plus an `accepted` import; those
checks and permissions did not change.

- Admin and assigned Analyst import lists return only their visible
  organization records; Reviewer and Client list requests return **403**.
- Regression coverage verifies Analyst visibility excludes a foreign tenant,
  audit creation succeeds with an accepted import, and rejected/foreign imports
  fail with **400**. Reviewer and Client audit-creation requests return **403**.
- Headless and headed browser runs each uploaded two valid synthetic summaries
  through the Analyst UI with distinct source periods. In both roles, selecting
  the other accepted import updated the audit form's source period. The
  Admin-created audit references the selected import ID. Reviewer audit
  selection completed without a general import-list request.
- Latest non-browser backend suite: **148 passed in 24.67s**. Frontend role
  tests: **4 passed**; React production build, Django checks, migration checks,
  Python compilation, and changed-file `git diff --check` passed.

This browser blocker has no remaining code or test blocker. Genuine full-data,
clinical, and business acceptance remain separate release requirements.

### P3 closure — MK-22 and MK-23

- **MK-22 — Documentation contradiction: COMPLETE.** README now describes
  implemented plan-specific claims audits and organization-scoped access, and
  states the actual payer-file limitation. This handoff labels dated baseline
  and `BEFORE` sections as historical so they are not mistaken for current
  status.
- **MK-23 — Extractor count units: COMPLETE.** `excluded_records` counts
  excluded claim records only. Aggregate cells have separate
  `excluded_aggregate_cells`, `suppressed_aggregate_cells`,
  `rejected_aggregate_cells`, and `aggregate_cell_reasons` fields. The extractor
  guide documents their units and reconciliation.

## RG-01 — Browser E2E Verification (2026-11-05)

**Decision: RG-01 BLOCKED.** A real Chromium browser was launched in both headless and headed modes against the React/Vite app and Django `live_server`, using disposable users and the pytest synthetic data root. Neither run completed the end-to-end workflow. No customer/operational database was used; pytest configured a shared in-memory SQLite database. No credentials, OTP secrets, tokens, cookies, screenshots, or traces were added to tracked files. Temporary logs and sanitized failure screenshots are under ignored `.pytest-tmp/`.

### Browser execution evidence

- Browser: Playwright Python 1.64 with the locally installed Playwright Chromium build (binary directory `chromium-1248`). The actual browser launched in both runs.
- Headless: **0 passed, 1 failed**. Command: `.venv\Scripts\python.exe -m pytest tests\test_browser_e2e.py -q -p no:cacheprovider --basetemp=.pytest-tmp\rg01-headless9`. Chromium reached account and tenant setup, then the live Django process raised SQLite `database table is locked` / `InterfaceError: bad parameter or other API misuse`; the aggregate-preview UI wait timed out. Django logged HTTP 500s on `/api/v1/reports/` and `/api/v1/plans/1/network-roster/` during shared-memory DB access.
- Headed: **0 passed, 1 failed**. Command: `.venv\Scripts\python.exe -m pytest tests\test_browser_e2e.py -q -p no:cacheprovider --headed --slowmo=50 --basetemp=.pytest-tmp\rg01-headed2`. Chromium visibly launched and progressed through MFA/admin/account setup, then failed at SQLite row-read corruption (`IndexError` in SQLite result conversion). An earlier headed attempt found an ambiguous duplicate “User management” heading; the test locator was scoped to `<main>`, but the database failure remains.
- The test harness uses random runtime credentials/MFA seeds, test-only settings, and a shared in-memory SQLite DB assertion. Bounded retries for brief SQLite lock overlaps did not make concurrent browser/server access reliable. Use a file-backed isolated test DB or separate disposable Django process before accepting browser results.
- The test includes but did not complete: admin MFA and invalid OTP, analyst import/run, reviewer organization boundaries and approval/rejection, creator self-approval denial, clinical unit validation, client published results/PDF/CSV, unpublished/rejected denial, unresolved markup, reviewer revocation, direct route authorization, navigation/forms, console/network checks, and desktop/mobile assertions. All are **NOT TESTED** as completed browser scenarios. Aggregate browser count per mode: **0 passed, 1 failed, 0 skipped**.
- API telemetry recorded unexpected HTTP 500 responses on `/api/v1/reports/` and `/api/v1/plans/1/network-roster/` during the DB failure. `/favicon.ico` returned 404. The test did not reach final console/network summary assertions. No credential-bearing screenshots or traces were retained; the failure screenshot helper clears password and OTP inputs.

### Changes and verification

- Added `tests/test_browser_e2e.py` for the real-browser workflow and isolated synthetic setup. The harness must be migrated away from shared in-memory SQLite before its results can verify the end-to-end security scenarios.
- Updated `frontend/src/pages/PlanAudits.jsx` to expose the approved PDF download action when server capability `can_download_report` is true; previously the UI exposed CSV but no PDF control. Production build passed; browser behavior remains **NOT TESTED**.
- Full pytest: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\rg01-full` — **135 passed, 1 failed** (the new browser test failed with the SQLite error above); all 135 pre-existing tests passed.
- Django `check`: **passed**. `makemigrations --check --dry-run`: **no changes detected**. `migrate --check`: **passed; no pending migrations**.
- `npm --prefix frontend run build`: **passed**.
- No commit, push, deployment, or operational/customer database mutation occurred. RG-01 remains blocked until every browser scenario completes against a reliably isolated disposable DB, headless and headed, with actual route statuses and console results captured.

## MK-10 — Ambiguous Adjustment Chain Propagation (2026-11-05)

**Disposition: MK-10 VERIFIED at the synthetic extraction, regression, and build level.** The before-fix duplicate-ancestor scenario retained claim C, an adjustment descendant of ambiguous A. After the fix, A’s duplicate rows and every dependent adjustment are excluded, while unrelated claims still aggregate normally. No operational claims, raw datasets, Parquet files, migrations, or historical audit versions were changed.

### Original BEFORE reproduction and financial impact

Synthetic inputs were two conflicting paid rows with ID `A` ($100/$80 and $150/$120 allowed/paid), adjusted claim `B` referencing `A` ($125/$100), and adjusted claim `C` referencing `B` ($130/$105), plus 11 independent valid claims ($10/$5 each). Before the fix, resolver output included **C** and all 11 independent IDs. It recorded only **2 exclusions** under `unresolved_adjustment_or_duplicate`; the aggregate exported **$240 allowed / $160 paid**, instead of the correct unrelated-only **$110 / $55**. The entire dependency chain must not contribute amounts when its root is ambiguous.

### Actual BEFORE → AFTER

**`client_extractor/src/processing/resolve_adjustments.py::resolve_claims`**

BEFORE, duplicate IDs and direct bad references were marked unresolved, but a descendant of a marked child was not traversed. The final pass could still export that descendant:

```python
if len(targets) != 1 or reference == claim["claim_id"]:
    unresolved.add(claim["claim_id"])
    if len(targets) == 1:
        unresolved.add(reference)
    continue
...
if claim_id in unresolved:
    _reason(quality, "unresolved_adjustment_or_duplicate")
    continue
if claim["claim_status"] in {"paid", "approved", "adjusted"}:
    output.append(claim)
```

AFTER, the resolver indexes IDs, builds predecessor-to-dependent edges, validates references and context, detects competing actions, then uses iterative Kahn traversal and a queue to mark cycles and propagate invalidity to every descendant. It does not recurse, and sorts retained claims by ID for deterministic output.

```python
pending = deque(invalid)
while pending:
    claim_id = pending.popleft()
    for child_id in children.get(claim_id, ()):
        if child_id not in invalid:
            invalid.add(child_id)
            pending.append(child_id)
...
return sorted(output, key=lambda claim: claim["claim_id"])
```

Duplicate IDs are ambiguous within the resolver, including identical rows supplied directly. The existing CLI normalization stage safely removes exact duplicate normalized source records before resolution, increments its established `duplicate_records` counter, and reports `duplicate_exact_record`; rows with the same ID but conflicting values remain ambiguous. Missing/self references, mismatched member/plan/HCPCS/provider/service-date context, malformed dependencies, multiple replacements or reversals, cycles, and descendants of any invalid node fail closed. Branches invalidate the affected root and all competing descendants; unrelated claims remain eligible.

Reversal semantics remain explicit: a unique valid reversal excludes both the reversal transaction and the referenced payable claim; a valid adjustment followed by a reversal contributes neither the earlier nor adjusted amount. A reversal of an ambiguous/missing/mismatched claim, competing reversals, or an adjustment/reversal branch is unresolved and cannot restore an older payable claim. A dependent transaction that points to a reversal is rejected because the input contract does not define safe reversal-of-reversal or replacement-after-reversal semantics. `adjusted_records`, `reversed_records`, `excluded_records`, and existing reason keys are preserved. Each source row reaching the resolver is counted once as retained or excluded; earlier normalization-stage invalid/exact-duplicate records remain in their existing separate counters. Quality output contains row numbers and generic reasons only, not claim/member identifiers.

The complete pipeline regression confirms the ambiguous chain never reaches aggregation or CSV export: the 11 unrelated members still meet the suppression threshold and export **$110 allowed / $55 paid**. Existing source-hash manifest generation and PHI-safe quality reporting remain intact; the extractor continues to operate locally without network calls.

### Modified files and verification

- `client_extractor/src/processing/resolve_adjustments.py` — complete iterative graph validation, descendant invalidity propagation, deterministic output, and preserved valid adjustment/reversal counting.
- `tests/test_client_extractor.py` — before-fix reproduction; complete synthetic CLI integration; valid linear/approved claims; identical and conflicting duplicate IDs; multiple branches; missing/self references; context mismatches; cycles and descendants; 1,200-node cyclic and 1,500-node valid chains; reversal ambiguity; and exact exclusion/aggregate totals.
- `docs/PROJECT_HANDOFF.md` — this MK-10 implementation and verification record. No other application, reader, validation, aggregation, exporter, UI, or dependency files were changed.
- Focused command: `.venv\\Scripts\\python.exe -m pytest tests\\test_client_extractor.py -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk10-focused-final` — **28 passed**.
- Full suite: `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk10-final` — **135 passed in 23.23s**, including MK-01–MK-09 regressions.
- `.venv\\Scripts\\python.exe backend\\manage.py check` — **no issues**.
- `.venv\\Scripts\\python.exe backend\\manage.py makemigrations --check --dry-run` — **no changes detected**; `.venv\\Scripts\\python.exe backend\\manage.py migrate --check` — **passed; no migration required**.
- `npm --prefix frontend run build` — **passed**. `git diff --check` — **passed**, with the existing CRLF informational notice for `frontend/src/main.jsx`.
- Browser testing: **NOT TESTED**; this is a local file-based client extractor, and verification used synthetic input. No customer data was modified. No commit, push, or deployment was performed.

**MK-10: VERIFIED. All 10 P1 issues: VERIFIED at the code/test level.** Browser and deployment verification remain separate.

## MK-09 — Conflicting Network Roster Validation (Implementation and Verification, 2026-11-05)

**Disposition: MK-09 VERIFIED at the engine, API regression, and production-build level.** The defect reproduced with synthetic 2026Q1 rows: a full-quarter `in_network` entry plus a February-only `out_of_network` entry returned `IN_NETWORK` and `_build_opportunities()` created one savings opportunity. After the fix the status is `NETWORK_STATUS_UNKNOWN` and no opportunity is created. No customer data or migration was changed.

### Actual BEFORE → AFTER

**`backend/pricing/plan_audit_engine.py::network_status_for`**

BEFORE, only rows that independently covered the complete quarter participated in the status decision; shorter conflicting intervals were ignored:

```python
covering = [item for item in records if item.effective_start <= start
            and (item.effective_end is None or item.effective_end >= end)]
statuses = {item.network_status for item in covering}
if statuses == {"in_network"}:
    return "IN_NETWORK"
if statuses == {"out_of_network"}:
    return "OUT_OF_NETWORK"
```

AFTER, overlapping intervals are clipped to quarter bounds and swept at every inclusive-date boundary. A gap, conflicting status, status transition, malformed interval, invalid source hash, missing network/location identity, or multiple plan/network/location identities yields `NETWORK_STATUS_UNKNOWN`. `NETWORK_DATA_EXPIRED` is returned only when all matching provider records end before the requested quarter; future-only or mixed historical/future evidence is unknown. Full quarter coverage with one consistent status returns `IN_NETWORK` or `OUT_OF_NETWORK`.

```python
quarter_end_exclusive = end + timedelta(days=1)
events[clipped_start]["add"].append(status)
events[clipped_end + timedelta(days=1)]["remove"].append(status)
...
if not active or len(active) != 1:
    return "NETWORK_STATUS_UNKNOWN"
...
return "IN_NETWORK" if consistent_status == "in_network" else "OUT_OF_NETWORK"
```

The sweep is independent of roster input order. `_build_opportunities()` retains the strict eligibility predicate `network_status_for(...) == "IN_NETWORK"`; conflicting/unknown alternatives therefore cannot enter savings, while a fully verified in-network alternative remains eligible. Relevant roster source hashes are retained on results/opportunities. Existing report and CSV serialization expose the explicit `network_status`; the UI styles only `IN_NETWORK` as validated, displays other states as pending, and uses “Not available” where no savings opportunity exists, rather than reporting unknown coverage as zero savings. No frontend or report code change was needed.

### Regression and verification

- Added `tests/test_api.py::test_mk09_network_status_requires_consistent_full_quarter_coverage`. It covers both conflict directions (full-quarter in + February out and the inverse), conflict exclusion from savings, verified alternatives, same-status overlap, adjacent inclusive intervals, gaps, February-only coverage, expired and open-ended records, quarter edges, leap-year Q1, Q4/year boundary, provider and plan isolation, ambiguous contract/location, source hashes, and order permutations.
- Focused command: `.venv\\Scripts\\python.exe -m pytest tests\\test_api.py::test_mk09_network_status_requires_consistent_full_quarter_coverage -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk09-focused-final` — **1 passed**.
- Full backend suite: `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk09-final` — **114 passed in 62.52s** (includes prior MK-01–MK-08 regressions).
- `.venv\\Scripts\\python.exe backend\\manage.py check` — **no issues**.
- `.venv\\Scripts\\python.exe backend\\manage.py makemigrations --check --dry-run` — **no changes detected**; `.venv\\Scripts\\python.exe backend\\manage.py migrate --check` — **passed; no migration required**.
- `npm run build` from `frontend` — **passed**. `git diff --check` — **passed**, with only the pre-existing CRLF informational notice for `frontend/src/main.jsx`.
- Browser testing was **NOT TESTED**. Tests use isolated synthetic intervals and the repository test database; no actual customer records, published audits, or deployments were touched. No commit, push, or deployment was performed.

**MK-09: VERIFIED. Overall: READY FOR MK-10.**

## MK-07 — Reviewer Unit Validation Access

**Disposition: MK-07 VERIFIED at the API and production-build level.** The original defect reproduced: authenticated REVIEWER GETs to `/api/v1/drug-unit-validations/` and `/api/v1/drug-selection-scope/` both returned **403**. Both endpoints required `CanAdminister`; the selected-scope endpoint also removed review decisions for every non-Admin role.

### Actual BEFORE → AFTER

BEFORE, both reads were Admin-only and saved review evidence was hidden from REVIEWER:

```python
@api_view(["GET"])
@permission_classes([CanAdminister])
def drug_scope_status(request):
    ...
    if has_any_role(request.user, {ADMIN_GROUP}):
        drug["unit_review"] = review
    else:
        drug.pop("unit_review", None)
```

The unit-exception endpoint had the same `CanAdminister` permission and returned posted price, ASP and markup columns for every authorized caller.

AFTER, only these two read endpoints use the existing `CanReview` policy, which authorizes REVIEWER and SUPER_ADMIN (including the existing Admin alias). Reviewer responses contain clinical unit/source evidence and bound review history, while omitting CMS spending ranks and price/ASP/markup columns. Admin retains the full prior response. Admin settings and audit logs remain protected by `CanAdminister`.

```python
@api_view(["GET"])
@permission_classes([CanReview])
def drug_scope_status(request):
    ...
    admin_access = has_any_role(request.user, {ADMIN_GROUP})
    reviewer_access = has_any_role(request.user, {REVIEWER_GROUP})
    ...
    if admin_access or reviewer_access:
        drug["unit_review"] = review
    if reviewer_access and not admin_access:
        drug = {key: drug.get(key) for key in (
            "hcpcs", "name", "brand", "description", "billing_qty", "billing_unit",
            "asp_quarter", "asp_dosage", "selection_source", "selection_source_file",
            "selection_source_sha256", "unit_review",
        )}
```

```python
@api_view(["GET"])
@permission_classes([CanReview])
def unit_validations(request):
    ...
    if not has_any_role(request.user, {ADMIN_GROUP}):
        rows = [{key: row.get(key) for key in clinical_fields} for row in rows]
```

`review_drug_unit` remains `CanReview` and continues to require a selected HCPCS, matching CMS dosage quantity/unit, named external clinical reviewer and evidence notes. The existing Unit Validation page now has no preselected “Validated” decision, disables submission when CMS unit evidence is incomplete, shows the selected source hash and saved decision/evidence, refreshes after submission, and hides financial columns from Reviewer accounts. Null benchmark markups in Plan Audits are explicitly labeled “Not comparable.”

### Permission and API results

`tests/test_api.py::test_mk07_reviewer_clinical_unit_validation_access` first failed against the unmodified endpoint permissions with actual Reviewer responses **403 / 403**. After the change it passes and covers:

| Account/scenario | Actual result |
|---|---|
| REVIEWER reads unit exceptions and selected CMS scope | **200 / 200** |
| REVIEWER sees prior/current review status, clinical reviewer identity, rationale and matching scope SHA-256 | **PASS** |
| REVIEWER records a valid synthetic `unit_unresolved` decision | **200**; state visible after refresh |
| Wrong billing quantity or inadequate evidence | **400 / 400** |
| CLIENT reads both endpoints / attempts a review write | **403 / 403 / 403** |
| ANALYST reads both endpoints / attempts a review write | **403 / 403 / 403** |
| Unauthenticated reads | **401 / 401** |
| SUPER_ADMIN reads both endpoints | **200 / 200** |
| REVIEWER reads application settings or audit logs | **403 / 403** |

The synthetic review remains `unit_unresolved`; no clinical signoff was fabricated. Its export writes only beneath pytest `tmp_path`. Clinical unit references are global CMS/reference data, not organization-owned audit data; these endpoints do not expose organization financial records. No applicable tenant-scoped audit endpoint was broadened.

**Files changed for MK-07:** `backend/pricing/views.py`, `frontend/src/pages/UnitValidation.jsx`, `frontend/src/pages/PlanAudits.jsx`, `tests/test_api.py`, and this handoff. No migration was required. Browser interaction was **NOT TESTED**.

## MK-08 — Benchmark-Safe Drug Summaries

**Disposition: MK-08 VERIFIED by synthetic exact-Decimal regression coverage.** The original reproduction returned **`allowed_markup_multiple="5"`** for one `UNIT_UNRESOLVED` detail row with 10 units, $100 allowed and ASP $2, even though the stored detailed allowed and paid markups were both null.

### Actual BEFORE → AFTER calculation

BEFORE, `drug_analysis` selected a single ASP from an unordered set and reconstructed markup from all rows’ aggregate dollars and units, independently of each detailed row’s unit-review decision or stored markup:

```python
asp = next(iter(item["asp"])) if len(item["asp"]) == 1 else None
allowed_markup = allowed_unit / asp if asp else None
paid_markup = paid_unit / asp if asp else None
```

AFTER, eligibility requires the canonical detailed markup to be present and finite, validated unit-review evidence, valid selection/review/ASP SHA-256 references, a valid quarter, positive units and ASP, and a nonnegative finite numerator. `UNIT_UNRESOLVED`, `UNIT_AMBIGUOUS`, and `BILLING_UNIT_MISMATCH` block the comparison. Other quality states are evaluated against actual detailed metrics: the `NETWORK_UNVERIFIED` fixture with validated unit/source evidence and calculated detail remains eligible; a warning alone does not imply a unit decision.

```python
if (row.data_quality_status in blocking_quality
        or blocking_quality.intersection(row.data_quality_notes or [])
        or refs.get("unit_review_status") != "validated"):
    return "unit_not_validated"
...
if detail is None or not detail.is_finite() or detail < 0:
    return "detailed_markup_unavailable"
```

Engine result source references now preserve the validated billing quantity and unit. Within each quarter, eligible rows must agree on ASP value/source, unit-review source, billing quantity/unit and selected-scope source. Conflicting rows are excluded for that quarter. Same-quarter ratios are combined as `sum(price numerator) / sum(units × matching ASP)`, not as an unweighted average of ratios. The top-level markup and ASP remain null when the audit spans multiple quarters; each quarter gets its own breakdown. No arbitrary benchmark is selected.

Raw visible totals remain separate from eligible and excluded benchmark amounts/units. The response reports metric-specific eligible/excluded amounts, row/unit counts, quality counts and exclusion reasons so allowed and paid amounts reconcile without treating missing comparisons as zero. Null detailed markups in the Plan Audits table display “Not comparable.” PDF and CSV generation already serialize the canonical detailed-result markup fields; those paths were inspected and left unchanged. Savings opportunities are generated separately from the detail engine and are not derived from `drug_analysis` summary markups.

### Numeric regression results

`tests/test_api.py::test_mk08_drug_analysis_uses_only_compatible_detailed_benchmarks` reproduces the **5× → null** defect, then covers immutable Version 1 preservation and a synthetic Version 2 containing:

- Two eligible 2026Q1 rows: allowed $400 / (20 units × ASP $2) = **10×**; paid $320 / (20 × $2) = **8×**.
- An unresolved row and a validated-unit row with a missing detailed markup: neither contributes to Q1 metrics.
- A `NETWORK_UNVERIFIED` row with a populated, source-bound detailed calculation: included in Q2, allowed **5×**, paid exactly `100 / (10 × 3)`.
- Missing ASP, zero ASP, and same-quarter conflicting billing units (`MG` versus `VIAL`): excluded, with null quarter markups.
- A mixed-quarter audit (2025Q4, 2026Q1/Q2/Q3/Q4): top-level markup/ASP null; all quarter calculations remain separate.
- Visible allowed amount **$1,100** = eligible **$550** + excluded **$550**; excluded rows **6**, excluded units **55**. Paid amounts and units also reconcile exactly. Repeated requests return identical ordered results.

The model requires result allowed/paid amounts and units to be non-null; the test uses that schema invariant rather than inserting invalid null numerators. All financial assertions use `Decimal`, with no float tolerances.

**Files changed for MK-08:** `backend/pricing/plan_audit_engine.py`, `backend/pricing/plan_audit_run.py`, `frontend/src/pages/PlanAudits.jsx`, `tests/test_api.py`, and this handoff. No schema migration was required. Published immutable run result rows/artifacts were not modified.

## Combined MK-07 / MK-08 verification

- Baseline reproductions: MK-07 both Reviewer reads **403**; MK-08 unresolved detail returned **5×**.
- Focused tests: `test_mk07_reviewer_clinical_unit_validation_access` — **1 passed**; `test_mk08_drug_analysis_uses_only_compatible_detailed_benchmarks` — **1 passed**.
- Full backend suite: `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk07-mk08-final` — **113 passed in 61.41s**. This includes MK-01 through MK-06 regressions.
- Django `check`: **PASS**, no issues.
- `makemigrations --check --dry-run`: **PASS**, no changes detected; `migrate --check`: **PASS**, no pending migrations.
- React/Vite production build: **PASS**.
- `git diff --check`: **PASS**, with the existing informational CRLF warning for `frontend/src/main.jsx`.
- Browser testing: **NOT TESTED**. Production concurrency/deployment was not tested. No customer data, CMS reference data, or production Parquet files were changed. No commit, push, or deployment was performed.

MK-07: VERIFIED

MK-08: VERIFIED

Full pytest: 113 passed

Django checks: PASS

Frontend build: PASS

Migrations: not required

Browser testing: NOT TESTED

Overall: READY FOR MK-09

## MK-06 — Reviewer Organization Access (Implementation and Verification, 2026-11-05)

**Disposition: MK-06 VERIFIED at the API, test, and production-build level.** The requested local reproduction showed the core backend Reviewer grant was already implemented: a SUPER_ADMIN grant returned **201**, and the assigned Reviewer could access an audit in that organization (**200**). The missing behavior was primarily frontend discoverability and focused coverage of tenant scope and revocation. The backend role and Admin authorization boundary were retained.

### Initial reproduction and actual BEFORE code

Before application changes, `.venv\\Scripts\\python.exe -m pytest tests\\test_api.py::test_end_to_end_plan_audit_workflow -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk06-repro` passed (**1 passed**). In that existing synthetic workflow, an active REVIEWER was granted access with **HTTP 201** (`created: true`), and the assigned Reviewer opened the organization’s audit with **HTTP 200**. Thus the original backend rejection described in older audit material was not reproducible in this checkout.

The existing backend eligibility rule already included Reviewer, but validation text described an invalid target as a “Viewer”:

```python
except (TypeError, ValueError, get_user_model().DoesNotExist):
    return Response({"error": "A valid active Viewer user_id is required."}, status=400)
if not user.groups.filter(name__in=(CLIENT_GROUP, VIEWER_GROUP, ANALYST_GROUP, REVIEWER_GROUP)).exists():
    return Response({"error": "Organization access can be granted only to an Analyst, Reviewer, or Client account."}, status=400)
```

The active-user picker already included REVIEWER in its filter, but the visible prompt omitted that role and options did not identify eligible roles:

```jsx
<option value="">Select an active Analyst or Client</option>
{viewerUsers.map((item) => (
  <option key={item.id} value={item.id}>
    {item.display_name} ({item.username}, ID {item.id})
  </option>
))}
```

### Actual AFTER code and explanation

`backend/pricing/plan_audit_setup.py` retains its active, non-superuser target lookup, explicit CLIENT/legacy Viewer/ANALYST/REVIEWER allowlist, Admin-only grant/revoke gate, unique `get_or_create`, and audit-event logging. Only inaccurate validation messages were corrected:

```python
except (TypeError, ValueError, get_user_model().DoesNotExist):
    return Response({"error": "A valid active user_id is required."}, status=400)
if not user.groups.filter(name__in=(CLIENT_GROUP, VIEWER_GROUP, ANALYST_GROUP, REVIEWER_GROUP)).exists():
    return Response({"error": "Organization access can be granted only to an active Analyst, Reviewer, Client, or legacy Viewer account."}, status=400)
```

`frontend/src/pages/PlanAudits.jsx` now removes accounts already assigned to the selected organization from the picker, labels eligible application roles, and uses the requested prompt. The existing grant/revoke actions and refresh/error handling remain in place:

```jsx
const assignedUserIds = new Set(accessRows.map((row) => String(row.user_id)));
const assignableUsers = viewerUsers.filter((item) => !assignedUserIds.has(String(item.id)));
const roleLabels = { ANALYST: "Analyst", REVIEWER: "Reviewer", CLIENT: "Client", Viewer: "Legacy Viewer" };
...
<option value="">Select an active Analyst, Reviewer or Client</option>
{assignableUsers.map((item) => (
  <option key={item.id} value={item.id}>
    {item.display_name} ({item.username}; {(item.roles || [])
      .filter((role) => roleLabels[role])
      .map((role) => roleLabels[role]).join(", ")}; ID {item.id})
  </option>
))}
```

`tests/test_api.py::test_end_to_end_plan_audit_workflow` extends its synthetic lifecycle to assert duplicate grant behavior, invalid targets, forbidden self/CLIENT/ANALYST grant and Reviewer revoke attempts, Reviewer organization and audit visibility, other-organization exclusion, approval, and immediate access removal after Admin revocation. No new files, dependencies, migrations, or customer-data changes were introduced.

### Scenario results

| Scenario | Actual HTTP/result | Status |
|---|---:|---|
| SUPER_ADMIN grants active Reviewer to ABC | **201**, `created: true` | **PASS** |
| Duplicate Reviewer assignment | **200**, `created: false`; exactly one assignment row | **PASS** |
| Assigned Reviewer lists ABC and opens its audit | **200** for organization list and audit detail/list | **PASS** |
| Reviewer opens XYZ organization’s synthetic audit | **404**; organization list contains ABC only and excludes XYZ | **PASS** |
| Reviewer independently approves eligible current version | **200**; published version matches the reviewed run | **PASS** |
| Assigned Client reads published results, PDF and CSV | **200** for all three | **PASS** |
| Reviewer attempts self-grant or revoke | **403** for both | **PASS** |
| CLIENT or ANALYST attempts to grant access | **403** for both | **PASS** |
| Inactive Reviewer, unknown ID, missing ID, no-role user, or superuser target | **400** | **PASS** |
| Admin revokes Reviewer assignment | **204** | **PASS** |
| Same Reviewer session requests organizations after revocation | **200**, empty organization list | **PASS** |
| Revoked Reviewer requests audit detail or approval | **404** for both | **PASS** |

The test continues to cover the pre-existing publication, rejection, immutable-version, clinical validation, MFA, tenant-isolation, and MK-04/MK-05 role-boundary assertions in the same synthetic workflow. Organization access is queried from current server-side assignments on each request; the existing valid session/JWT does not preserve access after revocation.

### Verification and limits

- Baseline focused reproduction before application edits: **1 passed**.
- Focused expanded workflow: `.venv\\Scripts\\python.exe -m pytest tests\\test_api.py::test_end_to_end_plan_audit_workflow -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk06-final-focused` — **1 passed in 15.98s**.
- Full suite: `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk06-final2` — **111 passed in 23.16s**.
- Django `check`: **no issues**.
- `makemigrations --check --dry-run`: **no changes detected**; `migrate --check`: successful, no pending migrations.
- `npm --prefix frontend run build`: **passed**.
- `git diff --check`: passed; Git printed its existing informational CRLF notice for `frontend/src/main.jsx`.
- Browser interaction and production deployment were **NOT TESTED**. No real customer records or audits were used. No commit, push, or deployment was performed.

**MK-06: VERIFIED** for the acceptance criteria covered by automated API tests and the production build. Browser and deployment verification remain separate.

## Independent Re-verification — MK-04 and MK-05 (2026-11-05)

**Decisions: MK-04 VERIFIED. MK-05 VERIFIED. Overall: READY FOR MK-06.** This independent pass added missing boundary assertions and found no remaining bypass in the inspected local API/Admin paths. It made no application-code changes.

### Code inspected and identity provenance

- `backend/pricing/models.py`: `PlanAudit.created_by`, `PlanAuditRun.initiated_by`, `PlanAuditArtifact.created_by`, `approved_by`, and version-bound `AuditReview` relationships. Creator/initiator/builder FKs are nullable (`SET_NULL`), so the approval code must reject missing provenance.
- `backend/pricing/plan_audit_imports.py::create_plan_audit`: creator is assigned from `request.user`; client-supplied creator IDs are ignored.
- `backend/pricing/plan_audit_run.py::run_audit`: current run initiator is assigned from `request.user` while the new run is created under the audit transaction/lock.
- `backend/pricing/plan_audit_reports.py::generate_plan_report`: each immutable artifact records `created_by=request.user`. `_set_review` checks the current version and exact result fingerprint, source/calculation fingerprints, artifact bytes/report fingerprint, clinical-quality gate, contributor IDs and publication state before recording approval.
- `backend/pricing/plan_audit_common.py::audit_payload`: staff receives actor IDs/names; client-only metadata withholds actor IDs and financial fingerprints.
- `backend/pricing/admin.py`: `PlanAudit.created_by` is read-only; `PlanAuditRun` and `PlanAuditArtifact` are not registered in Django Admin. The API audit detail route is GET-only; run/artifact requests ignore forged actor fields and derive identity from the authenticated user.
- `backend/pricing/permissions.py`, `backend/pricing/plan_audit_common.py`, `backend/pricing/plan_audit_imports.py`, `backend/pricing/plan_audit_run.py`, `backend/pricing/plan_audit_reports.py`, `backend/pricing/auth_views.py`, `frontend/src/pages/PlanAudits.jsx`, and `tests/test_api.py` were also inspected for role gates, scope, frontend advisory controls and alternate approval routes.

Current approval guard (unchanged in this verification):

```python
if not audit.created_by_id or not run.initiated_by_id:
    return Response({"error": "Approval is unavailable because this audit's creator or run initiator identity is missing."}, status=409)
...
if any(artifact.created_by_id is None for artifact in artifacts.values()):
    return Response({"error": "Approval is unavailable because a report artifact builder identity is missing."}, status=409)
contributor_ids = {
    audit.created_by_id,
    run.initiated_by_id,
    *(artifact.created_by_id for artifact in artifacts.values()),
}
if request.user.pk in contributor_ids:
    return Response({"error": "You cannot approve an audit that you created, ran, or built. An independent reviewer must approve this version."}, status=403)
```

No identity update API was found. A request forging `created_by_id`, `initiated_by_id`, or artifact builder IDs did not override the authenticated database user. PUT/PATCH to audit detail return **405**. Admin inspection confirms creator is read-only and run/artifact models are unregistered. A deleted contributor becomes a null FK and approval fails closed. Direct trusted ORM/database edits are outside the supported application update paths and remain an operational privileged-access risk.

### Independent scenario results

Test names: `tests/test_api.py::test_end_to_end_plan_audit_workflow`, `tests/test_api.py::test_audit_result_and_savings_admin_is_read_only`, `tests/test_api.py::test_mk05_actual_role_classification_matrix`, and `tests/test_migrations.py::LegacyAuditApprovalMigrationTests::test_approved_legacy_audit_is_linked_but_not_published`. All use temporary pytest databases and synthetic data.

| Test ID | Scenario / account | Actual HTTP; expected | Database/result state | Result |
|---|---|---|---|---|
| M4-01 | Creator, separate run initiator and builders; creator approves | **403; 403** | Pending → pending; `published_version` null; no approved review/event; client report endpoints remain **404** | **PASS** |
| M4-02 | REVIEWER+ANALYST run initiator attempts approval | **403; 403** | Pending, no approval evidence | **PASS** |
| M4-03 | Separate PDF artifact builder attempts approval | **403; 403** | Pending, no approval evidence | **PASS** |
| M4-04 | Separate CSV artifact builder attempts approval | **403; 403** | Pending, no approval evidence | **PASS** |
| M4-05 | SUPER_ADMIN creates, runs, and builds both artifacts | **403; 403** | Pending; published version null; no approved review/event; client results/PDF/CSV **404** | **PASS** |
| M4-06 | Missing creator, initiator, PDF builder, or CSV builder identity | Each **409; 409** | Pending/unverified; published version null; no approved review/event | **PASS** |
| M4-07 | Independent authorized Reviewer approves valid run | **200; 200** | Pending → published; current version set; approval evidence recorded | **PASS** |
| M4-08 | Independent authorized SUPER_ADMIN approves valid run | **200; 200** | Pending → published; approval evidence recorded | **PASS** |
| M4-09 | Client or Analyst calls approval | **403; 403** | No publication or approval evidence | **PASS** |
| M4-10 | Unassigned or other-tenant Reviewer approves/rejects | **404; 404** | Target audit unchanged | **PASS** |
| M4-11 | Wrong result fingerprint or stale version/binding | **409; 409** | Pending/current publication unchanged | **PASS** |
| M4-12 | Legacy `legacy_unverified` run without provenance attempts approval | **409; 409** | `unverified`, `published_version` null; historical approval remains history only | **PASS** |
| M5-01 | Superuser with no app groups lists, opens and runs draft | List/detail/run **200; 200** | Draft → running/completed; privileged results inspectable | **PASS** |
| M5-02 | Assigned CLIENT lists/opens draft metadata; requests financial routes/PDF/CSV | Safe list/detail **200**; unpublished finance/downloads **404**; run **403** | No publication change; summary/fingerprint withheld | **PASS** |
| M5-03 | Unassigned CLIENT, CLIENT+REVIEWER, or CLIENT+ANALYST crosses organization | Detail **404**; audit absent from list | No cross-tenant data returned | **PASS** |
| M5-04 | Assigned Analyst/Reviewer and assigned CLIENT+REVIEWER | Scoped list/detail/results **200**; Analyst execution **200**; Reviewer execution **403**; mixed CLIENT+REVIEWER reads unpublished results **200** only in its assigned organization | Existing explicit staff-role capabilities retained; cross-tenant request remains **404** | **PASS** |
| M5-05 | Role matrix: superuser no groups / with CLIENT, SUPER_ADMIN group, Analyst, Reviewer, Client, Viewer, mixed CLIENT+Reviewer/Analyst, no role, inactive Client | Active permitted list calls **200**; no-role **403**; inactive Client **401** | Authorization-only cases; no audit state changed | **PASS** |
| M5-06 | MK-03 publish → reject → stale approval, rerun, failure and new approval | Approval **200**, rejection **200**, stale approval **409**, failed-run routes **404**, new-version approval **200** | Version-bound publication/revocation remains correct | **PASS** |

Role policy confirmed by the matrix: `has_any_role()` intentionally grants permission inheritance to Django superusers; `is_client_only()` excludes privileged authority, so superusers are not clients even if explicitly assigned CLIENT. Explicit privileged application roles (SUPER_ADMIN, ANALYST, REVIEWER) take precedence over CLIENT/Viewer restrictions; a CLIENT+REVIEWER therefore has Reviewer capabilities only within its assigned organization, and a CLIENT+ANALYST has Analyst capabilities only within its assigned organization. Cross-tenant access remains **404**. A user with no role is not “client-only,” but `CanView` denies access (**403**). An inactive CLIENT retains client classification, while authentication rejects it (**401**). This is the current deliberate mixed-role behavior.

The test also confirms a real CLIENT can read safe unpublished metadata but cannot read unpublished financial data. After approval, assigned CLIENT result/PDF/CSV access is **200**; unassigned and cross-tenant users remain denied.

### Verification and limits

- Separate focused MK-04 command: **3 passed**.
- Separate focused MK-05 command: **2 passed**.
- Full suite: **111 passed**.
- Django `check`: **no issues**; `makemigrations --check --dry-run`: **no changes detected**; `migrate --check`: successful; no migration needed.
- React/Vite build: **passed**; `git diff --check`: passed except the existing CRLF informational notice.
- Browser testing: **NOT TESTED**; no browser automation package/browser executable or active local Django/Vite listeners were available.
- SQLite uses no row-level `SELECT FOR UPDATE`; transaction concurrency limitations documented under MK-03 remain. No concurrent multi-worker approval/rejection test was run.
- No defect was found in the current MK-04/MK-05 application paths. This pass changed only `tests/test_api.py` and this handoff; no customer data, migration, application code, commit, push or deployment was changed.

**MK-04: VERIFIED.**

**MK-05: VERIFIED.**

**Overall: READY FOR MK-06.**

## MK-05 — Superuser and CLIENT Role Separation (2026-11-05)

**Disposition: MK-05 VERIFIED.** Inspection found that the current local MK-02 helper already avoids the reported classification bug, so no application code was changed. MK-05 regression assertions were added to the existing synthetic audit workflow.

### Local role logic and root cause

`has_any_role()` intentionally treats Django superusers as authorized for every requested permission role. The dangerous pattern would be using only a CLIENT membership check as an identity test. The current local `is_client_only()` instead requires CLIENT/Viewer access **and** the absence of every privileged role:

```python
def is_client_only(user):
    return (has_any_role(user, {CLIENT_GROUP, VIEWER_GROUP})
            and not has_any_role(user, {SUPER_ADMIN_GROUP, ADMIN_GROUP, ANALYST_GROUP, REVIEWER_GROUP}))
```

Since `has_any_role()` returns true for superusers for both checks, `is_client_only(superuser)` evaluates false. Explicit SUPER_ADMIN, Analyst, and Reviewer accounts are likewise not client-only. CLIENT/legacy Viewer accounts with no privileged role remain restricted. `visible_organizations()` separately uses `is_admin()` so superusers retain administrative organization visibility. No broad change to permission inheritance was appropriate.

### Isolated regression test and actual responses

`tests/test_api.py::test_end_to_end_plan_audit_workflow` now explicitly checks the relevant role boundary on disposable synthetic audit data:

| Scenario | Actual response / assertion | Result |
|---|---|---|
| SUPER_ADMIN lists an unpublished draft | `GET /api/v1/plan-audits/` **200**, draft present | **PASS** |
| SUPER_ADMIN opens draft detail | `GET /api/v1/plan-audits/{id}/` **200**, status `draft` | **PASS** |
| SUPER_ADMIN runs a valid draft | `POST /api/v1/plan-audits/{id}/run/` **200** | **PASS** |
| SUPER_ADMIN inspects completed unpublished run | Overview/results **200** | **PASS** |
| Assigned CLIENT sees safe draft metadata | List/detail **200**, no result capability, summary empty and result fingerprint null | **PASS** |
| Assigned CLIENT requests unpublished financial data/PDF/CSV | Overview, results, drug/hospital/ASP/historical, savings, quality, network, PDF and CSV each **404** | **PASS** |
| CLIENT attempts to run a draft | **403** | **PASS** |
| CLIENT accesses an approved audit | Results/PDF/CSV **200** in the existing publication flow | **PASS** |
| Unassigned CLIENT accesses another organization's audit | Detail **404**; audit absent from list | **PASS** |
| Assigned Analyst and Reviewer access | List/detail/results **200** within assigned organization; Reviewer run attempt **403**; Analyst run in its permitted workflow **200** | **PASS** |
| Superuser self-approval / independent approval | MK-04 regression: self-approval **403** with no publication; independent Reviewer and SUPER_ADMIN **200** | **PASS** |
| Rejection and stale approval | MK-03 regression: rejection revokes; stale approval **409** | **PASS** |

### BEFORE / AFTER and changed files

BEFORE this verification, the local helper already had the privileged-role exclusion shown above; the test did not assert superuser draft listing, detail, execution, or the full assigned/unassigned client boundary. AFTER, the same application logic is protected by explicit regression assertions. There was no reproducible superuser-as-client failure in this workspace.

- `tests/test_api.py` — added the superuser/client/analyst/reviewer role-boundary and draft API assertions to the synthetic end-to-end lifecycle.
- `docs/PROJECT_HANDOFF.md` — recorded this verification.
- No application code, customer datasets, or migrations were changed.

`frontend/src/pages/PlanAudits.jsx` already treats `SUPER_ADMIN` as Admin/Analyst/Reviewer for the audit view and applies client-only UI restrictions only to users lacking those roles. The production build passed. A browser-driven interaction was not run; local browser and service availability was previously unavailable. SQLite row-lock concurrency limitations are documented under MK-03 and are unchanged.

### Verification results

- Focused `tests/test_api.py::test_end_to_end_plan_audit_workflow`: **1 passed**.
- Full pytest suite: **110 passed**.
- Django `check`: **no issues**.
- `makemigrations --check --dry-run`: **no changes detected**.
- `migrate --check`: successful; no migration required.
- React/Vite production build: **passed**.
- `git diff --check`: passed except the existing CRLF informational notice.
- MK-01 through MK-04 regressions passed in the full suite. No commit, push, or deployment was performed.

## MK-04 — Independent Creator/Builder Approval Verification (2026-11-05)

**Disposition: MK-04 VERIFIED.** The old code checked only whether the approver initiated the current run. It did not compare the audit creator or report artifact builders.

### BEFORE and reproduction

Actual BEFORE approval guard in `backend/pricing/plan_audit_reports.py::_set_review`:

```python
if run.initiated_by_id == request.user.pk:
    return Response({"error": "An independent reviewer must approve this run."}, status=409)
```

Two local synthetic reproductions were performed before restoring the fix:

- The SUPER_ADMIN who created, ran, and generated the report attempted to approve: **409**, with run state still `pending` and `published_version=None`. This did not satisfy the required self-approval **403** behavior.
- More critically, the SUPER_ADMIN creator who did not initiate the run attempted approval while another authorized analyst ran it and built the valid artifacts: response **200**; `PlanAudit.published_version` became the current version and the run became `published`. This confirmed the creator-only approval bypass.

No real customer audit or data was used.

### AFTER

Inside the existing transaction and version locks, approval now requires recorded identities for the audit creator, run initiator and both report builders. A requester matching any of those server-recorded IDs gets **403**. Missing creator, initiator, or artifact builder identity returns **409**, fail-closed, before creating an approval review or changing publication state.

```python
if not audit.created_by_id or not run.initiated_by_id:
    return Response({"error": "Approval is unavailable because this audit's creator or run initiator identity is missing."}, status=409)
...
if any(artifact.created_by_id is None for artifact in artifacts.values()):
    return Response({"error": "Approval is unavailable because a report artifact builder identity is missing."}, status=409)
contributor_ids = {
    audit.created_by_id,
    run.initiated_by_id,
    *(artifact.created_by_id for artifact in artifacts.values()),
}
if request.user.pk in contributor_ids:
    return Response({
        "error": "You cannot approve an audit that you created, ran, or built. An independent reviewer must approve this version."
    }, status=403)
```

An independent authorized Reviewer or SUPER_ADMIN can still approve after the existing current-version, source/result/artifact fingerprint, artifact-byte, clinical quality and publication-state checks pass. The identity values come from `PlanAudit.created_by`, `PlanAuditRun.initiated_by`, and `PlanAuditArtifact.created_by`; the review request cannot supply them. Django Admin now displays `PlanAudit.created_by` as read-only. Audit payloads return creator, initiator and builder names/IDs only to non-client staff so the interface can explain a disabled approval action.

### Regression and verification

`tests/test_api.py::test_end_to_end_plan_audit_workflow` verifies:

- SUPER_ADMIN creator + runner + artifact builder self-approval: **403**, no approved review, run remains pending, published version remains null.
- Creator who did not run, run initiator who did not create, and artifact builder: each **403**, no publication evidence.
- Analyst without Reviewer role: **403**. Assigned client report while pending: **404**.
- Missing audit creator, run initiator, or artifact-builder identity: each **409**, no publication.
- Independent Reviewer approval: **200**. Separate independent SUPER_ADMIN approval: **200**.
- Existing MK-03 rejection finality, cross-organization reviewer denial (**404**), stale binding rejection (**409**), MK-02 immutability/legacy migration, and MK-01 MFA/JWT logout tests remain in the full suite.

The pre-fix creator-only bypass was reproduced as **200 / published**; the post-fix regression is **403 / pending / no approval review**. Client report access remains **404** after denied self-approval.

- Focused workflow and Admin tests: **2 passed**.
- Full pytest suite: **110 passed**.
- Django `check`: **no issues**; `makemigrations --check --dry-run`: **no changes detected**; `migrate --check`: successful.
- React/Vite production build: **passed**; `git diff --check`: passed except the existing CRLF notice.
- No migration was required. Browser and deployment verification remain separate; local database concurrency limitations documented under MK-03 still apply.

### Files changed for MK-04

- `backend/pricing/plan_audit_reports.py` — enforce creator, run initiator, and artifact-builder independence and fail closed for missing identities.
- `backend/pricing/plan_audit_common.py` — provide staff-only actor IDs/names for approval guidance.
- `backend/pricing/admin.py` — make audit creator identity read-only in Django Admin.
- `frontend/src/pages/PlanAudits.jsx` — display creator/initiator/builders, disable contributor approval, and explain the restriction; backend 403 remains authoritative.
- `tests/test_api.py` — capture the pre-fix repro and add creator, runner, builder, missing-identity, independent Reviewer/SUPER_ADMIN and client denial assertions.
- `docs/PROJECT_HANDOFF.md` — this verification record.

No commit, push, or deployment was performed. Existing MK-01, MK-02, and MK-03 changes are preserved.

## MK-03 — Rejection Revokes Publication (2026-11-05)

### Independent verification (2026-11-05)

The requested sequence was run with disposable users, a generated synthetic claims import, and isolated Django test data. The workflow test was extended because the earlier test approved Version 2 (Version 1 intentionally contained unresolved clinical data). The new lifecycle explicitly approves v1, rejects v1, then approves a fresh v2.

| Scenario | Evidence / actual response | Result |
|---|---|---|
| Reviewer A approves Version 1 | `test_end_to_end_plan_audit_workflow`; approve response **200**, version `1` | **PASS** |
| Assigned client reads approved results, PDF and CSV | Same test; all three **200** before rejection | **PASS** |
| Reviewer B rejects v1; reason required | Reject response **200**, publication `rejected`, `published_version=null`; whitespace reason **400** | **PASS** |
| Publication is revoked and financial routes/artifacts close | Client overview, results, report/PDF, CSV, savings, quality each **404** after rejection | **PASS** |
| Reviewer A reuses v1 approval binding / direct republish | Approval response **409**; rejected run cannot be republished in place | **PASS** |
| Review history retained | Reviewer endpoint **200**; history contains `rejected` and `approved`, with full rejection reason | **PASS** |
| Safe client metadata | Client list remains **200**, says `rejected`, exposes reviewer/time, has empty summary and null result fingerprint | **PASS after privacy fix** |
| Fresh Version 2 approval restores access | Run v2, generate fresh artifacts, independent approval **200**; results/PDF/CSV **200** only after approval | **PASS** |
| Unauthorized and cross-organization reviewers | Reviewer role without organization assignment: reject **404**; reviewer from another organization: reject **404**. Client-only user trying to review: **403** | **PASS** |
| Stale version identifier | Reject with version `0` against current v1: **409**; stale v2 binding after rerun: **409** | **PASS** |
| MK-01 / MK-02 regressions | Full suite includes bearer logout, admin MFA, immutable result/savings, populated legacy migration, failed rerun and versioning cases | **PASS** |

**Additional defect found during independent verification:** audit-list metadata returned reviewer free-text rejection comments to clients. This was reproduced using a synthetic reason containing `$123456.78`; the pre-fix response included that amount. `audit_payload()` now returns `reason: null` for client-only users while retaining the full comment in reviewer history. The regression asserts the synthetic amount is absent from all client metadata. No other application defect was reproduced.

**Commands/results:** focused `tests/test_api.py::test_end_to_end_plan_audit_workflow` — **1 passed**; full pytest — **110 passed**; `manage.py check` — no issues; `makemigrations --check --dry-run` — no changes; `migrate --check` — successful; frontend Vite build — passed; `git diff --check` — passed except the existing CRLF informational notice. No migration or customer data change was made.

**Browser testing: NOT TESTED.** No local Django/Vite listeners were active on ports 8000/8001/5173/5174, and no Playwright/Puppeteer package or browser executable was available in the workspace.

**Concurrency limitation:** the local configured database is SQLite. `_set_review()` uses one atomic transaction and calls `select_for_update()` on both `PlanAudit` and `PlanAuditRun`, but SQLite does not implement row-level `SELECT FOR UPDATE`; concurrent approval/rejection requests were not exercised. SQLite serializes writes at database level and concurrent write contention may return a lock error. Verify simultaneous decision behavior on the intended deployment database (and use a row-locking database such as PostgreSQL for multi-worker concurrency) before claiming production concurrency verification.

**Independent disposition: MK-03 VERIFIED for the sequential publication/rejection acceptance flow.** Browser and simultaneous production-database concurrency remain NOT TESTED as described above. No commit, push, or deployment was performed.

**Disposition: implemented and regression verified.** MK-02 already made publication depend on the exact current run and required `PlanAudit.published_version` to match it, so an older approval could not authorize a rerun. The remaining defect was a same-version state transition: after one reviewer rejected a published run, another reviewer could submit the old approval binding and republish that same run. The reproduction returned HTTP 200 before the fix.

### Actual BEFORE → AFTER

**`backend/pricing/plan_audit_reports.py::_set_review`**

BEFORE, after validating the run binding, review always overwrote the run state; an approval could therefore reverse a rejection on the same version:

```python
review = AuditReview.objects.create(plan_audit=audit, audit_run=run, reviewer=request.user,
                                    review_status=status, comments=comments)
run.review_status = status
run.publication_status = "published" if status == "approved" else "rejected"
...
audit.published_version = run.version if status == "approved" else None
```

AFTER: audit and current run are locked; a run accepts approval only while pending, and rejection only while pending or published. Rejected runs are final, with a new version required for reconsideration.

```python
run = PlanAuditRun.objects.select_for_update().filter(
    plan_audit_id=audit.pk, version=audit.current_version,
).first()
...
if status == "approved" and run.publication_status != "pending":
    return Response({"error": "This run is no longer pending approval. Start a new version for republication."}, status=409)
if status == "rejected" and run.publication_status not in {"pending", "published"}:
    return Response({"error": "This run has already received a final publication decision."}, status=409)
...
if status == "rejected":
    run.revoked_at = timezone.now()
    run.revocation_reason = comments
...
audit.published_version = run.version if status == "approved" else None
```

The rejection also creates an append-only version-bound `AuditReview` and an `AuditEvent` containing version, result fingerprint, actor and reason. The response returns the reviewer, timestamp, reason and revoked publication state. A later ordinary comment remains historical commentary and cannot change publication state.

**`backend/pricing/plan_audit_common.py::audit_payload` and `frontend/src/pages/PlanAudits.jsx`**

BEFORE, a client-safe pending audit had no decision details, and the review panel labeled every completed non-published run “Pending Approval”; its Approve button stayed enabled after rejection.

AFTER: the shared safe metadata includes only the latest approved/rejected decision’s status, reviewer, timestamp and reason. It still hides the summary and result fingerprint for clients. The UI labels a rejection “Rejected — publication revoked,” shows the decision context, disables approval for a non-pending run and disables client downloads until publication.

```javascript
const publicationLabel = audit?.publication_status === "published" ? "Published" :
  audit?.publication_status === "rejected" ? "Rejected — publication revoked" :
  audit?.publication_status === "failed" ? "Failed — not publishable" :
  audit?.calculation_status === "running" ? "Running" :
  audit?.calculation_status === "completed" ? "Pending Approval" : audit?.calculation_status;
```

### Regression and verification

- `tests/test_api.py::test_end_to_end_plan_audit_workflow` reproduces approved → reviewer B rejection → reviewer A attempts old approval (HTTP 409) → client access denied on financial-data/report routes → new run → new-version approval restores access. It checks safe client decision metadata, missing rejection reason, client and stale binding denials, and failed-run non-publication.
- The shared `published_run()` gate remains authoritative for client detail/data/PDF/CSV access. Rejection clears `published_version`; old artifact routes therefore return 404. Reapproval of a rejected version is refused; a new numbered run can be approved after fresh artifacts and review.
- No schema change or migration was needed. Existing reviews and publication events remain preserved.
- Focused workflow test: **1 passed**. Full pytest suite: **110 passed**.
- `manage.py check`: **no issues**. `makemigrations --check --dry-run`: **no changes detected**. `migrate --check`: successful exit.
- `npm run build` in `frontend`: **passed**.
- Browser interaction and real multi-request concurrency against the production database are **not tested**. The handler locks both audit and run rows; verify actual locking behavior in the deployment database before release. No commit, push or deployment was performed.

### Modified files for MK-03

- `backend/pricing/plan_audit_reports.py` — lock run and enforce final rejection state, record rejection time/reason and audit event details, return decision metadata.
- `backend/pricing/plan_audit_common.py` — expose only safe latest-decision metadata in audit payloads.
- `frontend/src/pages/PlanAudits.jsx` — display rejection decision, clarify status and constrain controls/downloads.
- `tests/test_api.py` — reproduce the defect and verify revocation, stale approval rejection, client denial and new-version restoration.
- `docs/PROJECT_HANDOFF.md` — this implementation record.

No changes were made to the preserved MK-01 MFA/OTP, DuckDB, or MK-02 run-versioning design in this MK-03 fix.

## MK-01 / MK-02 Blocking Remediation Closure (2026-11-05)

**Current disposition: MK-01 VERIFIED; MK-02 VERIFIED; READY FOR MK-03 at the code/test level.** This section supersedes the earlier independent review below. Browser-driven login/UI verification and deployment verification have not been performed.

### Actual BEFORE code

`backend/pricing/auth_views.py::logout_view` revoked only the request cookie session:

```python
def logout_view(request):
    user = request.user
    AuditEvent.objects.create(actor=user, action="logout", entity_type="user", entity_id=str(user.pk))
    logout(request)
    return Response({"ok": True})
```

`backend/pricing/admin.py` registered audit result and savings records with Django's editable default admin:

```python
for model in (
    PlanOrganization, Plan, ClaimsSummaryImport, ClaimsSummaryRecord,
    NetworkRosterEntry, PlanAudit, PlanAuditResult, SavingsOpportunity,
):
    admin.site.register(model)
```

Before this remediation, the result/savings models inherited the ordinary `models.Model` save/delete behavior and default manager; there were no queryset write guards. On calculation errors `plan_audit_run.py` set only `calculation_status="failed"`, leaving `publication_status="pending"`.

### Actual AFTER code

Bearer logout checks token subject and validates the token's live session evidence before deletion; a cookie is flushed only if it belongs to the authenticated user:

```python
claims = request.auth if isinstance(request.auth, dict) else None
if claims is not None:
    if (str(claims.get("sub")) != str(user.pk)
            or not revoke_mfa_session(user, claims.get("sid"), claims.get("mfa_at"))):
        return Response({"error": "The authenticated session could not be revoked."}, status=401)
if mfa_session_is_valid(request.session, user):
    logout(request)
```

`revoke_mfa_session()` reloads the server-side session and verifies its user, Django auth hash, MFA timestamp, session-key binding, age, and enabled-device timestamp before `SessionStore.delete()`. The cookie-only path continues through `MFASessionAuthentication` CSRF enforcement.

Both snapshot models inherit `ImmutableAuditRunRow`; its manager permits bulk creation only while the referenced run is `running`, and instance/queryset save, update, and delete operations reject completed runs. The Admin registration uses an inspection-only `AuditRunRowAdmin` with all model fields readonly and add/change/delete disabled. Normal engine `bulk_create` remains allowed inside the active calculation transaction.

Failed execution now stores both `calculation_status="failed"` and `publication_status="failed"`, so failure cannot present as pending approval.

### Modifications and regression coverage

- `backend/pricing/auth_views.py`, `backend/pricing/mfa.py`: revoke the authenticated bearer `sid`; reject invalid/mismatched ownership; do not flush a different user's cookie session; preserve CSRF for cookie-backed logout.
- `backend/pricing/admin.py`, `backend/pricing/models.py`: read-only Admin and ORM-level write guards for `PlanAuditResult` and `SavingsOpportunity`. Engine creation is constrained to active runs; completed/legacy rows cannot be saved, bulk-updated, or deleted through supported ORM paths.
- `backend/pricing/plan_audit_run.py`, migration `0012_audit_run_rows_immutable_and_failed_publication.py`: explicit nonpublishable failed publication status.
- `tests/test_otp.py::test_bearer_logout_revokes_only_its_verified_session`: bearer-only logout, revoked token reuse, mixed bearer-A/cookie-B ownership, unaffected user B session, invalid/anonymous logout, cookie-backed logout, and CSRF rejection/acceptance.
- `tests/test_api.py::test_end_to_end_plan_audit_workflow`: confirms unresolved engine output cannot be approved; generates validated rows only during an active test run; after publication, instance save/delete, queryset update/delete, and bulk creation of results/savings are rejected; rerun, reapproval, and failed v4 remain gated. `test_audit_result_and_savings_admin_is_read_only` verifies Admin permissions.
- `tests/test_migrations.py::LegacyAuditApprovalMigrationTests::test_approved_legacy_audit_is_linked_but_not_published`: creates a populated approved v1 legacy audit, migrates it through `0011`, and proves legacy approval remains history with `published_version=None`, `publication_status="unverified"`, and no approving user on the new run.

### Final verification

- Focused tests: **4 passed**.
- Full backend suite: `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\remediation-final2` — **110 passed**.
- Django `check`: **no issues**.
- `makemigrations --check --dry-run`: **no model/migration drift**.
- `migrate --check`: **no pending migrations**; local `pricing.0012_audit_run_rows_immutable_and_failed_publication` is applied.
- `npm run build` from `frontend`: **passed**.
- `git diff --check`: passed apart from the existing informational CRLF notice for `frontend/src/main.jsx`.
- Local operational DB had no customer audit rows; only the migration ledger was advanced. No live audits/data were changed.

**MK-01: VERIFIED. MK-02: VERIFIED. Overall: READY FOR MK-03.** Browser automation and deployment/runtime verification remain separate and unperformed. No commit, push, or deployment was performed.

## Independent MK-01 / MK-02 Verification (2026-11-05)

**Final disposition: MK-01 NOT VERIFIED; MK-02 NOT VERIFIED; overall BLOCKED for MK-03.** Automated checks pass, but two acceptance issues remain. In MK-01, a bearer-only logout request does not invalidate the Django session named by the JWT; `logout_view()` flushes only `request.session`, while bearer authentication validates a separate `sid` session. In MK-02, `PlanAuditResult` and `SavingsOpportunity` are registered with Django Admin using the default editable admin, so authorized Admin users can alter or delete historical version rows. Result-hash validation fails closed for client reads after an edit, but that does not make the rows immutable or preserve the historical record. No implementation code was changed during this independent review. Two isolated assertions were added to existing tests: expired MFA sessions cannot refresh, and failed reruns leave client access denied.

### MK-01 findings

| Acceptance area | Files / method inspected | Test or evidence | Result |
|---|---|---|---|
| Password-only Admin/API access; staff + MFA for Django Admin | `backend/pricing/mfa_admin.py` (`has_permission`, `login`), `backend/pricing/jwt_auth.py` (`MFASessionAuthentication`), `backend/pricing/admin.py` | `tests/test_otp.py::test_mfa_boundary_blocks_admin_sessions_and_legacy_tokens`; `test_mfa_session_evidence_is_bound_to_the_authenticated_user_and_admin_staff_status` | **PASS** — password-only Admin login is forbidden; forced legacy session gets 401 on protected API and Admin index; valid MFA plus staff works; MFA non-staff cannot enter Admin. |
| Password-only token minting; access-token MFA binding; logout invalidation | `backend/pricing/auth_views.py` (`_access_token`, `refresh_access`, `logout_view`), `backend/pricing/mfa.py`, `backend/pricing/jwt_auth.py` | Same MFA boundary test; legacy token rejection and post-logout bearer rejection | **PASS** — issuance refuses sessions without MFA evidence; JWT requires `sid` and `mfa_at`, validated against the live session; logout invalidates that backing session/token. |
| Expired session cannot access protected endpoints or refresh | `backend/pricing/mfa.py`, `backend/pricing/jwt_auth.py`, `backend/pricing/auth_views.py` | Added `verified.post("/api/v1/auth/refresh/") == 401` after aging session evidence in `tests/test_otp.py` | **PASS** — protected API and refresh both reject expired evidence. |
| Current OTP acceptance, replay, strict neighboring-step rejection, recovery one-time use | `backend/pricing/otp.py`, `backend/pricing/auth_views.py` | `tests/test_otp.py::test_totp_code_window_and_provisioning_uri`, `test_totp_window_is_configurable_but_strict_by_default`, `test_canonical_password_totp_and_session_refresh_flow`, `test_admin_authenticator_is_required_after_password_and_code_cannot_replay` | **PASS** — current code succeeds; used step and used recovery code fail; previous/next steps fail with configured 0/0 windows. Runtime reports windows 0/0. |
| CSRF/session login flow | `backend/pricing/auth_views.py`, `frontend/src/api.js`, `frontend/src/main.jsx` | `test_canonical_password_totp_and_session_refresh_flow` uses `Client(enforce_csrf_checks=True)` through password challenge, TOTP, and token refresh | **PASS for API CSRF/session flow.** A real browser interaction was **NOT TESTED**; Vite build is not a browser login test. |
| Logout invalidates token session | `backend/pricing/auth_views.py::logout_view`, `backend/pricing/jwt_auth.py::AccessTokenAuthentication`, `backend/pricing/mfa.py::token_mfa_session_is_valid`, `frontend/src/api.js::logout` | Existing test proves cookie-backed logout invalidates its JWT. Static inspection of bearer-only path: token `sid` is in `request.auth`, but `logout_view` only calls Django `logout(request)` on the request's cookie session; no `sid` session deletion occurs | **FAIL / bearer-only method NOT TESTED.** If an API client submits only the bearer token, logout leaves the token's MFA session live and the token remains usable until expiry. Frontend same-origin logout includes the session cookie and passes the existing test; the API security invariant must hold for bearer callers too. |
| All authentication overrides/token issuance paths | `backend/pricing/auth_views.py`, `backend/pricing/jwt_auth.py`, `backend/pricing/mfa.py`, `backend/pricing/mfa_admin.py`, `backend/pricing/admin_config.py`, `backend/pricing/v1_urls.py`, `backend/pricing/urls.py`, `backend/auditapi/settings.py`, frontend auth files | Static route/override inspection plus MFA tests above | **PASS except bearer-only logout finding above.** Canonical and legacy refresh paths use MFA-enforcing session auth; JWT issuance is centralized in `_access_token`; custom AdminSite is installed. |

### MK-02 findings

| Acceptance area | Files / method inspected | Test or evidence | Result |
|---|---|---|---|
| New run numbering, preserve old rows, revoke publication before calculation | `backend/pricing/plan_audit_run.py::run_audit`, `backend/pricing/plan_audit_engine.py`, models | `tests/test_api.py::test_end_to_end_plan_audit_workflow` verifies v1 → v2, client denial, and v2 reapproval; source inspection confirms run-start transaction clears `published_version` before engine call | **PASS for API flow.** Test does not compare every v1 result/artifact byte after v2; no direct corruption test was run. |
| Results, savings, reviews, PDF/CSV bound to a run; source/result/artifact hashes; stale approval denied; reviewer independent | `backend/pricing/models.py`, `plan_audit_common.py`, `plan_audit_reports.py`, `plan_audit_engine.py`, `plan_audit_run.py` | E2E approval/rerun/stale approval tests; code checks version, result fingerprint, source hash and calculation fingerprint at approval and artifact hashes at download/publication | **PASS for implemented request paths.** Legacy approval is not carried into a published version. |
| Failed rerun cannot reopen client reads | `backend/pricing/plan_audit_run.py::run_audit`, `plan_audit_common.py::published_run` | Added failing-engine branch to the E2E test; v3 returns 500 and client overview/results/PDF/CSV remain 404 | **PASS.** Failed run metadata currently reports `publication_status="pending"` while `calculation_status="failed"`; client access remains denied, but the publication label is semantically stale. |
| Client direct endpoint gate, organization scope, safe pending metadata, stored exact artifacts, old URL revocation | `backend/pricing/permissions.py`, `plan_audit_common.py`, `plan_audit_imports.py`, `plan_audit_run.py`, `plan_audit_reports.py`, urls | E2E exercises overview/results/savings/quality/report/CSV denial during unpublished run, restored access after approval, and cross-organization 404; shared `get_visible_audit` check inspected | **PASS for endpoint authorization and tested cases.** URL paths identify the audit rather than a version; while unpublished they deny access, and after approval they return the current stored artifact. |
| Historical result immutability | `backend/pricing/admin.py` lines 70–73; `backend/pricing/models.py`; `backend/pricing/plan_audit_common.py::published_run` | Static registration inspection: `PlanAuditResult` and `SavingsOpportunity` use default `ModelAdmin` with editable fields and default change/delete permissions | **FAIL.** Admin users with model permissions can edit/delete old run data. Hash checks detect many edits and deny client publication, but do not preserve immutable history. This blocks MK-02 verification and MK-03 readiness. |
| UI Running/Pending Approval/Published, stale metrics, client download guard | `frontend/src/pages/PlanAudits.jsx` | Code inspection and production build; local state clears before rerun, client-pending detail avoids result calls, downloads use server capability flags | **PASS by inspection/build.** Dynamic browser interaction was **NOT TESTED**. |
| Unresolved clinical units cannot publish | `backend/pricing/plan_audit_reports.py::_set_review`, `backend/pricing/plan_audit_engine.py`, `tests/test_api.py` | Approval rejects any run row with `data_quality_status != "VALID"`; E2E manually marks the isolated fixture VALID before exercising the successful publication branch | **PASS by guard inspection.** E2E does not exercise a separate rejection assertion for the unresolved normal-engine rows; those rows are inspected before the fixture explicitly changes them. |

### Migration and local data

- `pricing.0011_plan_audit_run_versions` is applied; `showmigrations pricing` reports `[X]`.
- `makemigrations --check --dry-run` reports no changes; `migrate --check` reports no pending migrations.
- The configured local operational database contains **0 PlanAudit rows, 0 legacy runs, and 0 legacy reviews**. Therefore no customer/live audit rows were changed, but the legacy-linking data migration was **NOT TESTED against an existing approved legacy audit** in this environment.
- Static migration review: audits with prior results, savings, reviews, completed/running/failed status or report timestamps receive a version-1 `legacy_unverified` run; linked review rows remain historical, while run review/publication state is `unverified` and `published_version` is null. No historical approval is promoted.

### Commands executed

- `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\audit-final` — **107 passed**.
- `.venv\\Scripts\\python.exe backend\\manage.py check` — **no issues**.
- `.venv\\Scripts\\python.exe backend\\manage.py makemigrations --check --dry-run` — **no changes detected**.
- `.venv\\Scripts\\python.exe backend\\manage.py migrate --check` — **no pending migrations**.
- `npm run build` from `frontend` — **passed**.

**Decision:** MK-01 **NOT VERIFIED** because bearer-only logout does not revoke its backing session. MK-02 **NOT VERIFIED** because version-linked results/savings are editable/deletable in Django Admin and legacy migration behavior has no populated legacy fixture test. Overall readiness: **BLOCKED** until logout revokes the JWT's `sid`, historical run rows are protected from edits/deletes, and focused logout, immutability, and populated-legacy-migration tests pass. No commit, push, deploy, live audit or customer data change was performed.

## MK-02 Implementation Record — Acceptance Still Open (2026-11-05)

The implementation changes and prior checks are recorded here. Independent verification above found unresolved acceptance gaps; do not treat this section's implementation record as final acceptance. The BEFORE excerpts and baseline failure mechanism are below.

### BEFORE → AFTER code

**`backend/pricing/plan_audit_run.py` — mutable rerun replaced with version creation and durable revocation.**

BEFORE: the rerun marked the audit running, deleted `audit.results` and `audit.savings_opportunities`, then repopulated them. It left the old report timestamp/review usable.

AFTER (actual implementation):

```python
previous = current_audit_run(audit)
if previous and previous.publication_status in {"pending", "published"}:
    previous.publication_status = "revoked"
    previous.revoked_at = now
    previous.revocation_reason = "A newer calculation run has started."
    previous.save(update_fields=["publication_status", "revoked_at", "revocation_reason"])
...
run = PlanAuditRun.objects.create(
    plan_audit=audit, version=version, calculation_status="running",
    publication_status="pending", summary_import=audit.summary_import,
    source_sha256=audit.summary_import.file_hash, initiated_by=request.user,
    started_at=now, calculation_fingerprint=_calculation_fingerprint(),
)
audit.current_version = version
audit.published_version = None
audit.report_generated_at = None
audit.save(update_fields=["status", "summary", "current_version", "published_version",
                          "completed_at", "report_generated_at"])
```

The calculation stores a result fingerprint and per-reference SHA-256 fingerprints on completion, alongside source import and code/config fingerprints. Engine writes attach each result/opportunity to this run; earlier results remain in place.

**`backend/pricing/plan_audit_common.py` — version-bound client authorization.**

BEFORE: client access depended on mutable audit status/report date and latest audit-level approval.

AFTER (actual authorization condition):

```python
def get_visible_audit(user, audit_id):
    audit = get_accessible_audit(user, audit_id)
    if is_client_only(user) and not published_run(audit):
        raise Http404
    return audit
```

`published_run()` requires the current version, completed calculation, explicit approval, matching result fingerprint, and both immutable PDF/CSV artifacts whose bytes and combined report fingerprint verify. Every client detail/data/report endpoint uses this check; the list/detail metadata endpoints expose safe pending status while withholding summary and fingerprints.

**`backend/pricing/plan_audit_reports.py` — immutable artifacts and bound approval.**

BEFORE: report downloads regenerated from current mutable `audit.results`; reviews did not name a version.

AFTER (actual approval checks):

```python
if (not run or run.calculation_status != "completed"
        or request.data.get("version") != run.version
        or request.data.get("result_fingerprint") != run.result_fingerprint
        or run_result_fingerprint(run) != run.result_fingerprint
        or run.source_sha256 != audit.summary_import.file_hash
        or run.calculation_fingerprint != _calculation_fingerprint()):
    return Response({"error": "The audit version or its source/results changed; review the current version."}, status=409)
```

PDF and CSV bytes are created once per run, stored as `PlanAuditArtifact`, and their hashes are included in `report_fingerprint`. Downloads stream those stored bytes. Approval requires independent reviewer, matching version/results/source/calculation, both verified artifacts, and no blocking data-quality rows; it sets `published_version` only for that exact run. Rejection or rerun closes client access. Unvalidated savings are excluded from client payloads and published PDF metrics.

**Model/migration:** `PlanAuditRun`, `PlanAuditArtifact`, run links on result/opportunity/review, current/published version fields, per-run uniqueness constraints, and legacy linking are in `backend/pricing/models.py` and `backend/pricing/migrations/0011_plan_audit_run_versions.py`. Existing rows are retained as version 1 `legacy_unverified`; historical approvals are not treated as publication evidence, and no old hash is invented.

**`frontend/src/pages/PlanAudits.jsx`:** the page shows Running, Pending Approval, and Published from server status; it clears in-memory metrics and refreshes before rerun, warns before suspending a published run, avoids requesting data endpoints for a client-pending run, disables client downloads unless allowed, and submits version/result fingerprint with reviewer actions.

### Regression and verification

- Added to `tests/test_api.py::test_end_to_end_plan_audit_workflow`: v1 publication, rerun, client denial across overview/results/report/CSV/savings/quality, stale v1 approval rejection, v2 reapproval, and restored client reads/downloads. The fixture explicitly marks rows as validated to exercise the allowed publication branch; the normal engine's unresolved clinical-unit rows remain blocking.
- `.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp\\mk02-final` — **107 passed**.
- `.venv\\Scripts\\python.exe backend\\manage.py check` — **no issues**.
- `.venv\\Scripts\\python.exe backend\\manage.py makemigrations --check --dry-run` — **no changes detected**.
- `npm run build` from `frontend` — **Vite production build passed**.
- `.venv\\Scripts\\python.exe backend\\manage.py migrate pricing` — applied `0011_plan_audit_run_versions` successfully to the configured local development database.
- No commit, push, or deployment was performed. MK-01 MFA, OTP, and DuckDB changes remain intact.

### File-by-file review

BEFORE excerpts for the original mutable rerun, authorization gate, report/review behavior, listing filter, and unversioned data model are preserved above under **MK-02 Baseline — BEFORE Implementation**. AFTER code is in the implementation excerpts in this section; the complete file changes are inspectable with `git diff -- backend/pricing/models.py backend/pricing/plan_audit_common.py backend/pricing/plan_audit_engine.py backend/pricing/plan_audit_imports.py backend/pricing/plan_audit_run.py backend/pricing/plan_audit_reports.py frontend/src/pages/PlanAudits.jsx tests/test_api.py docs/PROJECT_HANDOFF.md` and the new migration `backend/pricing/migrations/0011_plan_audit_run_versions.py`.

## MK-02 Baseline — BEFORE Implementation

- **Repository state inspected:** branch `development`, HEAD `a903892690c3edf5a6ef136e33a8dc11525a1a80`. Existing uncommitted MFA, OTP, and DuckDB changes were present and are preserved.
- **Root cause:** Plan audit results, review decisions, and report timestamps are attached to the mutable `PlanAudit`; reruns delete/replace result rows without clearing publication evidence. Client authorization checks audit status, a report timestamp, and the latest audit-level review, so old approval can authorize newer rows. PDF and CSV endpoints regenerate from current rows.
- **BEFORE — `backend/pricing/plan_audit_run.py`, `run_audit()`:**

```python
with transaction.atomic():
    audit = PlanAudit.objects.select_for_update().select_related(
        "organization", "plan", "summary_import"
    ).get(pk=audit.pk)
    if audit.summary_import.import_status != "accepted":
        return Response({"error": "The selected summary import is not accepted."}, status=409)
    audit.status = "running"
    audit.summary = {}
    audit.save(update_fields=["status", "summary"])
    audit.results.all().delete()
    audit.savings_opportunities.all().delete()
    summary = run_plan_audit(audit)
    audit.summary = summary
    has_warnings = any(status != "VALID" for status in summary["quality_status_counts"])
    audit.status = "needs_review" if has_warnings else "completed"
    audit.completed_at = timezone.now()
    audit.save(update_fields=["summary", "status", "completed_at"])
```

- **BEFORE — `backend/pricing/plan_audit_common.py`, `get_visible_audit()`:** clients were filtered by `status="completed"`, non-null `report_generated_at`, and a latest `AuditReview.review_status == "approved"`; neither review nor timestamp identified a result version.
- **BEFORE — `backend/pricing/plan_audit_reports.py`, `_set_review()`:** `AuditReview.objects.create(plan_audit=audit, reviewer=request.user, review_status=status, comments=comments)` stored no run or result fingerprint. `plan_report()` and `export_plan_csv()` queried `audit.results.all()` when a download was requested.
- **BEFORE — `backend/pricing/plan_audit_imports.py`, `plan_audits()`:** repeated the same historical audit status/timestamp/latest-review filter for client listing.
- **BEFORE — data model:** `PlanAuditResult`, `SavingsOpportunity`, and `AuditReview` had no execution-version foreign key; PDF/CSV files were not stored as immutable artifacts.
- **Planned correction:** add numbered runs and version-linked rows/reviews/artifacts; commit publication revocation and the next running version before computation; publish only after independent approval tied to current result and artifact hashes. Preserve legacy reviews/results as unverified history because no prior immutable snapshot exists. No legacy approval or hash will be fabricated.

## OTP Expiry, Authentication 401, and DuckDB 500 Follow-up

- **OTP before:** `verify_code()` checked the previous, current, and next 30-second TOTP steps (`delta=-1,0,1`). This accepted an expired code and a code not yet displayed. **OTP now:** verification defaults to the current 30-second step only; SHA-1, six digits, and the 30-second period match the provisioning URI. `TOTP_PAST_WINDOW_STEPS` and `TOTP_FUTURE_WINDOW_STEPS` are explicit backend configuration overrides and default to `0`; setting either above zero intentionally broadens acceptance. `last_used_step` still rejects replay, and one-time recovery codes and enrollment confirmation remain active.
- **OTP timing:** `time.time()` is Unix UTC time; Django uses `TIME_ZONE=UTC` and `USE_TZ=True`. Browser timers do not authorize codes. The Windows Time service is running, but querying synchronization status with `w32tm /query /status` was denied in this environment, so clock synchronization could not be confirmed. Strict mode deliberately does not compensate for clock skew or network delay; a code arriving just after its boundary is rejected and the user must enter the newly displayed code.
- **Authentication:** Canonical sign-in, TOTP verification, and access-token refresh routes pass together with CSRF enforcement. Invalid credentials still correctly return 401; expired challenges now carry a stable error code, and the login page requests a fresh password challenge. Protected API requests retry once after session-backed refresh; if refresh fails, the frontend clears its bearer state and returns the app to sign-in. MFA, CSRF, JWT validation, and one-time recovery remain enforced.
- **DuckDB:** The materialized Parquet scan workaround is present in the imported workspace module `backend/pricing/data.py`. The requested endpoint query passes regression coverage. No local Django listener was found on ports 8000/8001, and no Vite listener on 5173/5174, so a stale running server could not be tested or restarted. Process command-line inspection was denied; the actual server process/version therefore remains unverified.
- **Runtime inspected:** `.venv\\Scripts\\python.exe`; Django 5.2.18; DuckDB 1.4.1; imported `pricing.otp`, `pricing.auth_views`, and `pricing.data` resolve to this workspace's `backend/pricing`. Runtime settings show `DEBUG=True`, UTC, and strict TOTP windows `0/0`. Vite uses `/api/v1` and defaults its proxy to `http://127.0.0.1:8000`.
- **Verification:** Focused OTP/API tests: **11 passed**. Full suite: **107 passed**. Django system check and migration check passed. React/Vite production build passed. No datasets were changed.

## Authentication 401 and Comparison 500 Verification

- **Authentication status:** The current changes complete the MFA boundary fix. Password sign-in returns an enrollment or TOTP challenge; successful TOTP/recovery verification rotates and binds a Django session, and `refresh_access` issues a token only from current MFA evidence. Password-only sessions and legacy tokens are rejected. The frontend retains the signed challenge, sends CSRF on state-changing requests, and refreshes from the HttpOnly session. Existing regression tests cover valid TOTP/recovery, one-time recovery codes, expired MFA evidence, session-bound token rejection, and refresh. No authentication code change was needed in this verification pass.
- **DuckDB root cause:** The actual `data/mart/comparison.parquet` has 10,266 rows, one ZSTD row group, and is readable with DuckDB 1.4.1 and PyArrow 22.0.0. PyArrow projected reads succeed. With this installed DuckDB, a direct all-column `SELECT * FROM read_parquet(?) ORDER BY markup_multiple DESC NULLS LAST LIMIT 50 OFFSET 0` reproduces `_duckdb.NotImplementedException: PlainSkip not implemented`; projection sorting and scans without pagination succeed. The existing `backend/pricing/data.py` materializes the comparison scan before filtering/sorting/pagination, which avoids the failing Parquet `PlainSkip` path without rewriting source data or changing financial values.
- **Regression coverage:** `tests/test_api.py::test_rates_filter_and_sort` now also calls the reported versioned endpoint with `sort=markup_multiple&order=desc&limit=50&offset=0` and checks HTTP 200, up to 50 rows, and descending non-null values. `test_production_comparison_parquet_supports_rate_projection` checks representative values against the production snapshot.
- **Verification:** Focused MFA/comparison tests: **7 passed**. Full pytest suite: **104 passed**. Django system check: **no issues**. `migrate --check`: **passed**. `npm --prefix frontend run build`: **passed**. Pytest used `.codex-tmp\\pytest` because the host temp directory is inaccessible.
- **Data integrity:** No Parquet files were rewritten. Existing tests verify the representative top-page markup values remain `0.33013196677384780278670953910` and `0.11088290460878885316184351550`.

## MK-01 — Django Admin MFA Boundary

- **Task ID:** MK-01.
- **Initial state:** clean working tree at `a903892690c3edf5a6ef136e33a8dc11525a1a80` (`phase-0-1-5 Complete`).
- **Verified root cause:** `auditapi.urls` mounted the stock `admin.site.urls`; DRF accepted ordinary Django `SessionAuthentication`; `auth_views.refresh_access` explicitly used it; JWTs had no MFA/session provenance.
- **BEFORE references:** `backend/auditapi/urls.py`, `backend/auditapi/settings.py`, `backend/pricing/admin.py`, `backend/pricing/auth_views.py`, `backend/pricing/jwt_auth.py`, `backend/pricing/otp.py`, `backend/pricing/permissions.py`, `backend/pricing/models.py`, `tests/test_otp.py`, and `tests/test_api.py` were inspected before changes. No credentials, OTP secrets, recovery codes, cookies, or tokens are recorded here.
- **Vulnerability reproduction:** before the fix, stock `/admin/login/` could establish a password-only Django session; DRF's standard `SessionAuthentication` and the explicit `refresh_access` override trusted that session. The regression test now proves a password-only/legacy session receives `401` from `/api/v1/user-accounts/` and `/api/v1/auth/refresh/`, while `/admin/login/` returns `403` without processing credentials.
- **Files modified:** `backend/auditapi/settings.py`; `backend/pricing/auth_views.py`; `backend/pricing/jwt_auth.py`; `tests/test_api.py`; `tests/test_otp.py`; this handoff. **Files added:** `backend/pricing/mfa.py`; `backend/pricing/admin_config.py`; `backend/pricing/mfa_admin.py`.
- **AFTER references and design:** `MFAAdminSite` replaces the default Django Admin site and requires `is_active`, `is_staff`, Django authentication, and live MFA evidence. `mfa.py` records evidence only after successful TOTP/recovery verification, after `login()` rotates the session. Evidence is bound to the user id, session key HMAC, Django session auth hash, verification time, and current enabled-device `updated_at`; it expires with the 8-hour session policy. `MFASessionAuthentication` enforces this for DRF. JWTs now require signed `sid` and `mfa_at` claims and validate the referenced, live MFA session; therefore pre-change tokens are rejected and logout/session expiry/device change revokes current tokens.
- **Tests run:** `.venv\Scripts\python.exe -m pytest tests\test_otp.py -q -p no:cacheprovider` — **4 passed**. `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` — **103 passed in 19.26s**. The test temp directory was placed under the workspace because the host temp directory was inaccessible; cache provider was disabled because `.pytest_cache` is not writable in this environment.
- **Other verification:** `.venv\Scripts\python.exe backend\manage.py check` — no issues; `.venv\Scripts\python.exe backend\manage.py migrate --check` — passed; `npm --prefix frontend run build` — passed (Vite built successfully).
- **Remaining MK-01 work:** none. Exact review command: `git diff -- backend/auditapi/settings.py backend/pricing/auth_views.py backend/pricing/jwt_auth.py backend/pricing/mfa.py backend/pricing/admin_config.py backend/pricing/mfa_admin.py tests/test_otp.py tests/test_api.py docs/PROJECT_HANDOFF.md`.

**Active Project Handoff Document**  
**Date:** 2026-11-03  
**Working Directory:** `C:\infu-audit\Meshkor_Audit_P`  
**Git Branch:** `main` (up to date with `origin/main`)

---

## 1. Executive Summary & Phases 0, 1, 5 Status

MeshKor is an enterprise healthcare data platform providing infusion-drug price transparency, hospital machine-readable file (MRF) rate benchmarking, and employer/TPA plan audits.

### Phase Status Overview

| Phase | Status | Technical Verification | External Business Requirements |
|---|---|---|---|
| **Phase 0: Project Architecture & Hygiene** | **COMPLETE** | Restructured backend entry points, zero hardcoded developer paths, centralized path resolution, reproducible environment (`backend/requirements.txt`), git hygiene verified | None |
| **Phase 1: CMS Reference Tables & Pipeline** | **COMPLETE** | 7 reference tables verified, 12 quarters ASP coverage (2024Q1–2026Q4), 5 CMS spot-checks passed, 100% normalized 11-digit NDCs, 20/20 in-scope drug coverage, 5 new reference tests passing | None |
| **Phase 2: Claims Explorer & Organizations** | **COMPLETE** | Tenant-scoped synthetic DE-SynPUF and Synthea (178,804 rows across 18 tables) analytics, subtable explorer, DuckDB queries | None |
| **Phase 3: Market Analysis Report** | **COMPLETE** | 100% byte-for-byte report reproducibility verified across markdown, CSVs, and dashboard JSON | 3 genuine broker/TPA evaluations required |
| **Phase 4: Plan Audits & Historical Analytics** | **COMPLETE** | Standalone zero-network client extractor, k-anonymity suppression ($\ge 11$), roster ingestion, audit run engine, in-network savings calculation | Customer data authorization |
| **Phase 5: Production Acceptance & Release Gate** | **PENDING ACCEPTANCE** | Financial math verified (Decimal arithmetic, statutory ASP), 101 tests pass, security regressions pass | **NOT READY FOR COMMERCIAL RELEASE** (0/3 broker evaluations, 0/20 clinical unit approvals) |

---

## 2. Phase 0: Project Structure & Backend Organization

### 2.1 Directory Layout & Standardization
The codebase adheres to the standardized project structure:
- `backend/`: Django project (`backend/auditapi/`), pricing domain app (`backend/pricing/`), entry CLI (`backend/manage.py`), backend dependencies (`backend/requirements.txt`), and backend scripts (`backend/scripts/build_market_report.py`).
- `client_extractor/`: Standalone, distributable zero-network CLI designed to run in the customer's on-premise firewall environment.
- `pipeline/`: Core data transformation package (`common.py`, `build_compare.py`, `synthea_to_parquet.py`, etc.) accessible by Django and CLI tools.
- `data/`: Curated Parquet files (`data/ref/`, `data/mart/`, `data/claims/`, `data/synthetic/`).
- `config/`: Shared pipeline and domain configurations (`drugs_in_scope.yaml`, `pipeline.yaml`, `hospital_sites.csv`, `report.json`).
- `frontend/`: React + Vite single-page application.
- `tests/`: Unified pytest suite (`tests/test_api.py`, `tests/test_pipeline.py`, `tests/test_reference_data.py`, `tests/test_client_extractor.py`).

### 2.2 Path Centralization & Portability
- All runtime data paths resolve dynamically via `pipeline.common.paths()`, which anchors to `Path(__file__).resolve().parent.parent` and supports `IA_DATA_ROOT` environment override.
- Django `settings.py` resolves `BASE_DIR = Path(__file__).resolve().parent.parent` (the `backend/` folder) and `PROJECT_DIR = BASE_DIR.parent`.
- Full-codebase scan confirmed **zero hardcoded developer machine paths** in runtime code. All path operations use relative or dynamically constructed `Path` objects.

### 2.3 Dependency & Environment Verification
- Python Version: Python 3.13.12 (Windows 64-bit).
- Dependencies locked in `backend/requirements.txt` and verified against active virtual environment:
  - `Django==5.2.18`
  - `djangorestframework==3.16.1`
  - `polars==1.34.0`
  - `duckdb==1.4.1`
  - `pyarrow==22.0.0`
  - `cryptography==50.0.2`
  - `reportlab==4.4.4`
- Git hygiene verified: `.env`, SQLite operational databases (`db.sqlite3`), Parquet files, virtual environments, node modules, and raw customer files are strictly excluded by `.gitignore`.

---

## 3. Phase 1: Reference Data Inventory & Validation

All CMS and reference datasets were directly audited via DuckDB and Polars:

### 3.1 Dataset Inventory & Statistics

| Dataset | File Path | Records | Distinct Entities | Periods / Range | Quality Status |
|---|---|---|---|---|---|
| **Medicare ASP** | `data/ref/ref_asp.parquet` | 10,795 | 1,155 HCPCS | 12 Quarters: 2024Q1–2026Q4 | **VALID** (15 null limits out of 10,795; limits $0.002 to $2.73M) |
| **CCN-to-NPI Mapping** | `data/ref/ref_ccn_npi.parquet` | 25,444 | 9,163 CCNs, 19,342 NPIs | Nationwide (783 Ohio records, 316 CCNs, 633 NPIs) | **VALID** (0 null NPIs in Ohio; 131 acute-care CCNs, 362 NPIs) |
| **NPPES Provider** | `data/ref/ref__ref_provider__state_part=OH__*.parquet` | 258,553 | 258,553 NPIs | Ohio partition | **VALID** (0 invalid NPI lengths; 47,392 Type-2 orgs, 211,161 Type-1, 502 deactivated) |
| **NDC-HCPCS Crosswalk** | `data/ref/ref_ndc_hcpcs.parquet` | 95,545 | 1,335 HCPCS, 10,468 NDCs | 12 Quarters | **VALID** (9,069 distinct 11-digit NDCs; 0 invalid `ndc11` lengths) |
| **Drug Scope Reference** | `data/ref/drug_scope.parquet` | 20 | 20 HCPCS | Part B Spending 2024 (Rank 1–20) | **VALID** (All 20 have source SHA-256; reviews pending) |
| **FDA NDC Product** | `data/ref/ref_ndc_product.parquet` | 116,501 | FDA product directory | Reference | **VALID** |
| **NADAC Acquisition** | `data/ref/ref_nadac.parquet` | 1,001,844 | Retail pharmacy acquisition | Benchmark reference | **VALID** (Acquisition prices separated from hospital negotiated rates) |

### 3.2 ASP Statutory Rate Verification & 5 Spot Checks
The published CMS ASP payment limit includes statutory payment percentages. **No additional 6% is ever added.**  
Five spot-checks for 2026Q1 were verified against published CMS payment files:

1. **J0897** (Denosumab injection / Prolia, 1 MG): **$29.4570**
2. **J1745** (Infliximab not biosimil / Remicade, 10 MG): **$32.4230**
3. **J2350** (Injection, ocrelizumab / Ocrevus, 1 MG): **$59.3240**
4. **J9271** (Injection, pembrolizumab / Keytruda, 1 MG): **$59.7260**
5. **J9299** (Injection, nivolumab / Opdivo, 1 MG): **$33.5730**

### 3.3 Scope Coverage
- 20 of 20 in-scope drugs (100%) are present in `ref_asp.parquet`.
- 20 of 20 in-scope drugs (100%) are present in `ref_ndc_hcpcs.parquet`.
- Dedicated test suite `tests/test_reference_data.py` validates all 5 conditions programmatically.

---

## 4. Phase 5: Verification & Production Acceptance

### 4.1 Report Reproducibility (Task 6)
- Verified report generation reproducibility using `scripts/test_reproducibility.py`.
- Running `build_market_report.py` across successive runs with unchanged inputs yields **100% byte-for-byte identical output**:
  - `reports/ohio_market_report_draft.md`: **MATCH (Byte-for-byte)**
  - `reports/ohio_hospital_by_drug.csv`: **MATCH (Byte-for-byte)**
  - `reports/ohio_report_sources.csv`: **MATCH (Byte-for-byte)**
  - `reports/dashboard_data.json`: **MATCH (Byte-for-byte)**

### 4.2 Financial Calculation Validation (Task 7)
- **Calculation engine**: `pipeline.build_compare` and `backend.pricing.plan_audit_engine` use Python `Decimal` arithmetic.
- **Formula adherence**:
  $$\text{per\_unit} = \frac{\text{total\_allowed}}{\text{total\_units}}$$
  $$\text{markup\_multiple} = \frac{\text{verified\_price\_per\_unit}}{\text{matching\_quarter\_asp\_payment\_limit}}$$
  $$\text{potential\_savings} = \max(0, \text{current\_allowed\_per\_unit} - \text{alternative\_allowed\_per\_unit}) \times \text{eligible\_units}$$
- **Discrepancy fix**: Resolved a defect in `pipeline/build_compare.py` where `asp["quarter"]` and `dosage_text` were expected instead of `period` and `dosage`. Both aliases are now handled automatically.
- **Run verification**: `python -m pipeline.build_compare` writes 10,266 comparison rows deterministically:
  - `unit_unresolved`: 9,153
  - `percent_of_charges`: 540
  - `algorithm_only`: 514
  - `review_range`: 59

### 4.3 Independent Clinical Unit Review (Task 8)
- Model: `DrugUnitReview` (`backend/pricing/models.py`).
- Clinical review boundary: MeshKor does not impersonate a clinical reviewer or auto-approve drug units.
- **Current Status**: All 20 in-scope drugs remain with `review_status = None` (pending).
- Review package: The frontend `DrugScope.jsx` provides HCPCS, drug description, CMS billing units, dosage text, source SHA-256 hashes, and review notes.
- Independent verification requirement: Dual-party sign-off is required before any report release. A user who submits an audit cannot be the sole approver.

### 4.4 Security Regression Testing (Task 9)
All negative and boundary security test cases pass:
- Unauthenticated requests to analytics endpoints return `401 Unauthorized`.
- Non-admin/viewer role escalation requests return `403 Forbidden`.
- Organization isolation: Users can only query datasets and plan audits belonging to their authorized tenant organizations (`visible_organizations()`).
- Path traversal: Zip upload rejects path traversal members (`../../`).
- Session security: Google Authenticator TOTP enforced; encrypted TOTP seeds in SQLite; CSRF tokens enforced on state-modifying requests.
- Formula injection: Untrusted CSV export cells prefixed with formula characters (`=`, `+`, `-`, `@`) are neutralized with prepended single quotes.

### 4.5 Legal, Compliance & Insurance Readiness (Task 10)
- **Disclaimers in Reports**:
  - ASP benchmarks represent statutory limits and do not reflect supplemental rebates.
  - Hospital prices originate from public machine-readable files (MRFs) subject to hospital reporting accuracy.
  - Billing unit conversions are subject to clinical validation.
  - Potential savings opportunities are informational estimates and require clinical appropriateness and network verification.
- **Readiness Checklist**:
  - [ ] Commercial Errors & Omissions (E&O) insurance policy active.
  - [ ] Cyber liability & privacy insurance policy active.
  - [ ] Business Associate Agreement (BAA) assessment completed.
  - [ ] Customer Data Processing Agreement (DPA) finalized.
  - [ ] Formal legal review of market report marketing claims.

### 4.6 Customer Validation & Pricing Strategy (Task 11)
- **Broker/TPA Milestone**: 3 genuine evaluations required before commercial release. Current status: **0 of 3**.
- **Pricing Strategy Models Evaluated**:
  1. *Per-Report Pricing* ($5,000–$15,000 per completed audit): Low commitment for employers; simple transaction model; lacks recurring predictable revenue.
  2. *Annual Per-Employer Retainer* ($25,000–$50,000/yr for quarterly audits): Aligns with ongoing plan year monitoring; higher annual contract value; requires continuous claims onboarding.
  3. *PEPM (Per-Employee-Per-Month)* ($0.25–$0.75 PEPM): Familiar model for TPAs and self-funded employers; scalable with employer headcount; requires steady enrollment roster integration.
  4. *Paid Pilot Pricing* ($7,500 single-plan initial audit credited toward annual retainer): Minimizes client friction; directly tests the 15-step onboarding workflow; ideal for the first authorized commercial client.

---

## 5. Release Acceptance Gate (Task 12)

```text
======================================================================
                     RELEASE ACCEPTANCE GATE
======================================================================
  Technical Implementation:      VERIFIED (101/101 tests pass)
  Security Regressions:          VERIFIED
  Report Reproducibility:        VERIFIED (Byte-for-byte identical)
  Financial Precision:           VERIFIED (Decimal arithmetic)
  Clinical Review Approvals:     PENDING (0 / 20 approved)
  Broker/TPA Evaluations:        PENDING (0 / 3 evaluations)
  Legal/Insurance Policies:      PENDING BUSINESS AUTHORIZATION

  FINAL RELEASE STATUS: NOT READY FOR COMMERCIAL RELEASE
======================================================================
```

Release is gated until:
1. Three genuine broker/TPA evaluations are recorded in `BrokerEvaluation`.
2. Qualified human clinical reviewers complete the 20 pending `DrugUnitReview` records.
3. Corporate legal and insurance coverage checklists are finalized.

---

## 6. Verification Commands & Execution Results

```powershell
cd C:\infu-audit\Meshkor_Audit_P

# 1. Django System & Migration Check
.venv\Scripts\python.exe backend/manage.py check
# Result: System check identified no issues (0 silenced).

.venv\Scripts\python.exe backend/manage.py migrate --check
# Result: No pending unapplied migrations.

# 2. Pytest Test Suite
.venv\Scripts\python.exe -m pytest -q
# Result: 101 passed in 22.86s.

# 3. Reference Data Verification
.venv\Scripts\python.exe scripts/verify_phase1_complete.py
# Result: All 5 reference datasets verified; 20/20 drugs covered; 0 invalid NPIs/NDCs.

# 4. Report Reproducibility
.venv\Scripts\python.exe scripts/test_reproducibility.py
# Result: 100% byte-for-byte match across markdown, CSVs, and dashboard JSON.

# 5. Frontend Production Build
npm --prefix frontend run build
# Result: Built in 4.7s, 0 errors.
```

---

## 7. Modified & Created Files Summary

### Files Created:
- `backend/requirements.txt`: Locked backend dependencies.
- `backend/scripts/build_market_report.py`: Backend CLI entry point for report generation.
- `tests/test_reference_data.py`: 5 automated tests for Phase 1 CMS reference datasets.
- `scripts/verify_phase1_complete.py`: Comprehensive reference data audit utility.
- `scripts/test_reproducibility.py`: Report byte-level reproducibility test script.

### Files Modified:
- `pipeline/build_compare.py`: Fixed `quarter`/`period` and `dosage_text`/`dosage` column alias handling for `ref_asp.parquet`.
- `docs/PROJECT_HANDOFF.md`: Updated with complete Phase 0, 1, and 5 handoff documentation.

---

## PHASE 1 — ROLE ARCHITECTURE IMPLEMENTATION

**Implementation date:** 2026-11-07
**Status:** **BLOCKED** — role work is implemented, but the full non-browser regression is not clean because five reference-data tests disagree with the datasets present in this checkout.

### Final permission matrix

| Capability | SUPER_ADMIN / legacy Admin | ANALYST | REVIEWER | CLIENT / legacy Viewer |
|---|---:|---:|---:|---:|
| Assigned organization and plan access | All | Assigned | Assigned | Assigned |
| Administration, users, audit logs, platform settings | Yes | No | No | No |
| Source imports and pipeline work | Yes | Authorized work | No | No |
| Claims Explorer synthetic datasets | Yes | Assigned and registered datasets | No | No |
| Create and run plan audits | Yes | Yes | No | No |
| Review queue and clinical unit validation | Yes | No | Yes | No |
| Approve or reject eligible audit versions | Yes, subject to independence checks | No | Yes, subject to independence checks | No |
| Market reports and comparisons | Per existing release authorization | Yes | Yes | Released content only |
| Plan financial results and downloads | Yes | Assigned audit work | Assigned review work | Current published versions and approved artifacts only |
| Account security and methodology | Yes | Yes | Yes | Yes |

Multiple roles combine their explicitly granted capabilities. Legacy `Admin` maps to the Super Admin policy and legacy `Viewer` maps to Client. Unknown or missing frontend roles fail closed. Django superusers retain Django's existing full-access behavior.

### Existing functionality reused

- Kept one React application and one Django API.
- Reused `Overview.jsx` API-backed dashboard components and existing organizations, plans, pipeline, quality, report, and plan-audit APIs.
- Reused the existing plan audit reviewer queue, clinical unit review workflow, MFA/account security page, and publication/download endpoints.
- Added a separate client presentation of the existing published audit APIs so it does not load internal import metadata or the analyst/reviewer audit setup page.
- Kept existing tenant scoping, report-current-version checks, publication fingerprint checks, client financial redaction, audit independence rules, MFA, JWT, and CSRF handling intact.

### Files changed

- `frontend/src/rolePolicy.js` and `frontend/src/rolePolicy.test.js`: shared role aliases, workspace policy, and fail-closed helpers with focused role tests.
- `frontend/src/main.jsx`: centralized role-gated routes and navigation, explicit Access Denied content, role-aware labels, client plan-audit view selection, and account-security access for all authenticated roles.
- `frontend/src/pages/Overview.jsx`: Admin, Analyst, Reviewer, and Client dashboards with values sourced from authorized APIs; client dashboard includes published totals and approved PDF/CSV download links.
- `frontend/src/pages/ClientPlanAudits.jsx`: published-only client audit summaries and authorized downloads without exposing internal imports or review comments.
- `frontend/package.json`: `npm test` command for the role policy tests.
- `backend/pricing/permissions.py`: replaced broad client URL substring checks with a narrow client GET route allowlist; blocks source-import and organization-access endpoints.
- `backend/pricing/claims_views.py`: claims endpoints require Admin/Analyst analysis capability, excluding Reviewers and Clients.
- `backend/pricing/plan_audit_reports.py`: returns not found for Client attempts to read internal review comments.
- `tests/test_api.py`: verifies the client route boundary and Reviewer denial for Claims Explorer.
- `docs/PROJECT_HANDOFF.md`: this implementation record.

### Verification

- Frontend role policy: **4 passed** (`npm --prefix frontend test`).
- Focused backend role permission matrix: **1 passed**.
- Claims organization/privacy and Reviewer denial: **1 passed** (pytest emitted a test-database teardown file-lock warning after the pass).
- Plan-audit client publication lifecycle end-to-end: **1 passed**.
- Django system check: **passed**, no issues.
- Migration check: **passed**, no pending migrations.
- React production build: **passed**.
- Full non-browser pytest regression: **135 passed, 5 failed**. Failures are in `tests/test_reference_data.py`: the present ASP Parquet has `description`, `dosage`, and no `quarter` column where tests require `short_description`, `dosage_text`, and `quarter`; `ref_crosswalk.parquet` and `ref_enrollments.parquet` are absent. Dataset files were not changed.
- Browser E2E: **NOT TESTED**.
- `git diff --check`: **passed** (Git also reported access warnings for pre-existing inaccessible `tmp_pytest` paths).

### Remaining blockers

1. Reconcile the reference-data test schema and expected file names with the checked-in local reference dataset before claiming a clean full regression. This implementation did not modify Parquet or source data.
2. Browser role-navigation and direct-route behavior still needs execution in the browser test environment; the API and frontend policy checks do not substitute for that run.

**Result:** Role access **PASS**; dashboard implementation **PASS**; backend RBAC **PASS** for exercised role and tenant boundaries; full regression **135 passed / 5 failed**; frontend build **PASS**; Phase 1 overall **BLOCKED** pending the existing reference-data test mismatch.

---

## PHASE 1 — REGRESSION REPAIR AND FINAL VERIFICATION

**Date:** 2026-11-07
**Result:** **PHASE 1 VERIFIED** for the role architecture and non-browser acceptance. No reference Parquet files or customer data were modified.

### Original failures and verified causes

| Original failing test | Cause found | Correction |
|---|---|---|
| `test_ref_asp_quarters_and_structure` | The persisted `ref_asp.parquet` is an older supported snapshot with `description`, `dosage`, and `period`. The current loader writes `short_description`, `dosage_text`, and `quarter`; `backend/pricing/data.py` already aliases the older ASP columns for application reads. All 12 expected periods are present. | The test now accepts the documented legacy column aliases while still requiring the description, dosage, payment limit, period, and lineage fields. |
| `test_ref_asp_spot_checks_no_additional_6_percent` | The test hard-coded `quarter`; the legacy snapshot stores the same period in `period`. All five requested 2026Q1 values match the saved CMS payment limits. | Query the canonical or supported legacy period field. The test still compares all five exact values. |
| `test_drug_scope_coverage_in_asp_and_crosswalk` | The test required `ref_crosswalk.parquet`; this workspace has the supported legacy `ref_ndc_hcpcs.parquet`, which `data.files()` already resolves. | Resolve canonical first, then the registered legacy filename; retain the 20-code ASP and crosswalk coverage assertions. |
| `test_ndc_11digit_normalization` | Same stale crosswalk filename assumption. The legacy crosswalk contains 95,545 rows, 1,335 HCPCS codes, 9,069 distinct NDC11 values, and no NDC with a length other than 11. | Read the canonical or registered legacy crosswalk; retain the full-table 11-digit validation. |
| `test_ccn_npi_ohio_coverage` | The workspace has the older `ref_ccn_npi.parquet` mapping rather than `ref_enrollments.parquet`. The app resolver did not yet recognize this legacy enrollment artifact, so the API catalog also reported it missing. | Registered `ref_ccn_npi.parquet` as the legacy enrollment artifact in `pipeline/artifacts.py` and enabled that alias in `backend/pricing/data.py`. The test now uses the application resolver and filters to Ohio acute-care rows. |

### Data evidence and limits

- ASP snapshot: 10,795 rows; 12 quarters from 2024Q1 through 2026Q4; `source_file` and `source_sha256` are populated. Five checked 2026Q1 values are J0897 **29.4570**, J1745 **32.4230**, J2350 **59.3240**, J9271 **59.7260**, and J9299 **33.5730**.
- The saved legacy ASP snapshot contains 15 null payment limits: A9606 in 12 quarters, plus J0739, J0750, and J0751 in 2024Q4. None is in the current 20-drug scope; the 20 scoped codes have no null payment limits. The current loader separates unpriced rows from its canonical ASP output. These stored rows were not changed.
- J0177 has 11 ASP periods and no 2024Q1 row; it first appears in this snapshot at 2024Q2. The comparison code must keep that quarter explicitly unavailable rather than infer a price.
- Legacy CCN/NPI snapshot: 25,444 rows nationwide. The Ohio acute-care subset has 367 rows, 116 CCNs, 347 NPIs, and no null NPIs. The stored lineage has source names and hashes.
- The original raw downloads are not present under `data/raw_essential_inputs` in this checkout. Stored source hashes are populated in the Parquet lineage fields, but could not be recomputed against the original downloads. No sources were downloaded or replaced.
- These findings are retained as data lineage and quarter-availability limits; this repair did not suppress, replace, or fabricate reference records.

### Changes made

- Updated `tests/test_reference_data.py` to assert the same schema, coverage, five published ASP values, NDC normalization, and acute-care Ohio enrollment conditions across canonical and supported legacy snapshots. The test uses the project data resolver for the enrollment artifact.
- Updated `pipeline/artifacts.py` and `backend/pricing/data.py` to resolve `ref_ccn_npi.parquet` as a read-only legacy alias for `ref_enrollments.parquet`.
- Preserved all Phase 1 role policy, dashboards, route guards, claims restrictions, publication checks, independence rules, MFA, and tenant controls from the preceding implementation.

### Final verification

- Original reference-data tests after correction: **5 passed**; focused reference-catalog/API plus reference tests: **6 passed**.
- Full non-browser suite: `.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_browser_e2e.py -q -p no:cacheprovider --basetemp=.venv\phase1-final-full2-20261107` — **140 passed**.
- Frontend role tests: `npm --prefix frontend test` — **4 passed**.
- Django system check: **PASS**, no issues.
- `makemigrations --check --dry-run`: **PASS**, no changes detected.
- `migrate --check`: **PASS**, no pending migrations.
- React production build: **PASS** (Vite transformed 856 modules).
- `git diff --check`: **exit 0**. Git printed permission warnings while traversing pre-existing inaccessible `tmp_pytest` paths; no whitespace errors were reported.
- Browser E2E: **NOT TESTED**, as assigned to the separate RG-01 acceptance work.
- MK-01 through MK-10 regressions: **PASS** in the 140-test non-browser suite.
- No commit, push, or deployment was made.

**Acceptance:** Role access **PASS**; dashboards **PASS**; backend RBAC **PASS**; full non-browser regression **140 passed**; frontend role tests **4 passed**; Django/migration checks **PASS**; frontend build **PASS**. **PHASE 1: VERIFIED.**

---

## PHASE 2 — BUSINESS WORKFLOW AND BACKEND INTEGRATION

**Date:** 2026-11-07
**Result:** **PHASE 2 BLOCKED BY APPROVAL**. Existing workflows and the real calculation path are verified, but the checked-out audit cannot pass the clinical unit-review gate using genuine review evidence. The publication-state mechanics are covered by isolated tests; a test fixture that injects a validated marker and a savings row is not clinical/business signoff and is not counted as a valid publication acceptance.

### Completeness inventory

| Workflow | Classification | Existing frontend/API and evidence |
|---|---|---|
| Super Admin accounts, roles, deactivation/password reset, MFA | **WORKING** | `UserManagement.jsx` uses `/user-accounts/` and `/user-accounts/<id>/management/`; authentication/TOTP routes enforce onboarding and session evidence. Added `test_admin_account_role_and_organization_access_workflow` for account creation, role update, deactivation, and reactivation through the real API. |
| Organizations, plans, Analyst/Reviewer/Client access grant and revoke | **WORKING** | Plan Audits setup uses `/organizations/`, `/plans/`, and `/organizations/<id>/users/`; API tests check scoped visibility and immediate denial after revocation. |
| Reference data, source upload, pipeline jobs, audit logs | **WORKING** | Admin pages call reference catalog/detail, data-source upload/job, and audit-log APIs. Existing route/API tests cover catalog paging, file handling, job processing, source authorization, and logs. |
| Analyst assigned workspace, claims explorer, price comparison, aggregate import, roster validation, audit calculation and analysis | **WORKING** | Analyst routes use organization-scoped APIs. `test_end_to_end_plan_audit_workflow` runs the actual offline extractor on isolated synthetic claims, imports only suppressed aggregates with manifest/hash checks, validates the network roster, and invokes the calculation engine. No raw claims are stored by the import endpoint. |
| Reviewer queue, unit evidence, quality/provenance review, approval/rejection | **PARTIAL / BLOCKED BY APPROVAL** | Review and unit-validation endpoints enforce role, provenance, current-version binding, and independent-review restrictions. The real run remains unpublishable while unit evidence is unresolved. No external clinical reviewer evidence exists in this checkout; none was fabricated. |
| Client assigned context, published-only dashboard, PDF/CSV, empty state and direct API isolation | **WORKING** | Client UI loads only published audits and authorized artifacts. API tests verify unpublished/rejected result and download denial, cross-organization isolation, and immediate loss of access on rejection or access revocation. |
| Genuine approved report from this workspace’s current evidence | **BLOCKED_BY_APPROVAL** | The actual calculation produces unresolved unit review and no eligible savings. Approval returns 409 as designed. Existing publication-state test coverage uses a test-only injected marker/row to exercise state transitions; it is not counted as evidence that real financial results are publishable. |
| Browser-level role/navigation run | **NOT TESTED** | Per Phase 2 instructions, browser E2E remains Phase 3; build and frontend role-policy tests are not represented as browser acceptance. |

### Implementation and tests

- Reused the Phase 1 role-aware workspaces, Django route authorization, organization scoping, client financial redaction, versioned calculation/report artifacts, MFA/CSRF/JWT controls, and offline extractor. No duplicate workflow or broad runtime refactor was needed.
- Added `tests/test_api.py::test_admin_account_role_and_organization_access_workflow`. It exercises account creation and management through the same endpoints used by the UI, creates a synthetic organization and plan, grants assigned access, verifies role-scoped organization/plan listing, and checks that revocation removes access immediately. It also verifies that a disabled account cannot receive tenant access.
- The real-calculation path is covered in `test_end_to_end_plan_audit_workflow`: the extractor and engine run on test-only synthetic claims, actual calculated per-unit values are asserted, and approval of unresolved units is denied. Later fixture-injected approval scenarios in that test verify version/provenance/rejection state-machine behavior only; their injected savings do not establish financial acceptance.
- No operational or customer data, reference Parquet files, migration, or dependency was changed. No clinical signoff was invented.

### Verification

- Focused Admin, Analyst, Reviewer, and Client workflow tests: **6 passed** across the account-management workflow plus the existing role matrix, organization/plan workflow, real-extractor plan-audit lifecycle, and clinical-review authorization tests.
- Full non-browser backend suite: `.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_browser_e2e.py -q -p no:cacheprovider --basetemp=.venv\phase2-final-full-20261107` — **141 passed**.
- Frontend role-policy tests: `npm --prefix frontend test` — **4 passed**.
- Django system check: **PASS**.
- `makemigrations --check --dry-run` and `migrate --check`: **PASS**, no migration changes or pending migrations.
- Frontend production build: `npm --prefix frontend run build` — **PASS** (856 modules transformed).
- Financial integrity and authorization regressions, including MK-01–MK-10: **PASS** in the full non-browser suite. This verifies code paths and test fixtures, not missing clinical or source evidence.
- Browser E2E: **NOT TESTED**. `git diff --check` is recorded after this handoff update.

### Outstanding blockers and limits

1. A qualified clinical reviewer must provide and record genuine, drug-specific unit validation and evidence before an otherwise eligible audit can be approved. Until then, the real run’s publication denial is expected and must remain in force.
2. Stored CMS source downloads needed to recompute source hashes are absent from this checkout. J0177 also has no ASP row for 2024Q1. Do not infer or manufacture either item.
3. Browser-level workflow automation is deferred to Phase 3 as specified; no browser pass is claimed here.

**Acceptance:** Admin **PASS**; Analyst real calculation/import path **PASS**; Reviewer authorization/review controls **PASS**, genuine clinical approval **BLOCKED**; Client direct API and publication-boundary controls **PASS**; financial calculation code path **PASS**, real publication **BLOCKED_BY_APPROVAL**; tenant isolation **PASS**; MK-01–MK-10 regressions **PASS**; required non-browser tests **PASS**. **PHASE 2: BLOCKED BY APPROVAL; do not proceed to Phase 3 until genuine clinical evidence is recorded.**

---

## PHASE 2 — INDEPENDENT IMPLEMENTATION COMPLETENESS REVIEW

**Date:** 2026-11-07
**Decision:** **BLOCKED_BY_APPROVAL**, not implementation-blocked. The audit found and fixed Client data-exposure and workspace omissions. Other reviewed workflow code paths are present. A real audit run is correctly rejected for publication while its clinical unit status is unresolved. The synthetic publication-state fixture is not counted as genuine clinical approval or as verified savings.

### End-to-end feature map

| Owning role / feature | Frontend action | API method and backend handler | Storage / dependencies | Authorization and evidence | Classification |
|---|---|---|---|---|---|
| Super Admin: account creation, role, disable/enable, password reset | `UserManagement.jsx`: create form, role/status buttons, password form | `GET/POST /user-accounts/` → `auth_views.user_management`; `POST /user-accounts/{id}/management/` → `auth_views.manage_user` | Django User, Groups, `AuditEvent` | `CanAdminister`; tests enforce role validation, password reset, inactive access denial; new `test_admin_account_role_and_organization_access_workflow` calls the same endpoints | **IMPLEMENTED BUT INTEGRATION UNTESTED** at the React/browser layer; backend API workflow tested |
| Super Admin: MFA and sessions | Sign-in/enrollment flow in `main.jsx`; account security in `Settings.jsx` | CSRF/sign-in/TOTP/refresh/sign-out routes → `auth_views` | User session, OTP device/challenges, auth throttle records | MFA evidence, CSRF, JWT and rate-limit tests in `test_api.py` and `test_otp.py`; no security logic changed | **FULLY IMPLEMENTED AND TESTED** at API/unit level; browser flow not run |
| Super Admin: organization, plan, access assignment/revocation | `PlanAudits.jsx`: create organization/plan, grant/revoke access | `GET/POST /organizations/`, `/plans/`; `GET/POST/DELETE /organizations/{id}/users/` → `plan_audit_setup` | `PlanOrganization`, `Plan`, `PlanOrganizationAccess`, `AuditEvent` | Admin write checks; visible organization/plan queries scoped to grants. `test_organization_and_plan_lifecycle`, new admin workflow, end-to-end grant/revoke and cross-organization denial | **IMPLEMENTED BUT INTEGRATION UNTESTED** at the React/browser layer; API and tenant behavior tested |
| Super Admin / Analyst: CMS and hospital source ingestion, reference catalog, jobs | `Sources.jsx`, `ReferenceData.jsx`, `HospitalFiles.jsx`; upload/import/refresh/detail actions | `GET /data-sources/`, `POST /data-sources/uploads/`, `GET/POST /data-sources/processing-jobs/`, `GET /data-sources/processing-jobs/{id}/`, `GET /reference-data-sets/` and detail → `views.sources`, `source_upload`, `processing_jobs`, `processing_job_detail`, `reference_catalog`, `reference_table` | Source files, processing-job DB rows, configured Parquet outputs | Super Admin and authorized Analyst gates; file safety/job/reference tests include upload traversal, job processing, catalog paging. Local original CMS source downloads are absent; no real downloads were substituted | **IMPLEMENTED BUT INTEGRATION UNTESTED** against the actual source corpus; synthetic/API cases pass; source-hash recomputation is **BLOCKED BY DATA** |
| Analyst: Claims Explorer and synthetic dataset registration | `ClaimsExplorer.jsx`: register dataset, select org/dataset, filter/page/detail | `GET/POST /claims/datasets/`; `GET /claims/synthea/summary/`, `/claims/`, `/claims/{id}/` → `claims_views` | `ClaimsExplorerDataset`, isolated Synthea/Parquet files and DuckDB queries | `CanAnalyze`, assigned organization and registered-dataset checks; claims filtering, privacy, SQL-injection and organization isolation tests | **IMPLEMENTED BUT INTEGRATION UNTESTED** at the React/browser layer; backend endpoints tested |
| Analyst: local extraction, summary import, roster upload and validation | `PlanAudits.jsx`: preview/import aggregate+manifest; upload roster; inspect quarter coverage | `POST /plan-audits/import-summary/` → `import_plan_summary`; `GET /plan-audits/imports/`; `GET/POST /plans/{id}/network-roster/` → `plan_network_roster` | `ClaimsSummaryImport`, aggregate-only `ClaimsSummaryRecord`, `NetworkRosterEntry`; SHA-256 hashes; raw claims/roster files are not retained server-side | Analyst/Super Admin only for writes; exact schema, manifest hash, plan binding, suppression, NPI, interval-conflict checks. `test_end_to_end_plan_audit_workflow`, `test_mk09_network_status_requires_consistent_full_quarter_coverage`, extractor tests | **IMPLEMENTED BUT INTEGRATION UNTESTED** in browser; API/extractor integration tested on isolated synthetic data |
| Analyst: create/run audit and financial analysis | `PlanAudits.jsx`: create/run; tabs for spending, drug, network, savings, review/report | `POST /plan-audits/create/`, `POST /plan-audits/{id}/run/`; GET overview/results/historical/drug/hospital/ASP/savings/quality → `plan_audit_imports`, `plan_audit_run`, `plan_audit_reports` | Immutable `PlanAuditRun`, `PlanAuditResult`, `SavingsOpportunity`; ASP/HPT/drug-scope Parquet and current unit reviews | `CanAnalyze`, org/plan/import binding, quarter-matched benchmarks, current run fingerprints. Real engine calculates from accepted synthetic aggregates in the end-to-end test; unresolved values keep null markup and fail closed | **IMPLEMENTED AND API-TESTED**; production-data availability **BLOCKED BY DATA** where source snapshots are missing |
| Reviewer: clinical unit validation | `UnitValidation.jsx`: inspect CMS dosage/evidence and record a decision | `GET /drug-unit-validations/`, `GET /drug-selection-scope/`, `POST /drug-selection-scope/{hcpcs}/unit-review/` → `views.unit_validations`, `review_drug_unit` | `DrugUnitReview`, CMS scope/source hashes and dosage | Reviewer/Super Admin only; requires matching CMS billing quantity/unit, reviewer identity, evidence notes, and source binding. `test_mk07_reviewer_clinical_unit_validation_access` | **BLOCKED BY CLINICAL APPROVAL** for real publication; workflow/authorization API tested, no genuine signoff available |
| Reviewer: audit quality, provenance, review, approval/rejection | `PlanAudits.jsx`: inspect provenance/quality/history; submit comment; approve/reject | `GET/POST /plan-audits/{id}/review/`, `POST .../approve/`, `POST .../reject/`, `GET .../quality/` → `audit_review`, `_set_review`, `audit_quality` | Append-only `AuditReview`, immutable run/artifact fingerprints, `AuditEvent` | Reviewer/Super Admin; current-version binding, creator/runner/artifact-builder independence, complete artifacts, valid unit quality. End-to-end test confirms genuine unresolved approval returns 409 and remains pending. Fixture-injected transition tests exercise approval/rejection mechanics separately | **IMPLEMENTED AND API-TESTED**; genuine approval **BLOCKED BY CLINICAL APPROVAL**; browser queue integration untested |
| Client: published dashboard, historical/drug/hospital comparison, quality, savings, PDF/CSV | `ClientPlanAudits.jsx`: select published report, inspect comparison sections, download reports | GET `/plan-audits/`, `/{id}/overview/`, `/historical-spending/`, `/drug-analysis/`, `/hospital-comparison/`, `/asp-benchmark/`, `/savings/`, `/quality/`, `/report/`, `/export-csv/` | Published immutable run and verified artifacts; only validated/clinically approved savings returned | Client GET allowlist plus organization grant and `published_run` checks. Direct API tests assert no internal import/source references in Client payloads and no report access before publication/after rejection | **IMPLEMENTED BUT INTEGRATION UNTESTED** at the React/browser layer; Client API contract tested on isolated published-state fixture |

### Confirmed gaps fixed

1. Client audit list exposed `summary_import_id`; audit quality exposed the complete `validation_summary` including source provenance. Client result, hospital, ASP, network, and savings endpoints also returned `source_references`, and the stored analyst CSV was served unchanged to Clients. These exposed internal import/source lineage despite the Client boundary.
2. `ClientPlanAudits.jsx` showed only headline totals and downloads. It did not render historical spending, drug/ASP comparisons, hospital reference comparisons, quality explanations, or validated savings.
3. Client download button failures had no visible error state.

Minimal fixes:

- `plan_audit_common.audit_payload` now hides the summary import ID from Client payloads.
- `plan_audit_run.audit_results`, `hospital_comparison`, and `asp_benchmark`, plus `plan_audit_reports.audit_quality`, `audit_network_validation`, and `audit_savings`, omit internal source/import metadata for Client-only accounts while preserving Reviewer/Analyst provenance.
- The Client CSV endpoint verifies the published stored artifact and returns a deterministic CSV built from the same immutable run without the internal `source_references` column. Reviewer/Analyst downloads retain the source-reference column.
- `ClientPlanAudits.jsx` now calls the published-only history, drug, hospital, quality, and savings endpoints and renders their user-facing fields, with safe empty states and visible download errors.
- No finance calculation, clinical approval gate, tenant permission, MFA/CSRF/JWT, or stored audit artifact was weakened or modified.

### Core workflow and saved-state evidence

`test_end_to_end_plan_audit_workflow` now creates the main Analyst, Reviewer, and Client through the Admin user-management API, then assigns those accounts to the synthetic organization. It runs the actual extractor against temporary TEST claims, imports the accepted summary and roster through HTTP, creates and runs an audit, and checks persisted results.

- Admin account creation: **201**; organization and plan creation: **201** each; organization access grant: **201**.
- Aggregate extractor succeeds; summary import: **201**; network roster: **201**; audit creation: **201**; actual calculation: **200**.
- Real calculation persists actual plan allowed/paid unit values and result provenance. The result has `UNIT_UNRESOLVED`; its markup remains null. Both PDF/CSV artifacts may be prepared for review, but Reviewer approval returns **409** with “Resolve blocking data quality issues before publication.” The run remains `calculation_status=completed`, `publication_status=pending`; `published_version` stays null and no approved review is saved. Client result request returns **404**.
- The separate state-machine branch deliberately injects a test-only validated marker and synthetic savings row after the real calculation. Approval/rejection, stale-version denial, client publication access, downloads, and revocation are tested there only. That branch is not clinical approval evidence and its savings are not real financial results.
- Client published-state contract tests verify the comparison/history/quality endpoints, redacted payloads, and CSV; Client endpoints return **404** after rejection. Cross-organization and unassigned Client requests also return **404**.

### Test-quality and integration limits

- `tests/test_api.py` exercises real Django endpoints using a disposable database and test-only datasets. The main synthetic workflow invokes the actual extractor and calculation engine; it does not use mocked financial calculations for the unresolved-run decision.
- The later `validated_fixture_engine` inside `test_end_to_end_plan_audit_workflow` mutates result quality/source state and inserts one synthetic savings row. It tests lifecycle guards, not the real calculation result or clinical evidence.
- `tests/test_pipeline.py`, `tests/test_client_extractor.py`, and `tests/test_reference_data.py` use synthetic fixture files; they do not download current CMS or hospital datasets. Unit/financial calculation edge cases and MK-01–MK-10 are covered there and in API regression tests.
- Organization isolation is covered by `test_claims_explorer_organization_scoping_and_privacy` and the cross-organization cases in `test_end_to_end_plan_audit_workflow`.
- The four frontend tests exercise role-policy helpers only. There is no component-level API interaction suite. Production build validates compilation, not browser behavior. Browser E2E was not run; React loading/error behavior and route composition therefore remain **frontend integration unverified**.

### Files changed in this independent review

- `backend/pricing/plan_audit_common.py`
- `backend/pricing/plan_audit_run.py`
- `backend/pricing/plan_audit_reports.py`
- `frontend/src/pages/ClientPlanAudits.jsx`
- `tests/test_api.py`
- `docs/PROJECT_HANDOFF.md`

No other files, raw sources, reference Parquet, operational/customer data, migrations, or dependencies were changed. Existing uncommitted work was preserved.

### Final verification for independent review

- Focused Client/Admin workflow and lifecycle contracts: **2 passed**; focused real unresolved clinical-gate test: **1 passed**.
- Full non-browser backend suite: `.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_browser_e2e.py -q -p no:cacheprovider --basetemp=.venv\phase2-independent-final2-20261107` — **141 passed, 0 failed, 0 skipped**.
- Frontend role-policy tests: **4 passed**; React production build: **PASS** (856 modules).
- Django system check: **PASS**. Migration checks: **PASS**, no changes or pending migrations.
- `git diff --check`: **PASS** after this handoff edit.
- Browser E2E: **NOT TESTED**.

**Final decision:** **PHASE 2 BLOCKED_BY_APPROVAL.** Backend implementation gaps identified in the Client boundary and Client report page were fixed. Admin and Analyst business operations and backend authorization are verified; Reviewer workflow guards are verified; Client API privacy and publication controls are verified. Client React/browser integration remains unverified. Genuine clinical review is still required before any real run can be approved or published. Do not proceed to Phase 3.

---

## PHASE 3 — REAL BROWSER ACCEPTANCE

**Date:** 2026-11-07
**Technical result:** **VERIFIED** for the tested software workflows. The RG-01 suite ran in real Chromium in headless and headed modes against the React app, Django live server, disposable file-backed SQLite database, and actual calculation engine. This does not clear the separate clinical approval or business release gates.

### Environment and isolation

- Browser automation: Playwright Python 1.64.1; Chromium **156.0.8078.4**. Node.js **22.20.0**. The checked-in `.venv` Python environment was used.
- Each invocation set `MESHKOR_TEST_DB_PATH` to a new `.venv\phase3-browser-<mode>-...sqlite3` path and passed a unique `.venv\phase3-browser-<mode>-...-tmp...` `--basetemp`. The final reported headless DB was `.venv\phase3-browser-headless-report-20261107.sqlite3`; the final headed DB was `.venv\phase3-browser-headed-offline-20261107.sqlite3`.
- The test asserts the configured live-server database resolves to the exact environment-selected test path, exists as a file, and differs from both `data\operational\meshkor.sqlite3` and `settings.OPERATIONAL_DB_PATH`. It also verifies `pricing_auththrottlebucket` exists in that database after migrations.
- Django `live_server` owned the backend process on a dynamically assigned localhost port. The test-owned Vite process used a dynamically reserved localhost port and `VITE_PROXY_API_TARGET=http://127.0.0.1:<live-server-port>`. The harness readiness-checks both services and terminates its own Vite process; pytest owns the live server lifecycle.
- Synthetic users, organizations, plans, claims summaries, network roster, reference files, and hospital prices were used. Test artifacts remained in the dedicated ignored `.venv` directories. No operational database, customer data, or genuine reference files were modified.
- The external Google Fonts stylesheet is fulfilled with an empty CSS response by the browser harness because this environment blocks outbound network access. The app uses its local fallback font during the run. No dependency or production source configuration was added for this test accommodation.

### Browser results

| Area | Result and observed evidence |
|---|---|
| Headless Chromium RG-01 | **PASS**, `1 passed` (final instrumented run: 63.29 seconds). |
| Headed Chromium RG-01 | **PASS**, `1 passed` (77.60 seconds, `--slowmo 20`). |
| Admin | **PASS** — MFA including invalid OTP rejection; admin dashboard, Django Admin session, account creation for Analyst/Reviewer/Client, organization and plan creation, access grants, Data Sources page/API and Audit Logs page/API. |
| Analyst | **PASS** — assigned organization scope, price comparison page, permitted Claims Explorer, aggregate import, roster import, audit creation, actual calculation and report artifact generation. The test verifies that unresolved J1745 markup is null and renders “Not comparable.” |
| Reviewer | **PASS** — unit-review screen and synthetic review record, tenant isolation, contributor independence, Reviewer run denial (403), unresolved audit approval denial (409), no publication for that unresolved audit, approval of the separate software-only fixture, then rejection and stale-binding denial. |
| Client | **PASS** — account security page, correct empty state and direct unpublished PDF/CSV/results denial, direct Claims Explorer and Data Sources route denial, assigned published fixture display, and immediate report denial following rejection. |
| Responsive layout | **PASS** — 1440×900 desktop and 390×844 mobile viewport; horizontal overflow assertions passed. Native required-field validation was also checked. |

The headless browser observed **349×200, 15×201, 1×204, 8×401, 6×403, 2×409, and 14×404** API responses; **no API 5xx** occurred. The 401/403/404 responses were produced by deliberate unauthenticated, forbidden, unpublished, rejected, or cross-tenant requests. Both 409 responses were the unresolved clinical approval gate and stale approval binding. The browser test recorded no uncaught JavaScript errors and no unexpected console errors. The only blocked external resource was Google Fonts, handled by the explicit offline stylesheet route above.

### Calculation, publication contract, and Client confidentiality

- The Analyst browser uploads the extracted, suppressed synthetic aggregate and a synthetic roster, then triggers the actual calculation path. The test reads the persisted result through the real API. The unresolved J1745 result has no allowed markup; an independent Reviewer approval attempt returns 409 and `published_version` remains null.
- A separate synthetic J9271 fixture has a synthetic unit review and synthetic hospital rates so the browser can exercise the existing server-side publication contract. Reviewer approval, Client serialization, historical/drug/hospital comparisons, and real generated PDF/CSV downloads were exercised through the browser. This is classified as **SOFTWARE PUBLICATION CONTRACT VERIFIED USING SYNTHETIC FIXTURES** only. It is not genuine clinical approval, validated market savings, production publication acceptance, or evidence that a real client report may be released.
- Client API checks confirm no `source_references`, `import_quality`, or `summary_import_id` reaches the Client. Client CSV excludes `source_references` and `claims_summary_import_id`. The PDF begins with `%PDF-`; the CSV has the expected `hcpcs_code` header. The Client’s results and both report URLs return 404 before publication and after rejection. Cross-organization and reviewer-comment requests also remain inaccessible.
- No clinical evidence was fabricated or treated as human signoff. A qualified clinical reviewer must still validate each real drug’s units before a genuine report can be published.

### UI defect fixed

The real Client browser flow found a render-time exception when the selected report changed from no selection to an ID: `useApi` briefly supplies `data: null` for newly activated section requests. Client render callbacks now safely handle that loading transition. This is a narrow defensive rendering fix in `ClientPlanAudits.jsx`; it does not change API permissions, calculation, publication, or report data.

### Verification

- Final instrumented headless browser run: `python -m pytest tests/test_browser_e2e.py -q -s -p no:cacheprovider --basetemp .venv\phase3-browser-headless-report-tmp-20261107` with the unique `MESHKOR_TEST_DB_PATH` above — **1 passed**.
- Final headed browser run: `python -m pytest tests/test_browser_e2e.py -q -p no:cacheprovider --headed --slowmo 20 --basetemp .venv\phase3-browser-headed-offline-tmp-20261107` with its separate unique test DB — **1 passed**.
- Backend regression suite: `.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/test_browser_e2e.py -q -p no:cacheprovider --basetemp .venv\phase3-regression-final-20261107` — **141 passed**.
- Frontend role tests: `npm --prefix frontend test` — **4 passed**.
- Django `check` — **PASS**. `makemigrations --check --dry-run` — **PASS**, no changes detected. `migrate --check` — **PASS**.
- React production build — **PASS**, 856 modules transformed.
- `git diff --check` scoped to modified project files — **PASS**. An unrestricted invocation also traversed pre-existing `tmp_pytest` entries that are inaccessible in this environment; that directory was not cleaned or modified for this phase.

### Modified files and remaining limits

- Browser integration fix: `frontend/src/pages/ClientPlanAudits.jsx`.
- Browser workflow coverage and isolated network/font instrumentation: `tests/test_browser_e2e.py`.
- This Phase 3 handoff section: `docs/PROJECT_HANDOFF.md`.
- Preserved earlier uncommitted Phase 2 work: `backend/pricing/plan_audit_common.py`, `backend/pricing/plan_audit_reports.py`, `backend/pricing/plan_audit_run.py`, and `tests/test_api.py`.

The raw CMS source downloads needed for some provenance hash recomputation remain unavailable, and J0177 still has no ASP row for 2024Q1. Genuine clinical unit validation and business release authorization remain separate blockers for a real report. The test covers the current role workflows; it is not a comprehensive visual review of every page/control or every browser engine.

**Acceptance:** RG-01 browser E2E **VERIFIED** in both modes; Admin, Analyst, Reviewer, Client, tenant restrictions, MFA, real calculation, expected clinical blocking, synthetic publication contract, Client confidentiality, downloads, desktop/mobile assertions, backend/frontend regressions, migrations, and build **PASS**. **PHASE 3 TECHNICAL VERIFICATION: VERIFIED.** Real clinical signoff and business release remain pending. No commit, push, or deployment was performed.
