# Phase 4: Plan-Specific Infusion Drug Audits & Client Onboarding

## 1. Data Boundary and Privacy Architecture

The client extractor processes employer or TPA claim files inside that organization's controlled environment. It makes **zero network requests**. Only the approved aggregate CSV (`claims_summary.csv`) and its matching cryptographic manifest (`manifest.json`) are uploaded to MeshKor central.

- **Zero Raw Claims Ingestion**: Raw claims, internal claim IDs, member/patient IDs, and local quality logs are never accepted by the central import endpoint, never transmitted over the network, and never stored in the central database.
- **Local Quality Reports**: The local quality report (`output/data_quality.json`) contains source row numbers and generic validation reasons. It must remain strictly within the client environment.
- **HIPAA and Disclosure Boundary**: The extractor's k-anonymity suppression controls (primary threshold of 11 distinct members and complementary cell suppression) are technical privacy controls, not a formal HIPAA compliance determination. Customer organizations must conduct their own disclosure review.

---

## 2. Client-Side Extractor Setup & Execution

Run inside the client's controlled environment:

```powershell
cd client_extractor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config/client_config.example.yaml config/client_config.yaml
python -m src.cli extract --claims path\to\claims.csv --config config\client_config.yaml --output output
```

### 2.1 Supported File Formats & Input Limits
- **Formats**: CSV, XLSX, and XLSM.
- **EDI 837P / 837I**: Deliberately disabled until payer-specific companion guides and adjudication rules are implemented.
- **Safety Caps**: Input files are capped at 256 MiB and 1,000,000 records. Individual CSV fields are capped at 1,000,000 characters. XLSX/XLSM archives are checked against decompression bombs (zip bombs) with internal file count and compression ratio limits.

### 2.2 Input Schema & Field Requirements

| Canonical Field | Type / Requirement | Description |
|---|---|---|
| `claim_id` | Text | Unique source claim identifier; preserve as text |
| `service_date` | ISO Date / Datetime | Date of service (`YYYY-MM-DD`) |
| `hcpcs_code` | Text (5-char) | Valid HCPCS code |
| `site_npi` | Text (10-digit) | Valid billing or service provider NPI; preserve leading zeroes |
| `units` | Decimal ($> 0$) | Adjudicated positive billed units; never infer missing units |
| `allowed_amount` | Decimal ($\ge 0$) | Total adjudicated allowed amount for the row |
| `paid_amount` | Decimal ($\ge 0$) | Adjudicated amount paid by plan; zero is permitted |
| `member_id` | Text | Source member identifier; strictly local, never exported |
| `claim_status` | Enum | `paid`, `approved`, `adjusted`, `reversed`, or `denied` |
| `plan_id` | Text | Must match the `plan_id` configured in `client_config.yaml` |
| `adjustment_reference` | Text (Optional) | Reference to previous claim ID being adjusted |
| `reversal_reference` | Text (Optional) | Reference to previous claim ID being reversed |
| `service_setting` | Text (Optional) | Setting description (e.g., `hospital_outpatient`, `physician_office`) |

### 2.3 Source Column Mapping (`client_config.yaml`)
When customer column labels differ from canonical names, configure `column_mapping` in the local client configuration:

```yaml
column_mapping:
  claim_id: "Claim Number"
  service_date: "Date of Service"
  hcpcs_code: "Procedure Code"
  site_npi: "Billing Provider NPI"
  units: "Quantity"
  allowed_amount: "Allowed Charges"
  paid_amount: "Net Paid"
  member_id: "Member Identifier"
  claim_status: "Claim Status Description"
  plan_id: "Benefit Plan ID"
  service_setting: "Place of Service"
```

Mappings must map distinct source columns. Required mapped headers are validated before parsing records. Identifiers must be preserved as text in spreadsheets so leading zeroes are not discarded.

### 2.4 Payment Semantics & Adjustment Linkage
- Adjudicated claim-line values must be used; do not mix claim-line figures with member or plan-level totals.
- Adjustments and reversals are linked only when the reference uniquely points to a single claim sharing the exact same member, plan, HCPCS code, provider NPI, and service date.
- Denied claims, unresolved references, and duplicate/conflicting records are excluded from export and logged in `data_quality.json`.

### 2.5 Billing-Unit Evidence Requirements
`hcpcs_billing_units` in `client_config.yaml` must be populated only from reviewed, source-backed clinical evidence:

