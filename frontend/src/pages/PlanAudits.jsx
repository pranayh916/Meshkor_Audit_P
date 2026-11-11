import React, { useCallback, useEffect, useMemo, useState } from "react";
import { deleteJSON, downloadFile, getAllPages, getJSON, patchJSON, postJSON, uploadPlanSummary, uploadNetworkRoster } from "../api.js";

// ---------------------------------------------------------------------------
// Role helpers
// ---------------------------------------------------------------------------
const isAdmin = (user) => user?.roles?.some((role) => ["SUPER_ADMIN", "Admin"].includes(role));
const isAnalyst = (user) => isAdmin(user) || user?.roles?.includes("ANALYST");
const isReviewer = (user) => isAdmin(user) || user?.roles?.includes("REVIEWER");

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
const money = (value) => {
  if (value == null || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: number < 10 ? 3 : 2,
      }).format(number)
    : "—";
};
const count = (value) => (value == null ? "—" : Number(value).toLocaleString("en-US"));
const multiple = (value) =>
  value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(2)}×`;
const benchmarkMultiple = (value) => value == null ? "Not comparable" : multiple(value);
const pct = (value) =>
  value == null || !Number.isFinite(Number(value)) ? "—" : `${(Number(value) * 100).toFixed(1)}%`;

// ---------------------------------------------------------------------------
// CSV manifest constants (preserved from prior implementation)
// ---------------------------------------------------------------------------
const SUMMARY_FIELDS = [
  "plan_reference", "hcpcs_code", "site_npi", "quarter", "service_setting",
  "total_units", "total_allowed_amount", "total_paid_amount", "member_count_band",
  "source_period", "extraction_timestamp", "schema_version",
];

function csvRecordCount(text) {
  let records = 0;
  let quoted = false;
  let hasContent = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '"') {
      if (quoted && text[index + 1] === '"') index += 1;
      else quoted = !quoted;
      hasContent = true;
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (hasContent) records += 1;
      hasContent = false;
      if (character === "\r" && text[index + 1] === "\n") index += 1;
    } else {
      hasContent = true;
    }
  }
  if (quoted) throw new Error("The aggregate CSV contains an unclosed quoted field.");
  if (hasContent) records += 1;
  return records;
}

async function inspectAggregateFiles(summaryFile, manifestFile, planReference) {
  if (!summaryFile || !manifestFile) throw new Error("Choose both approved aggregate files.");
  if (summaryFile.size > 64 * 1024 * 1024 || manifestFile.size > 1024 * 1024) {
    throw new Error("The aggregate CSV or manifest exceeds the upload limit.");
  }
  const [text, manifestText] = await Promise.all([summaryFile.text(), manifestFile.text()]);
  const csvText = text.replace(/^\uFEFF/, "");
  const header = csvText.split(/\r\n|\n|\r/, 1)[0];
  if (header !== SUMMARY_FIELDS.join(",")) {
    throw new Error("The CSV header does not match the approved aggregate schema.");
  }
  let manifest;
  try { manifest = JSON.parse(manifestText.replace(/^\uFEFF/, "")); }
  catch { throw new Error("The manifest is not valid JSON."); }
  if (
    manifest.file !== summaryFile.name ||
    manifest.schema_version !== "1.0" ||
    JSON.stringify(manifest.approved_fields) !== JSON.stringify(SUMMARY_FIELDS) ||
    manifest.raw_claims_included !== false ||
    manifest.member_identifiers_included !== false ||
    manifest.small_cell_suppression_threshold !== 11 ||
    manifest.complementary_suppression_applied !== true
  ) {
    throw new Error("Manifest file, schema, privacy, or suppression declarations are invalid.");
  }
  if (!globalThis.crypto?.subtle) throw new Error("Secure SHA-256 preview is unavailable in this browser context.");
  const digest = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", await summaryFile.arrayBuffer()))
  ).map((byte) => byte.toString(16).padStart(2, "0")).join("");
  if (manifest.sha256 !== digest) throw new Error("Manifest SHA-256 does not match the selected aggregate CSV.");
  const provenance = manifest.source_provenance;
  if (
    !provenance ||
    !/^[a-f\d]{64}$/i.test(provenance.source_sha256 || "") ||
    !["csv", "xlsx", "xlsm"].includes(provenance.source_format) ||
    !Number.isInteger(provenance.input_records) ||
    provenance.input_records < 1 ||
    provenance.plan_reference !== planReference ||
    typeof provenance.source_period !== "string" ||
    !provenance.source_period ||
    !Number.isInteger(manifest.aggregate_rows) ||
    manifest.aggregate_rows !== csvRecordCount(csvText) - 1
  ) {
    throw new Error("Manifest provenance, plan reference, or aggregate row count is invalid.");
  }
  return {
    csvDigest: digest,
    rowCount: manifest.aggregate_rows,
    sourcePeriod: provenance.source_period,
    sourceHash: provenance.source_sha256,
  };
}

// ---------------------------------------------------------------------------
// Shared UI components
// ---------------------------------------------------------------------------
function ErrorBox({ error, details }) {
  return error ? (
    <div className="data-quality-alert" role="alert">
      <div className="alert-content">
        <strong className="alert-title">Could not complete the request</strong>
        <span className="alert-description">{error}</span>
        {details && <pre className="plan-audit-error-details">{JSON.stringify(details, null, 2)}</pre>}
      </div>
    </div>
  ) : null;
}

function Field({ label, ...props }) {
  return <label className="plan-audit-field">{label}<input {...props} /></label>;
}

function EmptyState({ message, sub }) {
  return (
    <div className="empty-panel-state">
      <p>{message}</p>
      {sub && <p className="muted">{sub}</p>}
    </div>
  );
}

function QualityBadge({ status }) {
  const cls = status === "VALID" ? "validated" : "pending";
  return <span className={`status-tag ${cls}`}>{status}</span>;
}

// ---------------------------------------------------------------------------
// Simple bar chart using CSS (no new npm dependencies)
// ---------------------------------------------------------------------------
function BarChart({ data, labelKey, valueKey, title, formatValue = money }) {
  if (!data || data.length === 0) return null;
  const maxVal = Math.max(...data.map((d) => Number(d[valueKey]) || 0), 1);
  return (
    <div className="plan-audit-chart" aria-label={title}>
      <p className="plan-audit-chart-title">{title}</p>
      <div className="plan-audit-chart-bars">
        {data.map((d) => {
          const val = Number(d[valueKey]) || 0;
          const barWidth = `${Math.max(1, (val / maxVal) * 100).toFixed(1)}%`;
          return (
            <div key={d[labelKey]} className="plan-audit-chart-row">
              <span className="plan-audit-chart-label" title={d[labelKey]}>{d[labelKey]}</span>
              <div className="plan-audit-chart-bar-track">
                <div className="plan-audit-chart-bar" style={{ width: barWidth }} />
              </div>
              <span className="plan-audit-chart-value">{formatValue(d[valueKey])}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Historical Spending
// ---------------------------------------------------------------------------
function HistoricalSpendingSection({ auditId, audit, metrics }) {
  const [spending, setSpending] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [hcpcsFilter, setHcpcsFilter] = useState("");
  const [quarterFilter, setQuarterFilter] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [settingFilter, setSettingFilter] = useState("");
  const [qualityFilter, setQualityFilter] = useState("");

  useEffect(() => {
    if (!auditId || !audit || !["completed", "needs_review"].includes(audit.status)) {
      setSpending(null);
      return undefined;
    }
    let alive = true;
    setLoading(true);
    setErr("");
    getJSON(`plan-audits/${auditId}/historical-spending/`, {
      hcpcs_code: hcpcsFilter,
      quarter: quarterFilter,
      site_npi: siteFilter,
      service_setting: settingFilter,
      data_quality_status: qualityFilter,
    })
      .then((data) => { if (alive) { setSpending(data); setLoading(false); } })
      .catch((e) => { if (alive) { setErr(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, [auditId, audit?.status, hcpcsFilter, quarterFilter, siteFilter, settingFilter, qualityFilter]);

  const topByAllowed = useMemo(() => {
    if (!spending?.by_hcpcs) return [];
    return [...spending.by_hcpcs]
      .sort((a, b) => Number(b.total_allowed_amount || 0) - Number(a.total_allowed_amount || 0))
      .slice(0, 15);
  }, [spending?.by_hcpcs]);

  const topByPaid = useMemo(() => {
    if (!spending?.by_hcpcs) return [];
    return [...spending.by_hcpcs]
      .sort((a, b) => Number(b.total_paid_amount || 0) - Number(a.total_paid_amount || 0))
      .slice(0, 15);
  }, [spending?.by_hcpcs]);

  if (!audit) {
    return <EmptyState message="Select an audit to view historical spending." />;
  }
  if (!["completed", "needs_review"].includes(audit.status)) {
    return (
      <EmptyState
        message="No historical spending data available."
        sub={`This audit has status "${audit.status}". Run the audit to generate results.`}
      />
    );
  }
  if (loading) return <p className="muted">Loading historical spending…</p>;
  if (err) return <ErrorBox error={err} />;
  if (!spending) return null;

  if (!spending.available) {
    return (
      <div className="dashboard-panel">
        <EmptyState
          message="No approved aggregate data available for this audit."
          sub={spending.reason}
        />
        <ul className="plan-audit-quality">
          <li>To populate this view, the employer/TPA must supply a claims export to the local extractor.</li>
          <li>The extractor produces standardized claims summary and verification manifest files.</li>
          <li>An Analyst imports those files under Plan Setup → Import approved aggregates.</li>
          <li>An Analyst then creates and runs a Plan Audit.</li>
          <li>Synthetic datasets (CMS DE-SynPUF and Synthea Synthetic Demo) are available only in the separate Claims Explorer.</li>
        </ul>
      </div>
    );
  }

  const s = spending.summary;
  return (
    <div>
      {/* Filters */}
      <section className="dashboard-panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">Filter Historical Spending</h3>
            <p className="panel-subtitle">Apply server-side filters across approved historical aggregate spending.</p>
          </div>
          {(hcpcsFilter || quarterFilter || siteFilter || settingFilter || qualityFilter) && (
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                setHcpcsFilter("");
                setQuarterFilter("");
                setSiteFilter("");
                setSettingFilter("");
                setQualityFilter("");
              }}
            >
              Clear Filters
            </button>
          )}
        </div>
        <div className="plan-audit-filters" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "10px" }}>
          <Field
            label="HCPCS Code"
            type="text"
            placeholder="e.g. J9271"
            value={hcpcsFilter}
            onChange={(e) => setHcpcsFilter(e.target.value.toUpperCase())}
          />
          <Field
            label="Quarter"
            type="text"
            placeholder="e.g. 2026Q4"
            value={quarterFilter}
            onChange={(e) => setQuarterFilter(e.target.value.toUpperCase())}
          />
          <Field
            label="Site NPI"
            type="text"
            placeholder="10-digit NPI"
            value={siteFilter}
            onChange={(e) => setSiteFilter(e.target.value)}
          />
          <Field
            label="Setting"
            type="text"
            placeholder="e.g. outpatient"
            value={settingFilter}
            onChange={(e) => setSettingFilter(e.target.value)}
          />
          <label className="plan-audit-field">
            Quality Status
            <select
              value={qualityFilter}
              onChange={(e) => setQualityFilter(e.target.value)}
            >
              <option value="">All Statuses</option>
              <option value="VALID">VALID</option>
              <option value="UNIT_UNRESOLVED">UNIT_UNRESOLVED</option>
              <option value="REFERENCE_NOT_FOUND">REFERENCE_NOT_FOUND</option>
              <option value="NETWORK_UNVERIFIED">NETWORK_UNVERIFIED</option>
            </select>
          </label>
        </div>
      </section>

      {/* Summary metrics */}
      <section className="dashboard-panel">
        <h3 className="panel-title">Spending summary</h3>
        <p className="muted">
          {audit.organization_name} · {audit.plan_name} · {audit.reporting_period} · {audit.status}
        </p>
        <div className="plan-audit-metrics">
          <article><span>Total allowed spending</span><strong>{money(s.total_allowed_amount)}</strong></article>
          <article><span>Total paid spending</span><strong>{money(s.total_paid_amount)}</strong></article>
          <article><span>Total units analyzed</span><strong>{count(s.total_units)}</strong></article>
          <article><span>Distinct HCPCS codes</span><strong>{count(s.distinct_hcpcs_count)}</strong></article>
          <article><span>Distinct sites (NPI)</span><strong>{count(s.distinct_site_count)}</strong></article>
          <article><span>Quarters covered</span><strong>{count(s.distinct_quarter_count)}</strong></article>
          <article><span>Matched ASP benchmarks</span><strong>{count(s.matched_benchmark_rows)}</strong></article>
          <article><span>Unmatched benchmarks</span><strong>{count(s.unmatched_benchmark_rows)}</strong></article>
          <article>
            <span>Data quality warnings</span>
            <strong>{count(metrics?.data_quality_warnings)}</strong>
          </article>
        </div>
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Totals include only approved, unsuppressed aggregate rows. No member counts or claim-level detail are shown.
        </p>
      </section>

      {/* Charts */}
      {spending.by_quarter?.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Spending & Utilization by Quarter</h3>
          <BarChart
            data={spending.by_quarter}
            labelKey="quarter"
            valueKey="total_allowed_amount"
            title="Allowed amount by quarter"
          />
          <BarChart
            data={spending.by_quarter}
            labelKey="quarter"
            valueKey="total_paid_amount"
            title="Paid amount by quarter"
          />
          <BarChart
            data={spending.by_quarter}
            labelKey="quarter"
            valueKey="total_units"
            title="Billed units by quarter (utilization)"
            formatValue={count}
          />
        </section>
      )}

      {topByAllowed.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Top Infusion Drugs by Spending</h3>
          <BarChart
            data={topByAllowed}
            labelKey="hcpcs_code"
            valueKey="total_allowed_amount"
            title="Top 15 Drugs by Allowed Spending"
          />
          <BarChart
            data={topByPaid}
            labelKey="hcpcs_code"
            valueKey="total_paid_amount"
            title="Top 15 Drugs by Plan Paid Spending"
          />
        </section>
      )}

      {/* Historical price-per-unit table */}
      {spending.by_hcpcs?.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Historical Drug Price-Per-Unit Comparisons</h3>
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>HCPCS</th>
                  <th>Drug Description</th>
                  <th>Allowed Spending</th>
                  <th>Paid Spending</th>
                  <th>Total Units</th>
                  <th>Allowed / Unit</th>
                  <th>Paid / Unit</th>
                  <th>Sites</th>
                  <th>Quarters</th>
                </tr>
              </thead>
              <tbody>
                {spending.by_hcpcs.map((row) => (
                  <tr key={row.hcpcs_code}>
                    <td><strong>{row.hcpcs_code}</strong></td>
                    <td>{row.drug_description || "—"}</td>
                    <td>{money(row.total_allowed_amount)}</td>
                    <td>{money(row.total_paid_amount)}</td>
                    <td>{count(row.total_units)}</td>
                    <td>{money(row.allowed_per_unit)}</td>
                    <td>{money(row.paid_per_unit)}</td>
                    <td>{count(row.site_count)}</td>
                    <td>{count(row.quarter_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {spending.by_site?.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Spending by site NPI</h3>
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>Site NPI</th>
                  <th>Total allowed</th>
                  <th>Total paid</th>
                  <th>Total Units</th>
                  <th>HCPCS count</th>
                  <th>Network status</th>
                </tr>
              </thead>
              <tbody>
                {spending.by_site.map((row) => (
                  <tr key={row.site_npi}>
                    <td><strong>{row.site_npi}</strong></td>
                    <td>{money(row.total_allowed_amount)}</td>
                    <td>{money(row.total_paid_amount)}</td>
                    <td>{count(row.total_units)}</td>
                    <td>{count(row.hcpcs_count)}</td>
                    <td>
                      <span className={`status-tag ${row.network_status_summary === "IN_NETWORK" ? "validated" : "pending"}`}>
                        {row.network_status_summary}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {spending.by_setting?.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Spending by service setting</h3>
          <BarChart
            data={spending.by_setting}
            labelKey="service_setting"
            valueKey="total_allowed_amount"
            title="Allowed amount by service setting"
          />
        </section>
      )}

      {/* Data quality and notes */}
      {spending.data_quality && Object.keys(spending.data_quality).length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Data quality summary</h3>
          <div className="plan-audit-quality">
            {Object.entries(spending.data_quality).map(([status, n]) => (
              <p key={status}><QualityBadge status={status} /> {count(n)} result rows</p>
            ))}
          </div>
        </section>
      )}

      {spending.data_notes?.length > 0 && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Interpretation notes</h3>
          <div className="plan-audit-quality">
            {spending.data_notes.map((note) => <p key={note}>• {note}</p>)}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Drug Cost Analysis
// ---------------------------------------------------------------------------
function DrugCostSection({ auditId, audit }) {
  const [results, setResults] = useState([]);
  const [resultCount, setResultCount] = useState(0);
  const [hcpcsFilter, setHcpcsFilter] = useState("");
  const [quarterFilter, setQuarterFilter] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [qualityFilter, setQualityFilter] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setResults([]); setResultCount(0);
    if (!auditId) return undefined;
    let alive = true;
    getJSON(`plan-audits/${auditId}/results/`, {
      limit: 500,
      hcpcs_code: hcpcsFilter,
      quarter: quarterFilter,
      site_npi: siteFilter,
      data_quality_status: qualityFilter,
    })
      .then((page) => {
        if (alive) { setResults(page.results || []); setResultCount(page.count || 0); }
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [auditId, hcpcsFilter, quarterFilter, siteFilter, qualityFilter]);

  if (!audit) return <EmptyState message="Select a completed audit to view drug cost analysis." />;

  return (
    <div>
      <section className="dashboard-panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">Drug cost analysis</h3>
            <p className="panel-subtitle">
              Plan allowed and paid amounts per billing unit alongside CMS ASP limits.
              Hospital reference prices are not this plan&apos;s contracted rates.
            </p>
          </div>
        </div>
        <ErrorBox error={error} />
        <div className="plan-audit-filters">
          <Field
            label="Filter HCPCS"
            value={hcpcsFilter}
            maxLength="5"
            placeholder="J-code"
            onChange={(e) => setHcpcsFilter(e.target.value.toUpperCase())}
          />
          <Field
            label="Filter quarter"
            value={quarterFilter}
            maxLength="6"
            placeholder="2025Q1"
            onChange={(e) => setQuarterFilter(e.target.value.toUpperCase())}
          />
          <Field
            label="Filter site NPI"
            value={siteFilter}
            maxLength="10"
            placeholder="10-digit NPI"
            onChange={(e) => setSiteFilter(e.target.value.replace(/\D/g, ""))}
          />
          <label className="plan-audit-field">
            Filter quality
            <select value={qualityFilter} onChange={(e) => setQualityFilter(e.target.value)}>
              <option value="">All</option>
              <option value="VALID">VALID</option>
              <option value="UNIT_UNRESOLVED">UNIT_UNRESOLVED</option>
              <option value="REFERENCE_NOT_FOUND">REFERENCE_NOT_FOUND</option>
              <option value="NETWORK_UNVERIFIED">NETWORK_UNVERIFIED</option>
            </select>
          </label>
        </div>
        <p className="muted">
          Showing {count(results.length)} of {count(resultCount)} filtered result rows.
          Download the results CSV for the complete export.
        </p>
        {results.length ? (
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>HCPCS / Drug</th>
                  <th>Site NPI</th>
                  <th>Quarter</th>
                  <th>Setting</th>
                  <th>Units</th>
                  <th>Allowed total</th>
                  <th>Paid total</th>
                  <th>Allowed / unit</th>
                  <th>Paid / unit</th>
                  <th>ASP limit / unit</th>
                  <th>Allowed × ASP</th>
                  <th>Paid × ASP</th>
                  <th>Hospital ref / unit</th>
                  <th>Network</th>
                  <th>Quality</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {results.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="hcpcs-badge">{row.hcpcs_code}</span>
                      <small className="plan-audit-row-notes">{row.drug_description || "Description unavailable"}</small>
                    </td>
                    <td>{row.site_npi}</td>
                    <td>{row.quarter}</td>
                    <td>{row.service_setting}</td>
                    <td>{count(row.total_units)}</td>
                    <td>{money(row.total_allowed_amount)}</td>
                    <td>{money(row.total_paid_amount)}</td>
                    <td>{money(row.plan_allowed_price_per_unit)}</td>
                    <td>{money(row.plan_paid_price_per_unit)}</td>
                    <td>{money(row.asp_payment_limit)}</td>
                    <td>{benchmarkMultiple(row.allowed_markup_multiple)}</td>
                    <td>{benchmarkMultiple(row.paid_markup_multiple)}</td>
                    <td>
                      {row.hospital_price_per_unit != null ? (
                        <>
                          {money(row.hospital_price_per_unit)}
                          <small className="plan-audit-row-notes"> (ref; not plan rate)</small>
                        </>
                      ) : "—"}
                    </td>
                    <td>{row.network_status}</td>
                    <td>
                      <QualityBadge status={row.data_quality_status} />
                      {row.data_quality_notes?.length > 0 && (
                        <small className="plan-audit-row-notes">{row.data_quality_notes.join(", ")}</small>
                      )}
                    </td>
                    <td>
                      <details>
                        <summary>View source</summary>
                        <dl className="plan-audit-evidence">
                          {Object.entries(row.source_references || {}).map(([key, value]) =>
                            value != null && (
                              <React.Fragment key={key}>
                                <dt>{key.replace(/_/g, " ")}</dt>
                                <dd>{String(value)}</dd>
                              </React.Fragment>
                            )
                          )}
                        </dl>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            message="No result rows match the current filters."
            sub="Run the audit or clear the filters to see drug cost results."
          />
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Provider & Network Analysis
// ---------------------------------------------------------------------------
function ProviderNetworkSection({ auditId, audit }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows([]);
    setTotal(0);
    setNextOffset(null);
    setError("");
    if (!auditId) return undefined;
    let alive = true;
    getJSON(`plan-audits/${auditId}/network-validation/`, { limit: 200, offset: 0 })
      .then((data) => {
        if (!alive) return;
        setRows(data.results || []);
        setTotal(data.count || 0);
        setNextOffset(data.next_offset);
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [auditId]);

  async function loadMore() {
    if (nextOffset == null) return;
    setLoadingMore(true); setError("");
    try {
      const data = await getJSON(`plan-audits/${auditId}/network-validation/`, { limit: 200, offset: nextOffset });
      setRows((current) => [...current, ...(data.results || [])]);
      setNextOffset(data.next_offset);
    } catch (e) { setError(e.message); }
    finally { setLoadingMore(false); }
  }

  if (!audit) return <EmptyState message="Select a completed audit to view provider and network analysis." />;

  // Group by site NPI
  const bySite = {};
  for (const row of rows) {
    if (!bySite[row.site_npi]) {
      bySite[row.site_npi] = { statuses: new Set(), hcpcs: new Set(), quarters: new Set() };
    }
    bySite[row.site_npi].statuses.add(row.data_network_status);
    bySite[row.site_npi].hcpcs.add(row.hcpcs_code);
    bySite[row.site_npi].quarters.add(row.quarter);
  }

  return (
    <div>
      <section className="dashboard-panel">
        <h3 className="panel-title">Provider and network analysis</h3>
        <p className="panel-subtitle muted">
          Network status is derived solely from the uploaded plan roster. An NPI is in-network only when
          a roster interval covers the full reporting quarter. No status is inferred from facility names.
        </p>
        <ErrorBox error={error} />
        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>Site NPI</th>
                  <th>HCPCS codes</th>
                  <th>Quarters</th>
                  <th>Network status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(bySite).sort(([a], [b]) => a.localeCompare(b)).map(([npi, data]) => (
                  <tr key={npi}>
                    <td>{npi}</td>
                    <td>{[...data.hcpcs].sort().join(", ")}</td>
                    <td>{[...data.quarters].sort().join(", ")}</td>
                    <td>{[...data.statuses].join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            message="No network validation data available."
            sub="Import a plan network roster and run the audit to see provider network status."
          />
        )}
        {rows.length > 0 && <div className="table-footer-links"><span>Showing {rows.length.toLocaleString()} of {total.toLocaleString()} result rows</span>
          {nextOffset != null && <button type="button" className="button secondary" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : "Load more"}</button>}
        </div>}
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Unknown or expired network evidence is shown as-is.
          Provider names shown here, if any, are from the roster file and are not independently verified.
        </p>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Savings Opportunities
// ---------------------------------------------------------------------------
function SavingsSection({ auditId, audit }) {
  const [savings, setSavings] = useState([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSavings([]);
    setTotal(0);
    setNextOffset(null);
    setError("");
    if (!auditId) return undefined;
    let alive = true;
    getJSON(`plan-audits/${auditId}/savings/`, { limit: 200, offset: 0 })
      .then((data) => {
        if (!alive) return;
        setSavings(data.results || []);
        setTotal(data.count || 0);
        setNextOffset(data.next_offset);
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [auditId]);

  async function loadMore() {
    if (nextOffset == null) return;
    setLoadingMore(true); setError("");
    try {
      const data = await getJSON(`plan-audits/${auditId}/savings/`, { limit: 200, offset: nextOffset });
      setSavings((current) => [...current, ...(data.results || [])]);
      setNextOffset(data.next_offset);
    } catch (e) { setError(e.message); }
    finally { setLoadingMore(false); }
  }

  if (!audit) return <EmptyState message="Select a completed audit to view savings opportunities." />;

  return (
    <div>
      <section className="dashboard-panel">
        <h3 className="panel-title">Savings opportunities</h3>
        <p className="panel-subtitle muted">
          Evidence-backed price differences observed between sites for the same HCPCS, quarter, service setting,
          and billing unit. Alternatives are limited to sites with verified full-quarter in-network roster coverage.
          These figures are <strong>potential opportunities for review, not guaranteed or recoverable overpayments.</strong>
          Clinical and feasibility review remain pending for all items below.
        </p>
        <ErrorBox error={error} />
        {savings.length ? (
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>HCPCS</th>
                  <th>Quarter</th>
                  <th>Setting</th>
                  <th>Current site</th>
                  <th>Alternative site</th>
                  <th>Current allowed / unit</th>
                  <th>Alternative / unit</th>
                  <th>Units</th>
                  <th>Potential allowed savings</th>
                  <th>Potential paid difference</th>
                  <th>Network (alternative)</th>
                  <th>Clinical review</th>
                  <th>Validation</th>
                </tr>
              </thead>
              <tbody>
                {savings.map((row) => (
                  <tr key={row.id}>
                    <td>{row.hcpcs_code}</td>
                    <td>{row.quarter}</td>
                    <td>{row.service_setting || "—"}</td>
                    <td>{row.current_site_npi}</td>
                    <td>{row.alternative_site_npi}</td>
                    <td>{money(row.current_allowed_price_per_unit)}</td>
                    <td>{money(row.alternative_allowed_price_per_unit)}</td>
                    <td>{count(row.units)}</td>
                    <td>{money(row.potential_allowed_savings)}</td>
                    <td>{row.potential_paid_difference != null ? money(row.potential_paid_difference) : "Not available"}</td>
                    <td>{row.network_status}</td>
                    <td>{row.clinical_review_status}</td>
                    <td>{row.validation_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            message="No savings opportunities identified."
            sub="Opportunities require: validated billing units, a lower-priced in-network alternative for the same HCPCS and quarter, and verified full-quarter roster coverage for the alternative site."
          />
        )}
        {savings.length > 0 && <div className="table-footer-links"><span>Showing {savings.length.toLocaleString()} of {total.toLocaleString()} opportunities</span>
          {nextOffset != null && <button type="button" className="button secondary" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : "Load more"}</button>}
        </div>}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Audit Review and Reports
// ---------------------------------------------------------------------------
function ReviewReportsSection({ auditId, audit, reviews, quality, reviewer, analyst, admin, user, busy, onRefresh }) {
  const [reviewComment, setReviewComment] = useState("");
  const [localError, setLocalError] = useState("");
  const [localNotice, setLocalNotice] = useState("");
  const [localBusy, setLocalBusy] = useState(false);

  async function act(action, success) {
    setLocalBusy(true); setLocalError(""); setLocalNotice("");
    try { await action(); setLocalNotice(success); onRefresh(); }
    catch (e) { setLocalError(e.message); }
    finally { setLocalBusy(false); }
  }

  const canAct = !busy && !localBusy && ["completed", "needs_review"].includes(audit?.status)
    && Boolean(audit?.result_fingerprint);
  const reviewBinding = { version: audit?.current_version, result_fingerprint: audit?.result_fingerprint };
  const currentUserId = user?.id == null ? "" : String(user.id);
  const contributorIds = [audit?.created_by_id, audit?.run_initiated_by_id,
    ...(audit?.artifact_builders || []).map((builder) => builder.id)];
  const isCreatorOrRunner = Boolean(currentUserId && [audit?.created_by_id, audit?.run_initiated_by_id]
    .some((id) => id != null && String(id) === currentUserId));
  const isArtifactBuilder = Boolean(currentUserId && (audit?.artifact_builders || [])
    .some((builder) => builder.id != null && String(builder.id) === currentUserId));
  const contributorIdentityMissing = !audit?.created_by_id || !audit?.run_initiated_by_id
    || audit?.artifact_builders?.length !== 2 || audit.artifact_builders.some((builder) => builder.id == null);
  const currentUserContributed = Boolean(currentUserId && contributorIds
    .some((id) => id != null && String(id) === currentUserId));
  const latestDecision = reviews.find((item) => ["approved", "rejected"].includes(item.review_status))
    || (audit?.latest_publication_decision ? {
      review_status: audit.latest_publication_decision.status,
      reviewer: audit.latest_publication_decision.reviewer,
      reviewed_at: audit.latest_publication_decision.reviewed_at,
      comments: audit.latest_publication_decision.reason,
    } : null);
  const publicationLabel = audit?.publication_status === "published" ? "Published" :
    audit?.publication_status === "rejected" ? "Rejected — publication revoked" :
      audit?.publication_status === "revoked" ? "Revoked — publication suspended" :
        audit?.publication_status === "failed" || audit?.calculation_status === "failed" ? "Failed — not publishable" :
          audit?.calculation_status === "running" ? "Running" :
            audit?.calculation_status === "completed" ? "Pending Approval" : audit?.calculation_status || "Not started";

  return (
    <div>
      {localError && <ErrorBox error={localError} />}
      {localNotice && <div className="plan-audit-notice" role="status">{localNotice}</div>}

      {/* Report generation and exports */}
      {audit && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Report actions</h3>
          <p className="muted" role="status">
            Run v{audit.current_version || 0}: {publicationLabel}
          </p>
          {(reviewer || analyst || admin) && (
            <div className="muted">
              <p>Audit creator: {audit.created_by || "Unknown"}; run initiator: {audit.run_initiated_by || "Unknown"}.</p>
              <p>Report builders: {(audit.artifact_builders || []).map((builder) => builder.username || "Unknown").join(", ") || "Unknown"}.</p>
            </div>
          )}
          {latestDecision && (
            <p className="muted" role="status">
              Latest decision: {latestDecision.review_status} by {latestDecision.reviewer || "Reviewer"}
              {latestDecision.reviewed_at ? ` on ${latestDecision.reviewed_at}` : ""}
              {latestDecision.comments ? ` — ${latestDecision.comments}` : ""}
            </p>
          )}
          {!audit.can_view_results && !analyst && !reviewer && (
            <p className="muted">
              {audit.publication_status === "rejected"
                ? "A reviewer rejected this run and revoked publication. Results remain unavailable until a new run is approved."
                : audit.publication_status === "failed"
                  ? "This calculation failed and cannot be published. Results and downloads are unavailable."
                  : "Updated report pending independent review. Results and downloads are unavailable until approval."}
            </p>
          )}
          <div className="plan-audit-actions">
            {analyst && (
              <button
                type="button"
                className="secondary"
                disabled={!canAct || audit.publication_status === "rejected" || audit.publication_status === "failed"}
                onClick={() => act(async () => {
                  await postJSON(`plan-audits/${auditId}/generate-report/`);
                  await downloadFile(`plan-audits/${auditId}/report/`, `plan-audit-${auditId}.pdf`);
                }, "PDF report generated.")}
              >
                Generate and download PDF
              </button>
            )}
            {audit.can_download_report && (
              <button
                type="button"
                className="secondary"
                disabled={busy || localBusy}
                onClick={() => act(
                  () => downloadFile(`plan-audits/${auditId}/report/`, `plan-audit-${auditId}.pdf`),
                  "Approved PDF downloaded."
                )}
              >
                Download approved PDF
              </button>
            )}
            <button
              type="button"
              className="secondary"
              disabled={busy || localBusy || !audit.can_download_csv}
              onClick={() => act(
                () => downloadFile(`plan-audits/${auditId}/export-csv/`, `plan-audit-${auditId}.csv`),
                "Results CSV downloaded."
              )}
            >
              Download results CSV
            </button>
          </div>
          {audit.report_generated_at && (
            <p className="muted">Last report generated: {audit.report_generated_at}</p>
          )}
          <p className="muted">
            Client accounts can access only audits with an approved review and a generated report.
          </p>
        </section>
      )}

      {/* Data quality summary */}
      {quality && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Data quality and evidence limits</h3>
          <div className="plan-audit-quality">
            {(quality.notes || []).map((note) => <p key={note}>• {note}</p>)}
            {quality.benchmark_availability && (
              <>
                <p>
                  <b>Medicare ASP benchmark:</b> {count(quality.benchmark_availability.asp_available)} available;{" "}
                  {count(quality.benchmark_availability.asp_unavailable)} unavailable.
                </p>
                <p>
                  <b>Hospital price reference (not a plan contract rate):</b>{" "}
                  {count(quality.benchmark_availability.hospital_reference_available)} available;{" "}
                  {count(quality.benchmark_availability.hospital_reference_unavailable)} unavailable.
                </p>
              </>
            )}
            {quality.result_status_counts &&
              Object.entries(quality.result_status_counts).map(([name, value]) => (
                <p key={name}><b>{name}:</b> {count(value)} result rows</p>
              ))}
          </div>
        </section>
      )}

      {/* Review history */}
      <section className="dashboard-panel">
        <h3 className="panel-title">Review history</h3>
        {reviews.length ? (
          <ul className="plan-audit-access-list">
            {reviews.map((item) => (
              <li key={item.id}>
                <span>
                  <b>{item.reviewer || "Reviewer"}:</b> {item.review_status} {item.comments}
                </span>
                <small>{item.reviewed_at}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No review submitted yet.</p>
        )}
        {reviewer && audit && (
          <form
            className="plan-audit-form"
            onSubmit={(e) => {
              e.preventDefault();
              act(
                () => postJSON(`plan-audits/${auditId}/review/`, { comments: reviewComment, ...reviewBinding }),
                "Review comment submitted."
              );
            }}
          >
            <Field
              label="Review comment or decision reason"
              value={reviewComment}
              maxLength="2000"
              onChange={(e) => setReviewComment(e.target.value)}
            />
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button disabled={!canAct}>Add review comment</button>
              <button
                type="button"
                disabled={!canAct || audit.publication_status !== "pending"
                  || currentUserContributed || contributorIdentityMissing}
                onClick={() => act(
                  () => postJSON(`plan-audits/${auditId}/approve/`, { comments: reviewComment, ...reviewBinding }),
                  "Audit approved."
                )}
              >
                Approve audit
              </button>
              <button
                type="button"
                className="secondary"
                disabled={!canAct || !reviewComment.trim() || !["pending", "published"].includes(audit.publication_status)}
                onClick={() => act(
                  () => postJSON(`plan-audits/${auditId}/reject/`, { comments: reviewComment, ...reviewBinding }),
                  "Audit rejected."
                )}
              >
                Reject audit
              </button>
            </div>
            {isCreatorOrRunner && (
              <p className="muted" role="note">
                You cannot approve an audit that you created or ran. An independent reviewer must approve this version.
              </p>
            )}
            {!isCreatorOrRunner && isArtifactBuilder && (
              <p className="muted" role="note">You cannot approve report artifacts that you generated. An independent reviewer must approve this version.</p>
            )}
            {contributorIdentityMissing && (
              <p className="muted" role="note">Approval is disabled because creator, run initiator, or report builder identity is unavailable.</p>
            )}
            <p className="muted">
              Only Reviewers and Super Admins may approve or reject. Review records are permanent and append-only.
            </p>
          </form>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Plan Setup (Admin / Analyst only)
// ---------------------------------------------------------------------------
function PlanSetupSection({
  admin, analyst, busy, onRefresh, refreshKey,
  organizations, plans, imports,
  organizationId, setOrganizationId,
  planId, setPlanId,
  importId, setImportId,
  auditId, setAuditId,
  selectedImport, networkEvidence,
  accessRows, viewerUsers,
  rosterImportResult, setRosterImportResult,
  summaryPreview, setSummaryPreview,
  previewError, setPreviewError,
  previewBusy, setPreviewBusy,
  error, setError, setErrorDetails, setNotice, setBusy,
}) {
  const [managementPlans, setManagementPlans] = useState([]);
  useEffect(() => {
    if (!admin) { setManagementPlans([]); return undefined; }
    let alive = true;
    getJSON("plans/").then((items) => alive && setManagementPlans(items))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [admin, refreshKey]);
  const assignedUserIds = new Set(accessRows.map((row) => String(row.user_id)));
  const acceptedImports = imports.filter((item) => item.import_status === "accepted");
  const assignableUsers = viewerUsers.filter((item) => !assignedUserIds.has(String(item.id)));
  const roleLabels = { ANALYST: "Analyst", REVIEWER: "Reviewer", CLIENT: "Client", Viewer: "Legacy Viewer" };
  async function act(action, success) {
    setBusy(true); setError(""); setErrorDetails(null); setNotice("");
    try { await action(); setNotice(success); onRefresh(); }
    catch (e) {
      setError(e.message);
      setErrorDetails(e.payload?.validation_summary || e.payload?.errors || null);
      if (e.payload?.import_id) onRefresh();
    }
    finally { setBusy(false); }
  }

  async function previewSummary(event) {
    event.preventDefault();
    const form = event.currentTarget.form || event.currentTarget.closest("form");
    const summaryFile = form?.elements?.summary?.files?.[0];
    const manifestFile = form?.elements?.manifest?.files?.[0];
    setPreviewBusy(true); setPreviewError(""); setSummaryPreview(null);
    try {
      const currentPlan = plans.find((item) => String(item.id) === String(planId));
      const preview = await inspectAggregateFiles(summaryFile, manifestFile, currentPlan?.plan_reference);
      setSummaryPreview({ ...preview, summaryFile, manifestFile });
    } catch (e) {
      setPreviewError(e.message);
    } finally { setPreviewBusy(false); }
  }

  if (!analyst) {
    return (
      <EmptyState
        message="Plan setup is restricted to Analysts and Admins."
        sub="Contact a Super Admin to request access."
      />
    );
  }

  return (
    <div className="plan-audit-admin-grid">
      {admin && (
        <>
          <section className="dashboard-panel">
            <h3 className="panel-title">Organization Management</h3>
            {organizations.length ? (
              <div className="table-wrap"><table className="executive-table">
                <thead><tr><th>Organization</th><th>Type</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>{organizations.map((organization) => {
                  const nextStatus = organization.status === "active" ? "inactive" : "active";
                  const effect = nextStatus === "inactive"
                    ? "Users assigned to this organization will lose ordinary access to its plans, imports, and audits, including the ability to run or review audits. Existing records and reports will be retained."
                    : "Assigned users will regain access to active plans according to their roles and existing publication permissions.";
                  return <tr key={organization.id}>
                    <td>{organization.organization_name}</td><td>{organization.organization_type}</td>
                    <td>{organization.status}</td><td><button type="button" disabled={busy}
                      onClick={() => {
                        if (!window.confirm(`${nextStatus === "active" ? "Activate" : "Deactivate"} ${organization.organization_name}? ${effect}`)) return;
                        act(() => patchJSON(`organizations/${organization.id}/status/`, { status: nextStatus }),
                          `Organization ${nextStatus}.`);
                      }}>{nextStatus === "active" ? "Activate" : "Deactivate"}</button></td>
                  </tr>;
                })}</tbody>
              </table></div>
            ) : <p className="muted">No organizations are available.</p>}
          </section>

          <section className="dashboard-panel">
            <h3 className="panel-title">Plan Management</h3>
            {managementPlans.length ? (
              <div className="table-wrap"><table className="executive-table">
                <thead><tr><th>Plan</th><th>Reference</th><th>Organization</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>{managementPlans.map((plan) => {
                  const nextStatus = plan.status === "active" ? "inactive" : "active";
                  const effect = nextStatus === "inactive"
                    ? "Ordinary users will lose access to this plan's imports and audits, including the ability to run or review audits. Existing records and reports will be retained."
                    : "Assigned users will regain access, subject to their organization status, roles, and publication permissions.";
                  return <tr key={plan.id}>
                    <td>{plan.plan_name}</td><td>{plan.plan_reference}</td>
                    <td>{plan.organization_name}</td><td>{plan.status}</td>
                    <td><button type="button" disabled={busy}
                      onClick={() => {
                        if (!window.confirm(`${nextStatus === "active" ? "Activate" : "Deactivate"} ${plan.plan_name}? ${effect}`)) return;
                        act(() => patchJSON(`plans/${plan.id}/`, { status: nextStatus }), `Plan ${nextStatus}.`);
                      }}>{nextStatus === "active" ? "Activate" : "Deactivate"}</button></td>
                  </tr>;
                })}</tbody>
              </table></div>
            ) : <p className="muted">No plans are available.</p>}
          </section>
          <section className="dashboard-panel">
            <h3 className="panel-title">Create an organization</h3>
            <form
              className="plan-audit-form"
              onSubmit={(e) => {
                e.preventDefault();
                const element = e.currentTarget;
                const form = new FormData(element);
                act(async () => {
                  await postJSON("organizations/", {
                    organization_name: form.get("organization_name"),
                    organization_type: form.get("organization_type"),
                  });
                  element.reset();
                }, "Organization created.");
              }}
            >
              <Field name="organization_name" label="Organization name" maxLength="200" required />
              <label className="plan-audit-field">
                Organization type
                <select name="organization_type" required>
                  <option value="employer">Employer</option>
                  <option value="tpa">TPA</option>
                </select>
              </label>
              <button disabled={busy}>Create organization</button>
            </form>
          </section>

          <section className="dashboard-panel">
            <h3 className="panel-title">Create a plan</h3>
            {!organizationId ? (
              <p className="muted">Create or select an organization first.</p>
            ) : (
              <form
                className="plan-audit-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const element = e.currentTarget;
                  const form = new FormData(element);
                  act(async () => {
                    await postJSON("plans/", {
                      organization_id: organizationId,
                      plan_name: form.get("plan_name"),
                      payer_reference: form.get("payer_reference"),
                      plan_reference: form.get("plan_reference"),
                      effective_start: form.get("effective_start") || null,
                      effective_end: form.get("effective_end") || null,
                    });
                    element.reset();
                  }, "Plan created.");
                }}
              >
                <Field name="plan_name" label="Plan name" maxLength="200" required />
                <Field name="plan_reference" label="Unique plan reference" maxLength="120" required />
                <Field name="payer_reference" label="Payer reference (optional)" maxLength="120" />
                <Field name="effective_start" label="Effective start (optional)" type="date" />
                <Field name="effective_end" label="Effective end (optional)" type="date" />
                <button disabled={busy}>Create plan</button>
              </form>
            )}
          </section>
        </>
      )}

      {/* Import approved aggregates */}
      <section className="dashboard-panel">
        <h3 className="panel-title">Import approved aggregates</h3>
        {!planId ? (
          <p className="muted">Select or create a plan first.</p>
        ) : (
          <form
            className="plan-audit-form"
            onSubmit={(e) => {
              e.preventDefault();
              const element = e.currentTarget;
              const form = new FormData(element);
              if (!summaryPreview || form.get("summary") !== summaryPreview.summaryFile
                  || form.get("manifest") !== summaryPreview.manifestFile) {
                setPreviewError("Preview the currently selected aggregate CSV and manifest before importing.");
                return;
              }
              act(async () => {
                const imported = await uploadPlanSummary(organizationId, planId, form.get("summary"), form.get("manifest"));
                if (imported?.id) setImportId(String(imported.id));
                element.reset(); setSummaryPreview(null);
              }, "Approved aggregate summary imported.");
            }}
          >
            <label className="plan-audit-field">
              Claims summary CSV
              <input
                name="summary"
                type="file"
                accept=".csv,text/csv"
                required
                onChange={() => { setSummaryPreview(null); setPreviewError(""); }}
              />
            </label>
            <label className="plan-audit-field">
              Matching manifest JSON
              <input
                name="manifest"
                type="file"
                accept=".json,application/json"
                required
                onChange={() => { setSummaryPreview(null); setPreviewError(""); }}
              />
            </label>
            <p className="muted">
              Upload only the local extractor claims summary and manifest files.
              Raw claims must stay in the client environment.
            </p>
            <button
              type="button"
              disabled={busy || previewBusy}
              onClick={previewSummary}
            >
              {previewBusy ? "Checking files…" : "Preview validation"}
            </button>
            {previewError && <p className="data-quality-alert" role="alert">{previewError}</p>}
            {summaryPreview && (
              <div className="plan-audit-quality" role="status">
                <p>Privacy declarations and aggregate CSV SHA-256 verified locally.</p>
                <p>Source period: {summaryPreview.sourcePeriod}; aggregate rows: {count(summaryPreview.rowCount)}.</p>
                <p>Verification: <span className="pill s-ok">Verified</span> <code className="plan-audit-hash" title={summaryPreview.sourceHash}>{summaryPreview.sourceHash ? `${summaryPreview.sourceHash.slice(0, 8)}…${summaryPreview.sourceHash.slice(-6)}` : "Verified"}</code></p>
              </div>
            )}
            <button disabled={busy || !summaryPreview}>
              {busy ? "Importing…" : "Import approved aggregates"}
            </button>
          </form>
        )}
      </section>

      {/* Import network roster */}
      <section className="dashboard-panel">
        <h3 className="panel-title">Import plan network roster</h3>
        {!planId ? (
          <p className="muted">Select a plan first.</p>
        ) : (
          <>
            <form
              className="plan-audit-form"
              onSubmit={(e) => {
                e.preventDefault();
                const element = e.currentTarget;
                const form = new FormData(element);
                act(async () => {
                  const result = await uploadNetworkRoster(planId, form.get("roster"));
                  setRosterImportResult(result);
                  element.reset();
                }, "Network roster imported.");
              }}
            >
              <label className="plan-audit-field">
                Network roster CSV
                <input name="roster" type="file" accept=".csv,text/csv" required />
              </label>
              <p className="muted">
                Use the documented roster schema. Network status is accepted only when the source covers
                a full reporting quarter.
              </p>
              <button disabled={busy}>Validate and import roster</button>
            </form>
            {rosterImportResult && String(rosterImportResult.plan_id) === String(planId) && (
              <p className="muted" role="status">
                {count(rosterImportResult.accepted_rows)} roster rows accepted. Source file retained: no.
                Checksum: <code className="plan-audit-hash" title={rosterImportResult.sha256}>{rosterImportResult.sha256 ? `${rosterImportResult.sha256.slice(0, 8)}…${rosterImportResult.sha256.slice(-6)}` : "Verified"}</code>
              </p>
            )}
          </>
        )}
      </section>

      {/* Create audit */}
      <section className="dashboard-panel">
        <h3 className="panel-title">Create an audit</h3>
        {!selectedImport || selectedImport.import_status !== "accepted" ? (
          <p className="muted">Import an accepted summary for this plan first.</p>
        ) : (
          <form
            className="plan-audit-form"
            onSubmit={(e) => {
              e.preventDefault();
              const element = e.currentTarget;
              const form = new FormData(element);
              act(async () => {
                const item = await postJSON("plan-audits/create/", {
                  organization_id: organizationId,
                  plan_id: planId,
                  summary_import_id: form.get("summary_import_id") || selectedImport?.id || importId,
                  audit_name: form.get("audit_name"),
                  reporting_period: form.get("reporting_period"),
                });
                setAuditId(String(item.id));
                element.reset();
              }, "Plan audit created.");
            }}
          >
            {acceptedImports.length > 1 && (
              <label className="plan-audit-field">
                Summary import
                <select
                  name="summary_import_id"
                  value={importId}
                  onChange={(e) => setImportId(e.target.value)}
                  required
                >
                  {acceptedImports.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.source_file_name} ({item.source_period || "no period"}; {item.import_status})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <Field name="audit_name" label="Audit name" maxLength="200" required />
            <Field
              key={selectedImport.id}
              name="reporting_period"
              label="Source period"
              defaultValue={selectedImport.source_period}
              maxLength="64"
              required
            />
            <button disabled={busy}>Create audit</button>
          </form>
        )}
      </section>

      {/* Organization access (admin only) */}
      {admin && (
        <section className="dashboard-panel">
          <h3 className="panel-title">Organization access</h3>
          {!organizationId ? (
            <p className="muted">Select an organization first.</p>
          ) : (
            <>
              <form
                className="plan-audit-form plan-audit-form--inline"
                onSubmit={(e) => {
                  e.preventDefault();
                  const element = e.currentTarget;
                  const form = new FormData(element);
                  act(async () => {
                    await postJSON(`organizations/${organizationId}/users/`, { user_id: form.get("user_id") });
                    element.reset();
                  }, "Organization access granted.");
                }}
              >
                <label className="plan-audit-field">
                  Account
                  <select name="user_id" required defaultValue="">
                    <option value="">Select an active Analyst, Reviewer or Client</option>
                    {assignableUsers.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.display_name} ({item.username}; {(item.roles || [])
                          .filter((role) => roleLabels[role])
                          .map((role) => roleLabels[role]).join(", ")}; ID {item.id})
                      </option>
                    ))}
                  </select>
                </label>
                <button disabled={busy || assignableUsers.length === 0}>Grant access</button>
              </form>
              {accessRows.length ? (
                <ul className="plan-audit-access-list">
                  {accessRows.map((row) => (
                    <li key={row.user_id}>
                      <span>{row.display_name} <small>({row.username}, ID {row.user_id})</small></span>
                      <button
                        type="button"
                        className="button-subtle"
                        disabled={busy}
                        onClick={() => act(
                          () => deleteJSON(`organizations/${organizationId}/users/${row.user_id}/`),
                          "Organization access revoked."
                        )}
                      >
                        Revoke
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No viewers are assigned to this organization.</p>
              )}
            </>
          )}
        </section>
      )}

      {/* Import history */}
      {imports.length > 0 && (
        <section className="dashboard-panel" style={{ gridColumn: "1 / -1" }}>
          <h3 className="panel-title">Claims summary import history ({imports.length})</h3>
          <div className="table-wrap">
            <table className="executive-table">
              <thead>
                <tr>
                  <th>Source file</th>
                  <th>Status</th>
                  <th>Source period</th>
                  <th>Rows accepted</th>
                  <th>Rows rejected</th>
                  <th>Privacy validation</th>
                  <th>Aggregate SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {imports.map((item) => (
                  <tr key={item.id}>
                    <td>{item.source_file_name}</td>
                    <td>{item.import_status}</td>
                    <td>{item.source_period || "—"}</td>
                    <td>{count(item.validation_summary?.stored_rows)}</td>
                    <td>{count(item.validation_summary?.rejected_rows)}</td>
                    <td>
                      {item.validation_summary?.raw_claims_stored === false &&
                       item.validation_summary?.member_identifiers_stored === false
                        ? "Passed; no raw claims or member IDs stored"
                        : "Rejected or unavailable"}
                    </td>
                    <td><code className="plan-audit-hash" title={item.file_hash}>{item.file_hash ? `${item.file_hash.slice(0, 8)}…${item.file_hash.slice(-6)}` : "—"}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {networkEvidence && (
            <div style={{ marginTop: "1rem" }}>
              <p className="muted">
                {count(networkEvidence.entry_count)} roster records available.
                Full-quarter coverage computed only for the selected accepted import.
              </p>
              {networkEvidence.quarter_coverage && (
                <div className="plan-audit-quality">
                  <p>{count(networkEvidence.quarter_coverage.site_quarters)} site-quarter groups checked.</p>
                  {Object.entries(networkEvidence.quarter_coverage.status_counts || {}).map(([status, value]) => (
                    <p key={status}><b>{status}:</b> {count(value)}</p>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
const TABS = [
  { id: "spending", label: "Historical Spending" },
  { id: "drug", label: "Drug Cost Analysis" },
  { id: "network", label: "Provider & Network" },
  { id: "savings", label: "Savings Opportunities" },
  { id: "review", label: "Review & Reports" },
  { id: "setup", label: "Plan Setup" },
];

function TabBar({ activeTab, onSelect, analyst }) {
  return (
    <div className="plan-audit-tabs" role="tablist">
      {TABS.map((tab) => {
        // Hide Setup tab from non-analysts
        if (tab.id === "setup" && !analyst) return null;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`plan-audit-tab${activeTab === tab.id ? " plan-audit-tab--active" : ""}`}
            onClick={() => onSelect(tab.id)}
            type="button"
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function PlanAudits({ user }) {
  const admin = isAdmin(user);
  const analyst = isAnalyst(user);
  const reviewer = isReviewer(user);

  // Workspace selectors
  const [organizations, setOrganizations] = useState([]);
  const [plans, setPlans] = useState([]);
  const [imports, setImports] = useState([]);
  const [audits, setAudits] = useState([]);
  const [organizationId, setOrganizationId] = useState("");
  const [planId, setPlanId] = useState("");
  const [importId, setImportId] = useState("");
  const [auditId, setAuditId] = useState("");

  // Audit data
  const [audit, setAudit] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [quality, setQuality] = useState(null);
  const [reviews, setReviews] = useState([]);

  // Setup state
  const [accessRows, setAccessRows] = useState([]);
  const [viewerUsers, setViewerUsers] = useState([]);
  const [networkEvidence, setNetworkEvidence] = useState(null);
  const [rosterImportResult, setRosterImportResult] = useState(null);
  const [summaryPreview, setSummaryPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);

  // Global status
  const [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // Active tab — default to "spending" for analysis focus
  const [activeTab, setActiveTab] = useState("spending");

  const refresh = useCallback(() => setRefreshKey((v) => v + 1), []);

  // Load organizations
  useEffect(() => {
    let alive = true;
    getJSON("organizations/")
      .then((items) => {
        if (!alive) return;
        setOrganizations(items);
        if (!items.some((item) => String(item.id) === String(organizationId))) {
          setOrganizationId(items.length ? String(items[0].id) : "");
        }
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [organizationId, refreshKey]);

  // Clear downstream state on org change
  useEffect(() => {
    setPlans([]); setPlanId(""); setImports([]); setImportId(""); setAudits([]); setAuditId("");
  }, [organizationId]);

  // Load plans
  useEffect(() => {
    if (!organizationId) { setPlans([]); setPlanId(""); return undefined; }
    let alive = true;
    getJSON("plans/", { organization_id: organizationId })
      .then((items) => {
        if (!alive) return;
        setPlans(items);
        if (!items.length) setPlanId("");
        else if (!items.some((item) => String(item.id) === String(planId))) {
          setPlanId(String(items[0].id));
        }
      })
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [organizationId, refreshKey, planId]);

  // Clear imports/audits on plan change
  useEffect(() => {
    setImports([]); setImportId(""); setAudits([]); setAuditId("");
    setSummaryPreview(null); setPreviewError("");
  }, [planId]);

  // Load imports and audits
  useEffect(() => {
    if (!planId) { setImports([]); setImportId(""); setAudits([]); setAuditId(""); return undefined; }
    let alive = true;
    Promise.all([
      analyst ? getAllPages("plan-audits/imports/", { plan_id: planId }) : Promise.resolve([]),
      getAllPages("plan-audits/", { plan_id: planId }),
    ]).then(([importItems, auditItems]) => {
      if (!alive) return;
      setImports(importItems); setAudits(auditItems);
      const selectableImports = importItems.filter((item) => item.import_status === "accepted");
      if (!selectableImports.some((item) => String(item.id) === String(importId))) {
        const preferred = selectableImports[0];
        setImportId(preferred ? String(preferred.id) : "");
      }
      if (!auditItems.some((item) => String(item.id) === String(auditId))) {
        setAuditId(auditItems.length ? String(auditItems[0].id) : "");
      }
    }).catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [planId, refreshKey, importId, auditId]);

  // Load audit detail, overview, quality, reviews
  useEffect(() => {
    setAudit(null); setMetrics(null); setQuality(null); setReviews([]);
    if (!auditId) return undefined;
    let alive = true;
    const base = `plan-audits/${auditId}/`;
    (async () => {
      try {
        const detail = await getJSON(base);
        if (!alive) return;
        setAudit(detail);
        if (!detail.can_view_results && !analyst && !reviewer) {
          setMetrics(null); setQuality(null); setReviews([]);
          return;
        }
        const [overview, qualityData, reviewRows] = await Promise.all([
          getJSON(`${base}overview/`), getJSON(`${base}quality/`), getJSON(`${base}review/`),
        ]);
        if (!alive) return;
        setMetrics(overview.metrics); setQuality(qualityData); setReviews(reviewRows);
      } catch (e) { if (alive) setError(e.message); }
    })();
    return () => { alive = false; };
  }, [auditId, refreshKey, analyst, reviewer]);

  // Load viewer users (admin only)
  useEffect(() => {
    if (!admin) return undefined;
    let alive = true;
    getJSON("user-accounts/")
      .then((items) => alive && setViewerUsers(
        items.filter((item) =>
          item.is_active &&
          item.roles?.some((role) => ["CLIENT", "ANALYST", "REVIEWER", "Viewer"].includes(role))
        )
      ))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [admin]);

  // Load org access (admin only)
  useEffect(() => {
    setAccessRows([]);
    if (!admin || !organizationId) return undefined;
    let alive = true;
    getJSON(`organizations/${organizationId}/users/`)
      .then((items) => alive && setAccessRows(items))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [admin, organizationId, refreshKey]);

  const acceptedImports = useMemo(
    () => imports.filter((item) => item.import_status === "accepted"),
    [imports]
  );
  const selectedImport = useMemo(
    () => acceptedImports.find((item) => String(item.id) === String(importId)) ||
      (!importId ? acceptedImports[0] : null),
    [acceptedImports, importId]
  );

  // Load network evidence
  useEffect(() => {
    setNetworkEvidence(null);
    if (!planId) return undefined;
    let alive = true;
    const params = selectedImport?.import_status === "accepted" &&
      String(selectedImport.plan_id) === String(planId)
        ? { summary_import_id: selectedImport.id }
        : undefined;
    getJSON(`plans/${planId}/network-roster/`, params)
      .then((data) => alive && setNetworkEvidence(data))
      .catch((e) => alive && setError(e.message));
    return () => { alive = false; };
  }, [planId, selectedImport?.id, selectedImport?.import_status, refreshKey]);

  return (
    <div className="page-stack plan-audits-page">
      {/* Page intro */}
      <section className="page-intro">
        <div>
          <p className="eyebrow">Employer and TPA workspace</p>
          <h2>Plan-specific infusion drug audits</h2>
          <p className="muted">
            Analyze approved claims aggregates against verified hospital prices, Medicare ASP, and plan network data.
          </p>
        </div>
      </section>

      {/* Global alerts */}
      <ErrorBox error={error} details={errorDetails} />
      {notice && <div className="plan-audit-notice" role="status">{notice}</div>}

      {/* Workspace selectors */}
      <section className="dashboard-panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">Audit workspace</h3>
            <p className="panel-subtitle">
              Client and Analyst access is limited to organizations explicitly assigned by a Super Admin.
            </p>
          </div>
          {/* Run audit button shown in header for quick access when an audit is selected */}
          {audit && analyst && (
            <div className="plan-audit-actions">
              <button
                type="button"
                disabled={busy || audit.status === "running"}
                onClick={async () => {
                  if (audit.publication_status === "published" &&
                      !window.confirm("Starting a new run immediately suspends the published results until the new version is independently approved. Continue?")) return;
                  setAudit((current) => current ? { ...current, status: "running", calculation_status: "running",
                    publication_status: "pending", can_view_results: false, can_download_report: false,
                    can_download_csv: false, summary: {}, result_fingerprint: null } : current);
                  setMetrics(null); setQuality(null); setReviews([]); refresh();
                  setBusy(true); setError(""); setErrorDetails(null); setNotice("");
                  try {
                    await postJSON(`plan-audits/${auditId}/run/`);
                    setNotice("Audit run finished. Generate its PDF and CSV, then request independent approval before client publication.");
                    refresh();
                  } catch (e) {
                    setError(e.message);
                    setErrorDetails(e.payload || null);
                  } finally { setBusy(false); }
                }}
              >
                {busy ? "Running…" : "Run audit"}
              </button>
            </div>
          )}
        </div>
        <div className="plan-audit-selectors">
          <label>
            Organization
            <select value={organizationId} onChange={(e) => setOrganizationId(e.target.value)}>
              <option value="">Select organization</option>
              {organizations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.organization_name} ({item.organization_type})
                </option>
              ))}
            </select>
          </label>
          <label>
            Plan
            <select value={planId} onChange={(e) => setPlanId(e.target.value)}>
              <option value="">Select plan</option>
              {plans.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.plan_name} · {item.plan_reference}
                </option>
              ))}
            </select>
          </label>
          <label>
            Audit
            <select value={auditId} onChange={(e) => setAuditId(e.target.value)}>
              <option value="">Select audit</option>
              {audits.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.audit_name} · {item.status}
                </option>
              ))}
            </select>
          </label>
        </div>
        {organizations.length === 0 && (
          <div className="empty-panel-state">
            No organization access is assigned to this account yet.
            {analyst && " An Admin must create an organization and grant access."}
          </div>
        )}
        {audit && metrics && (
          <div className="plan-audit-metrics" style={{ marginTop: "1rem" }}>
            <article><span>Allowed amount</span><strong>{money(metrics.visible_allowed_amount)}</strong></article>
            <article><span>Paid amount</span><strong>{money(metrics.visible_paid_amount)}</strong></article>
            <article><span>Drugs analyzed</span><strong>{count(metrics.drugs_analyzed)}</strong></article>
            <article><span>Sites in claims</span><strong>{count(metrics.sites_with_claims)}</strong></article>
            <article>
              <span>Potential savings</span>
              <strong>{metrics.potential_allowed_savings != null ? money(metrics.potential_allowed_savings) : "Not available"}</strong>
            </article>
            <article><span>Quality warnings</span><strong>{count(metrics.data_quality_warnings)}</strong></article>
          </div>
        )}
        {audit && (
          <p className="muted" style={{ marginTop: "0.5rem" }}>
            {audit.organization_name} · {audit.plan_name} · {audit.reporting_period} · <b>{audit.status}</b>
          </p>
        )}
      </section>

      {/* Tab navigation */}
      <TabBar activeTab={activeTab} onSelect={setActiveTab} analyst={analyst} />

      {/* Tab content */}
      {activeTab === "spending" && (
        <HistoricalSpendingSection auditId={auditId} audit={audit} metrics={metrics} />
      )}
      {activeTab === "drug" && (
        <DrugCostSection auditId={auditId} audit={audit} />
      )}
      {activeTab === "network" && (
        <ProviderNetworkSection auditId={auditId} audit={audit} />
      )}
      {activeTab === "savings" && (
        <SavingsSection auditId={auditId} audit={audit} />
      )}
      {activeTab === "review" && (
        <ReviewReportsSection
          auditId={auditId}
          audit={audit}
          reviews={reviews}
          quality={quality}
          reviewer={reviewer}
          analyst={analyst}
          admin={admin}
          user={user}
          busy={busy}
          onRefresh={refresh}
        />
      )}
      {activeTab === "setup" && analyst && (
        <PlanSetupSection
          admin={admin}
          analyst={analyst}
          busy={busy}
          onRefresh={refresh}
          refreshKey={refreshKey}
          organizations={organizations}
          plans={plans}
          imports={imports}
          organizationId={organizationId}
          setOrganizationId={setOrganizationId}
          planId={planId}
          setPlanId={setPlanId}
          importId={importId}
          setImportId={setImportId}
          auditId={auditId}
          setAuditId={setAuditId}
          selectedImport={selectedImport}
          networkEvidence={networkEvidence}
          accessRows={accessRows}
          viewerUsers={viewerUsers}
          rosterImportResult={rosterImportResult}
          setRosterImportResult={setRosterImportResult}
          summaryPreview={summaryPreview}
          setSummaryPreview={setSummaryPreview}
          previewError={previewError}
          setPreviewError={setPreviewError}
          previewBusy={previewBusy}
          setPreviewBusy={setPreviewBusy}
          error={error}
          setError={setError}
          setErrorDetails={setErrorDetails}
          setNotice={setNotice}
          setBusy={setBusy}
        />
      )}
    </div>
  );
}
