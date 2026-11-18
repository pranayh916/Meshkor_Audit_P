import { useEffect, useState } from "react";
import { downloadFile, fmt, getAllPages, useApi } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function ClientPlanAudits() {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let active = true;
    setState({ data: null, error: null, loading: true });
    getAllPages("plan-audits")
      .then((data) => active && setState({ data, error: null, loading: false }))
      .catch((error) => active && setState({ data: null, error, loading: false }));
    return () => { active = false; };
  }, []);
  const approved = (state.data || []).filter((audit) => audit.can_view_results && audit.publication_status === "published");
  const [selectedId, setSelectedId] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState("");
  useEffect(() => {
    if (!approved.some((audit) => String(audit.id) === selectedId)) setSelectedId(approved[0] ? String(approved[0].id) : "");
  }, [approved.map((audit) => audit.id).join(","), selectedId]);
  const selected = approved.find((audit) => String(audit.id) === selectedId);
  const base = selected ? `plan-audits/${selected.id}/` : null;
  const overview = useApi(base ? `${base}overview` : null, null, [selected?.id]);
  const spending = useApi(base ? `${base}historical-spending` : null, null, [selected?.id]);
  const drugAnalysis = useApi(base ? `${base}drug-analysis` : null, null, [selected?.id]);
  const [hospitalComparison, setHospitalComparison] = useState({ data: null, error: null, loading: true });
  const quality = useApi(base ? `${base}quality` : null, null, [selected?.id]);
  const savings = useApi(base ? `${base}savings` : null, null, [selected?.id]);
  useEffect(() => {
    if (!selected) {
      setHospitalComparison({ data: null, error: null, loading: false });
      return undefined;
    }
    let active = true;
    setHospitalComparison({ data: null, error: null, loading: true });
    getAllPages(`plan-audits/${selected.id}/hospital-comparison`)
      .then((rows) => active && setHospitalComparison({ data: rows, error: null, loading: false }))
      .catch((error) => active && setHospitalComparison({ data: null, error, loading: false }));
    return () => { active = false; };
  }, [selected?.id]);
  const metrics = overview.data?.metrics || {};
  async function download(kind) {
    if (!selected) return;
    setDownloading(kind);
    setDownloadError("");
    try {
      const isPdf = kind === "pdf";
      await downloadFile(`plan-audits/${selected.id}/${isPdf ? "report" : "export-csv"}/`,
        `plan-audit-${selected.id}.${isPdf ? "pdf" : "csv"}`);
    } catch (error) {
      setDownloadError(error.message || "The approved report could not be downloaded.");
    } finally {
      setDownloading("");
    }
  }
  return <div className="page-stack">
    <section className="page-intro"><div><p className="eyebrow">Client workspace</p><h2>Approved plan reports</h2>
      <p className="muted">Published reports for organizations assigned to your account.</p></div></section>
    <Loading state={state}>{() => approved.length ? <>
      <section><h3>Published audits</h3><Table rows={approved} columns={[
        { key: "audit_name", label: "Audit" }, { key: "organization_name", label: "Organization" },
        { key: "plan_name", label: "Plan" }, { key: "reporting_period", label: "Reporting period" },
        { key: "publication_status", label: "Status", render: () => "Published" },
        { key: "id", label: "View", render: (row) => <button type="button" onClick={() => setSelectedId(String(row.id))} aria-pressed={String(row.id) === selectedId}>View summary</button> },
      ]} /></section>
      {selected && <section className="dashboard-panel"><h3>{selected.audit_name} · {selected.reporting_period}</h3>
        <Loading state={overview}>{() => <div className="plan-audit-metrics">
          <article><span>Historical allowed spend</span><strong>{fmt.usd(metrics.visible_allowed_amount)}</strong></article>
          <article><span>Historical paid spend</span><strong>{fmt.usd(metrics.visible_paid_amount)}</strong></article>
          <article><span>Drugs analyzed</span><strong>{fmt.n(metrics.drugs_analyzed)}</strong></article>
          <article><span>Sites in claims</span><strong>{fmt.n(metrics.sites_with_claims)}</strong></article>
          <article><span>Verified savings opportunities</span><strong>{metrics.potential_allowed_savings == null ? "—" : fmt.usd(metrics.potential_allowed_savings)}</strong></article>
        </div>}</Loading>
        <p className="muted">Published totals use approved, unsuppressed aggregate data. Savings are shown only after clinical and data validation.</p>
        <div className="role-dashboard-links">
          <button type="button" disabled={Boolean(downloading)} onClick={() => download("pdf")}>
            {downloading === "pdf" ? "Downloading PDF…" : "Download approved PDF"}
          </button>
          <button type="button" disabled={Boolean(downloading)} onClick={() => download("csv")}>
            {downloading === "csv" ? "Downloading CSV…" : "Download approved CSV"}
          </button>
        </div>
        {downloadError && <p className="note error" role="alert">{downloadError}</p>}
      </section>}
      {selected && <>
        <section className="dashboard-panel">
          <h3>Historical spending</h3>
          <Loading state={spending}>{(data) => !data?.available
            ? <p className="note">{data?.reason || "Historical spending is not available."}</p>
            : <>
              <p className="muted">Allowed and paid amounts from approved, unsuppressed aggregate rows.</p>
              <Table rows={data?.by_quarter || []} columns={[
                { key: "quarter", label: "Quarter" },
                { key: "total_allowed_amount", label: "Allowed", render: (row) => fmt.usd(row.total_allowed_amount) },
                { key: "total_paid_amount", label: "Paid", render: (row) => fmt.usd(row.total_paid_amount) },
                { key: "total_units", label: "Units", render: (row) => fmt.n(row.total_units) },
              ]} empty="No historical spending rows are available." />
              <h4>By drug</h4>
              <Table rows={data?.by_hcpcs || []} columns={[
                { key: "hcpcs_code", label: "HCPCS" }, { key: "drug_description", label: "Drug" },
                { key: "total_allowed_amount", label: "Allowed", render: (row) => fmt.usd(row.total_allowed_amount) },
                { key: "total_paid_amount", label: "Paid", render: (row) => fmt.usd(row.total_paid_amount) },
                { key: "allowed_per_unit", label: "Allowed per unit", render: (row) => fmt.usd(row.allowed_per_unit) },
                { key: "paid_per_unit", label: "Paid per unit", render: (row) => fmt.usd(row.paid_per_unit) },
              ]} />
            </>}
          </Loading>
        </section>

        <section className="dashboard-panel">
          <h3>Drug comparison</h3>
          <p className="muted">ASP markups use compatible, validated billing units. Excluded rows remain visible with their quality status.</p>
          <Loading state={drugAnalysis}>{(data) => <Table rows={data?.results || []} columns={[
            { key: "hcpcs_code", label: "HCPCS" },
            { key: "eligible_allowed_amount", label: "Comparable allowed", render: (row) => fmt.usd(row.eligible_allowed_amount) },
            { key: "allowed_markup_multiple", label: "Allowed / ASP", render: (row) => row.allowed_markup_multiple == null ? "Not comparable" : `${fmt.n(row.allowed_markup_multiple)}×` },
            { key: "eligible_paid_amount", label: "Comparable paid", render: (row) => fmt.usd(row.eligible_paid_amount) },
            { key: "paid_markup_multiple", label: "Paid / ASP", render: (row) => row.paid_markup_multiple == null ? "Not comparable" : `${fmt.n(row.paid_markup_multiple)}×` },
            { key: "excluded_row_count", label: "Excluded rows", num: true },
          ]} empty="No drug comparison rows are available." />}</Loading>
        </section>

        <section className="dashboard-panel">
          <h3>Hospital price comparison</h3>
          <p className="muted">Hospital-reported reference prices are not the plan&apos;s contracted rates.</p>
          <Loading state={hospitalComparison}>{(rows) => <Table rows={rows || []} columns={[
            { key: "hcpcs_code", label: "HCPCS" }, { key: "site_npi", label: "Site NPI" },
            { key: "quarter", label: "Quarter" }, { key: "service_setting", label: "Setting" },
            { key: "plan_allowed_price_per_unit", label: "Plan allowed / unit", render: (row) => fmt.usd(row.plan_allowed_price_per_unit) },
            { key: "hospital_reported_price_per_unit", label: "Hospital reference / unit", render: (row) => fmt.usd(row.hospital_reported_price_per_unit) },
            { key: "plan_to_hospital_price_multiple", label: "Plan / reference", render: (row) => row.plan_to_hospital_price_multiple == null ? "Not comparable" : `${fmt.n(row.plan_to_hospital_price_multiple)}×` },
            { key: "data_quality_status", label: "Data quality" },
          ]} empty="No hospital comparison rows are available." />}</Loading>
        </section>

        <section className="dashboard-panel">
          <h3>Data quality and savings</h3>
          <Loading state={quality}>{(data) => <>
            <div className="plan-audit-quality">
              {Object.entries(data?.result_status_counts || {}).map(([status, count]) => <p key={status}><b>{status}:</b> {fmt.n(count)} rows</p>)}
              {(data?.notes || []).map((note) => <p key={note}>{note}</p>)}
            </div>
            {data?.benchmark_availability && <p className="muted">
              ASP benchmark available for {fmt.n(data.benchmark_availability.asp_available)} of {fmt.n(data.benchmark_availability.result_rows)} rows; hospital reference available for {fmt.n(data.benchmark_availability.hospital_reference_available)}.
            </p>}
          </>}</Loading>
          <h4>Clinically reviewed savings opportunities</h4>
          <Loading state={savings}>{(data) => <Table rows={data?.results || []} columns={[
            { key: "hcpcs_code", label: "HCPCS" }, { key: "quarter", label: "Quarter" },
            { key: "current_site_npi", label: "Current site" }, { key: "alternative_site_npi", label: "Alternative site" },
            { key: "potential_allowed_savings", label: "Potential allowed savings", render: (row) => fmt.usd(row.potential_allowed_savings) },
          ]} empty="No savings opportunities have passed the required network, data, and clinical validation." />}</Loading>
        </section>
      </>}
    </> : <p className="note">No approved plan reports are currently assigned to your account.</p>}</Loading>
  </div>;
}