```yaml
hcpcs_billing_units:
  J1745:
    qty: 10
    unit: "MG"
    verification_status: "validated"
    source_reference: "FDA Package Insert Rev 2024-01"
    source_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

Every code requires `qty`, `unit`, `verification_status: validated`, `source_reference`, and the source file's 64-character SHA-256 in `source_sha256`. There is no fallback or default billing unit. Codes without verified billing units will not produce exportable aggregates.

### 2.6 Privacy Suppression Rules
- Aggregation is performed by `(plan_reference, hcpcs_code, site_npi, quarter, service_setting)`.
- Primary cell suppression: Groups with fewer than 11 distinct members (`distinct(member_id) < 11`) are suppressed.
- Complementary suppression: In groups with a small suppressed cell, a second cell is suppressed to prevent mathematical reconstruction.
- No exact member counts or subtotal rows are included in the export.
- Manifest declares both `small_cell_suppression_threshold: 11` and `complementary_suppression_applied: true`. Central systems reject any manifest missing these declarations.

---

## 3. Provider Network Roster Schema

A plan network roster CSV must use these exact columns:

```csv
provider_npi,provider_name,network_name,network_status,effective_start,effective_end,service_location,applicable_plan_reference
```

- `network_status`: Must be `in_network` or `out_of_network`.
- `effective_start` and `effective_end`: Valid ISO dates (`YYYY-MM-DD`). Leave `effective_end` empty only for open-ended coverage.
- `applicable_plan_reference`: Must exactly match the target plan's `plan_reference`.
- Full-Quarter Rule: A provider is considered in-network for a calendar quarter only when a roster interval spans the entire quarter.
- Conflict Prevention: Ingestion rejects files containing overlapping intervals with conflicting statuses for the same provider, both internally and against existing database records.

---

## 4. Central Audit Workflow

1. **Organization and Plan Setup**:
   - Super Admin creates the employer/TPA organization (`PlanOrganization`) and assigns an active plan (`Plan`) with a unique `plan_reference`.
   - Admin grants explicit access to Analysts, Reviewers, or Clients (`PlanOrganizationAccess`).
2. **Aggregate Ingestion**:
   - Analyst uploads the client extractor's `claims_summary.csv` and matching `manifest.json`.
   - Browser previews CSV headers, row counts, manifest privacy flags, and SHA-256 locally.
   - Central API authoritative checks: validates aggregate SHA-256, schema version, date/quarter formats, NPI checksum, positive units, non-negative amounts, member count bands (`11-50`, `51-100`, `100+`), and provenance matching.
   - Accepted rows are bulk-created in `ClaimsSummaryRecord`.
3. **Network Roster Upload**:
   - Admin or Analyst uploads the plan network roster CSV under Plan Setup.
4. **Audit Execution**:
   - Analyst creates a `PlanAudit` tied to an accepted summary import.
   - Triggering the audit run invokes `plan_audit_engine.run_plan_audit()`.
   - Matches claims against CMS ASP payment limits and verified hospital pricing references.
   - Calculates potential savings opportunities where an in-network lower-priced alternative site is observed.
5. **Review and Governance**:
   - Authorized Reviewers examine results, inspect source references, and submit comments.
   - Reviewers record formal decisions (`approved` or `rejected`). Review records are strictly append-only.
   - Client accounts can access audits only after a formal review approval and report generation.
6. **Reporting and Exports**:
   - Analyst generates the official PDF report (`ReportLab`).
   - Authorized users download results CSV and executive PDF reports.

---

## 5. Calculation Rules & Mathematical Definitions

- **Plan allowed per unit**: $\text{total\_allowed} / \text{total\_units}$
- **Plan paid per unit**: $\text{total\_paid} / \text{total\_units}$
- **Hospital markup**: $\text{hospital\_price\_per\_unit} / \text{asp\_payment\_limit}$
- **Plan allowed markup**: $\text{plan\_allowed\_price\_per\_unit} / \text{asp\_payment\_limit}$
- **Plan paid markup**: $\text{plan\_paid\_price\_per\_unit} / \text{asp\_payment\_limit}$
- **Plan to hospital ratio**: $\text{plan\_allowed\_price\_per\_unit} / \text{hospital\_price\_per\_unit}$
- **CMS ASP statutory add-on**: Payment limit already includes statutory 6%; no additional 6% is added.
- **Quarter matching**: Exact calendar quarter match required; no fallback to later quarters.
- **Potential savings**:
  $$\text{Opportunity} = \max\left(0, \text{current\_allowed\_per\_unit} - \text{alternative\_allowed\_per\_unit}\right) \times \text{eligible\_units}$$
  - Alternative site must have verified full-quarter in-network roster status.
  - Same HCPCS, same calendar quarter, same service setting, verified billing units.
  - Labeled as **potential savings pending clinical review**, never guaranteed or recoverable overpayments.

---

## 6. Real Pilot Readiness & Data Requirements

The commercial prerequisite requires that the Phase 1 market report has been used with at least three brokers or TPAs before commercial Phase 4 audits begin.

To conduct an authorized paid pilot:
1. Confirm commercial prerequisite is satisfied.
2. Sign data-sharing and business associate agreements with employer/TPA.
3. Install and run `client_extractor` locally inside customer environment.
4. Obtain reviewed billing-unit evidence for each in-scope HCPCS.
5. Obtain historical provider network roster with full-quarter coverage.
6. Add verified hospital name-to-NPI mappings in `config/hospital_sites.csv` if hospital reference comparison is desired (currently empty by default).
7. Import aggregate summary and roster; run audit; conduct clinical review; generate approved report.
