import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, MarkupBars, Table } from "../components.jsx";

export default function Overview({ user }) {
  const isAdmin = user?.roles?.includes("Admin");
  const meta = useApi("dashboard/summary");
  const drugs = useApi("medicare-part-b-drugs");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState("median_markup");
  const [sortDir, setSortDir] = useState("desc");

  if (!isAdmin && meta.error?.status === 403) {
    return <div className="overview-page">
      <header className="overview-header">
        <div className="header-titles">
          <p className="eyebrow">Viewer workspace</p>
          <h1 className="header-main-title">You are signed in</h1>
          <p className="header-subtitle">There is no released report available for Viewer access yet.</p>
        </div>
      </header>
      <section className="note" role="status">
        <h2>Report release is pending</h2>
        <p>Your Viewer account and password were accepted. An Admin must finish the external clinical unit reviews and have a different Admin release the current report before Viewer dashboards and comparisons become available.</p>
      </section>
    </div>;
  }

  const drugRows = drugs.data || [];
  const m = meta.data || {};
  const reviewRange = m.review_range || [];
  const missingAspRows = m.statuses?.find((row) => row.status === "missing_asp")?.n;

  // Table filtering and sorting
  const filteredRows = useMemo(() => {
    let rows = drugRows.slice();
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        r.name?.toLowerCase().includes(q) ||
        r.brand?.toLowerCase().includes(q) ||
        r.hcpcs?.toLowerCase().includes(q)
      );
    }
    rows.sort((a, b) => {
      let av = a[sortKey];
      let bv = b[sortKey];
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av > bv ? 1 : av < bv ? -1 : 0) * (sortDir === "asc" ? 1 : -1);
    });
    return rows;
  }, [drugRows, search, sortKey, sortDir]);

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  // Determine last successful refresh timestamp safely
  const refreshDate = m.generated_at ? new Date(m.generated_at).toLocaleDateString() : null;
  const refreshTime = m.generated_at?.slice(11, 16) ? `${m.generated_at.slice(11, 16)} UTC` : "";

  return (
    <div className="overview-page">
      {/* =========================================================================
          SECTION A: Compact Page Header
          ========================================================================= */}
      <header className="overview-header">
        <div className="header-titles">
          <p className="eyebrow">{isAdmin ? "Admin workspace" : "Viewer workspace"}</p>
          <h1 className="header-main-title">{isAdmin ? "Audit Operations Dashboard" : "Hospital Pricing Insights"}</h1>
          <p className="header-subtitle">
            {isAdmin
              ? "Monitor imports, data quality, and Ohio hospital pricing against Medicare Part B."
              : "Explore read-only Ohio hospital pricing comparisons against Medicare Part B benchmarks."}
          </p>
        </div>
        <div className="header-metadata">
          <div className="meta-badge">
            <span className="meta-label">Reporting Period:</span>
            <span className="meta-value">{m.reporting_period || "Not available in the comparison data"}</span>
          </div>
          <div className="meta-badge">
            <span className="meta-label">CMS Benchmark Quarter:</span>
            <span className="meta-value">
              {m.benchmark_quarters_used || m.latest_asp_quarter || "Not available"}
            </span>
          </div>
          {refreshDate && (
            <div className="meta-badge">
              <span className="meta-label">Last Data Refresh:</span>
              <span className="meta-value">{refreshDate} {refreshTime}</span>
            </div>
          )}
        </div>
      </header>

      <section className={`role-dashboard role-dashboard--${isAdmin ? "admin" : "viewer"}`} aria-label={`${isAdmin ? "Admin" : "Viewer"} dashboard actions`}>
        <div className="role-dashboard-copy">
          <span className="role-dashboard-label">{isAdmin ? "Operations and oversight" : "Read-only access"}</span>
          <h2>{isAdmin ? "Keep the audit data review-ready" : "Explore the available market evidence"}</h2>
          <p>{isAdmin
            ? "Manage source imports, resolve unit reviews, and inspect the audit trail."
            : "Browse hospitals, compare reported prices, and review the benchmark methodology."}</p>
        </div>
        <nav className="role-dashboard-links" aria-label="Dashboard shortcuts">
          {isAdmin ? <>
            <Link to="/data-sources">Manage imports</Link>
            <Link to="/drug-unit-validations">Review drug units</Link>
            <Link to="/hospital-file-quality">File quality</Link>
            <Link to="/audit-logs">Audit logs</Link>
          </> : <>
            <Link to="/hospital-drug-price-comparisons">Explore comparisons</Link>
            <Link to="/hospitals">Browse hospitals</Link>
            <Link to="/reports">View reports</Link>
            <Link to="/methodology">Methodology</Link>
          </>}
        </nav>
      </section>

      {isAdmin && m.data_is_archived_snapshot && <div className="snapshot-notice" role="status">
        This dashboard is using the saved Parquet snapshot. Its original CMS source ZIP is not available here, so the snapshot is shown as archived until sources are uploaded and imported again.
      </div>}

      {/* =========================================================================
          SECTION B: Exactly Four Primary KPI Cards
          ========================================================================= */}
      <Loading state={meta}>
        {(summary) => {
          const validRates = summary.headline_rates;
          const drugsCompared = summary.drugs_compared;
          const reviewNeeded = summary.comparisons_requiring_review;

          return (
            <section className="kpi-grid" aria-label={isAdmin ? "Admin operations summary" : "Market comparison summary"}>
              {isAdmin ? <>
                <article className="kpi-card">
                  <span className="kpi-label">Hospital MRF Files</span>
                  <strong className="kpi-value">{fmt.n(summary.hospital_file_count)}</strong>
                  <small className="kpi-definition">Files catalogued from the stored hospital data</small>
                  <div className="kpi-subtext">{fmt.n(summary.hospital_files_with_drug_rows)} contain selected-drug rows</div>
                </article>
                <article className="kpi-card warning">
                  <span className="kpi-label">Files with Parse Errors</span>
                  <strong className="kpi-value">{fmt.n(summary.hospital_files_with_errors)}</strong>
                  <small className="kpi-definition">Hospital price files with a recorded parser error</small>
                  <div className="kpi-subtext"><Link to="/hospital-file-quality">Open file quality</Link></div>
                </article>
                <article className="kpi-card warning">
                  <span className="kpi-label">Comparisons Requiring Review</span>
                  <strong className="kpi-value">{fmt.n(reviewNeeded)}</strong>
                  <small className="kpi-definition">Unresolved units, formulas, or configured outlier flags</small>
                  <div className="kpi-subtext"><Link to="/drug-unit-validations">Review flagged records</Link></div>
                </article>
                <article className="kpi-card highlight">
                  <span className="kpi-label">Validated Price Comparisons</span>
                  <strong className="kpi-value">{fmt.n(summary.validated_comparison_rates)}</strong>
                  <small className="kpi-definition">Eligible rates with a recorded unit review</small>
                  <div className="kpi-subtext">Of {fmt.n(validRates)} eligible rates</div>
                </article>
              </> : <>
                <article className="kpi-card highlight">
                  <span className="kpi-label">Hospitals with Valid Rates</span>
                  <strong className="kpi-value">{fmt.n(summary.hospitals_with_valid_rates ?? summary.hospitals_covered)}</strong>
                  <small className="kpi-definition">Hospitals with at least one eligible comparison</small>
                  <div className="kpi-subtext">Across {fmt.n(summary.systems)} hospital systems</div>
                </article>
                <article className="kpi-card">
                  <span className="kpi-label">Drugs Compared</span>
                  <strong className="kpi-value">{fmt.n(drugsCompared)}</strong>
                  <small className="kpi-definition">In-scope drugs with valid hospital pricing evidence</small>
                  <div className="kpi-subtext">Selected from CMS Part B spending data</div>
                </article>
                <article className="kpi-card highlight">
                  <span className="kpi-label">Valid Price Comparisons</span>
                  <strong className="kpi-value">{fmt.n(validRates)}</strong>
                  <small className="kpi-definition">Eligible reported rates matched to an ASP benchmark</small>
                  <div className="kpi-subtext">Price per HCPCS billing unit</div>
                </article>
                <article className="kpi-card">
                  <span className="kpi-label">Benchmark Quarter</span>
                  <strong className="kpi-value kpi-value--text">{summary.benchmark_quarters_used || summary.latest_asp_quarter || "—"}</strong>
                  <small className="kpi-definition">CMS ASP period used by eligible comparisons</small>
                  <div className="kpi-subtext">Reporting period: {summary.reporting_period || "Unavailable"}</div>
                </article>
              </>}
            </section>
          );
        }}
      </Loading>

      {/* =========================================================================
          SECTION 6: Conditional Data-Quality Warning
          ========================================================================= */}
      {isAdmin && m.comparisons_requiring_review > 0 && (
        <div className="data-quality-alert" role="alert">
          <div className="alert-icon">⚠</div>
          <div className="alert-content">
            <div className="alert-title">
              Data Quality Notice: {fmt.n(m.comparisons_requiring_review)} Records Requiring Manual Review
            </div>
            <div className="alert-description">
              {fmt.n(m.review_breakdown?.unresolved_units)} rates have unresolved hospital dosage units, {fmt.n(m.review_breakdown?.outliers_review_range)} fall outside the configured {reviewRange[0] ?? "—"}×–{reviewRange[1] ?? "—"}× review range, and {fmt.n(m.review_breakdown?.algorithm_or_percent_charges)} use percentage-of-charge or formula terms. {fmt.n(missingAspRows)} rows lack an exact-quarter ASP benchmark. Rows without a usable unit or exact-quarter ASP benchmark are not priced.
            </div>
            <div className="alert-links">
              {isAdmin && <Link to="/drug-unit-validations" className="alert-link">
                Review Unit Conversions &rarr;
              </Link>}
              <Link to="/hospital-drug-price-comparisons?status=unit_unresolved" className="alert-link">
                {isAdmin ? "Inspect Quarantined Rows" : "View flagged comparison rows"} &rarr;
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          SECTION 4: Main Visualization — Median Hospital Markup by Drug
          ========================================================================= */}
      <section className="dashboard-panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Median Hospital Markup by Drug</h2>
            <p className="panel-subtitle">
              Median of eligible hospital-negotiated rates per HCPCS billing unit divided by the CMS Medicare payment limit. A 1.0× markup is parity with Medicare.
            </p>
          </div>
        </div>

        <Loading state={drugs}>
          {(rows) => {
            const validDrugs = rows.filter((r) => r.rates > 0 && r.median_markup != null);
            if (!validDrugs.length) {
              return (
                <div className="empty-panel-state">
                  No eligible hospital-to-Medicare comparisons available for the current scope.
                </div>
              );
            }
            return (
              <MarkupBars
                rows={validDrugs.map((r) => ({
                  ...r,
                  label: `${r.hcpcs} ${r.name}`,
                }))}
                labelKey="label"
                reviewRange={reviewRange}
              />
            );
          }}
        </Loading>
      </section>

      <section className="dashboard-panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Top drugs by estimated dollars at stake</h2>
            <p className="panel-subtitle">Exposure proxy = CMS Part B spend multiplied by the positive portion of the median posted hospital rate markup above the ASP payment limit. This is not projected savings or hospital profit.</p>
          </div>
        </div>
        <Loading state={drugs}>
          {(rows) => <Table
            rows={rows.filter((r) => r.estimated_dollars_at_stake_proxy != null)
              .sort((a, b) => b.estimated_dollars_at_stake_proxy - a.estimated_dollars_at_stake_proxy).slice(0, 5)}
            empty="CMS Part B spending or eligible released comparisons are unavailable."
            columns={[
              { key: "hcpcs", label: "HCPCS" }, { key: "name", label: "Drug" },
              { key: "median_markup", label: "Median markup", num: true, render: (r) => fmt.x(r.median_markup) },
              { key: "partb_spending_proxy", label: "Part B spend proxy", num: true, render: (r) => fmt.usd(r.partb_spending_proxy) },
              { key: "estimated_dollars_at_stake_proxy", label: "Estimated exposure", num: true, render: (r) => fmt.usd(r.estimated_dollars_at_stake_proxy) },
            ]}
          />}
        </Loading>
      </section>

      {/* =========================================================================
          SECTION 5: Main Table — Drug Price Comparison
          ========================================================================= */}
      <section className="dashboard-panel">
        <div className="panel-header table-actions">
          <div>
            <h2 className="panel-title">Drug Price Comparison Table</h2>
            <p className="panel-subtitle">
              Authoritative summary of in-scope specialty drugs evaluated against contemporary CMS ASP payment limits.
            </p>
          </div>
          <div className="table-search-bar">
            <input
              type="search"
              placeholder="Filter by drug, brand, or HCPCS…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Filter drugs table"
            />
          </div>
        </div>

        <Loading state={drugs}>
          {() => {
            if (!filteredRows.length) {
              return (
                <div className="empty-panel-state">
                  No matching drug comparisons found for "{search}".
                </div>
              );
            }

            return (
              <div className="table-wrap">
                <table className="executive-table">
                  <thead>
                    <tr>
                      <th onClick={() => handleSort("name")}>
                        Drug Name {sortKey === "name" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th onClick={() => handleSort("hcpcs")}>
                        HCPCS {sortKey === "hcpcs" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th className="num" onClick={() => handleSort("asp_payment_limit")}>
                        Medicare Limit / Unit {sortKey === "asp_payment_limit" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th className="num" onClick={() => handleSort("median_hospital_price")}>
                        Median Hospital Price / Unit {sortKey === "median_hospital_price" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th className="num" onClick={() => handleSort("median_markup")}>
                        Median Markup {sortKey === "median_markup" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th className="num" onClick={() => handleSort("hospitals_priced")}>
                        Hospitals {sortKey === "hospitals_priced" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th className="num" onClick={() => handleSort("rates")}>
                        Valid Observations {sortKey === "rates" && (sortDir === "asc" ? "▲" : "▼")}
                      </th>
                      <th>Data Quality Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((r) => {
                      const hasValidRates = r.rates > 0;
                      return (
                        <tr key={r.hcpcs}>
                          <td>
                            <div className="drug-cell-name">
                              <Link to={`/drugs/${r.hcpcs}`} className="drug-link">
                                {r.name}
                              </Link>
                              {r.brand && <span className="drug-cell-brand">{r.brand}</span>}
                            </div>
                          </td>
                          <td>
                            <code className="hcpcs-badge">{r.hcpcs}</code>
                          </td>
                          <td className="num">
                            {r.asp_payment_limit != null ? (
                              <div>
                                <span className="cell-money">{fmt.usd(r.asp_payment_limit)}</span>
                                <div className="cell-unit-sub">{r.billing_unit}</div>
                              </div>
                            ) : (
                              <span className="muted">Unavailable</span>
                            )}
                          </td>
                          <td className="num">
                            {r.median_hospital_price != null ? (
                              <div>
                                <span className="cell-money">{fmt.usd(r.median_hospital_price)}</span>
                                <div className="cell-unit-sub">per {r.billing_unit}</div>
                              </div>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                          <td className="num">
                            {hasValidRates && r.median_markup != null ? (
                              <span className={`markup-pill ${r.median_markup >= 3 ? "hot" : r.median_markup >= 2 ? "warm" : "cool"}`}>
                                {fmt.x(r.median_markup)}
                              </span>
                            ) : (
                              <span className="muted">No valid comparisons</span>
                            )}
                          </td>
                          <td className="num">
                            <b>{fmt.n(r.hospitals_priced)}</b>
                          </td>
                          <td className="num">
                            {fmt.n(r.rates)}
                          </td>
                          <td>
                            {isAdmin ? r.reviewed_by ? (
                              <span className="status-tag validated">✓ Clinical Review Passed</span>
                            ) : r.unresolved_unit_rows > 0 ? (
                              <span className="status-tag pending" title={`${r.unresolved_unit_rows} unresolved hospital units`}>
                                Provisional ({r.unresolved_unit_rows} unres.)
                              </span>
                            ) : (
                              <span className="status-tag ready">Pending clinical review</span>
                            ) : r.verification_status === "verified" ? (
                              <span className="status-tag validated">✓ Clinically reviewed</span>
                            ) : <span className="status-tag pending">Pending clinical review</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          }}
        </Loading>

        <div className="table-footer-links">
          <span>Showing {filteredRows.length} in-scope specialty drugs</span>
          <div className="footer-actions">
            <Link to="/hospital-drug-price-comparisons" className="button-subtle">
              View All {m.rows == null ? "—" : fmt.n(m.rows)} Detailed Price Records &rarr;
            </Link>
            {isAdmin && <Link to="/drug-selection-scope" className="button-subtle">
              View CMS Spending Ranking Evidence &rarr;
            </Link>}
          </div>
        </div>
      </section>
    </div>
  );
}
