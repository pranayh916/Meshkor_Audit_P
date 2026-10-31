import { Link, useParams } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, MarkupBars, Provisional, StatusPill, Table } from "../components.jsx";
import RatesTable from "./RatesTable.jsx";

export default function DrugDetail() {
  const { hcpcs } = useParams();
  const d = useApi(`medicare-part-b-drugs/${hcpcs}`, null, [hcpcs]);
  return (
    <Loading state={d}>
      {(drug) => (
        <>
          <section>
            <div className="crumb"><Link to="/drug-selection-scope">Drug Selection Scope</Link> / {drug.hcpcs}</div>
            <h1>{drug.hcpcs} · {drug.name} <span className="muted">{drug.brand}</span></h1>
            <p className="lede">HCPCS billing unit: <b>{drug.billing_unit}</b>. Every hospital
              rate is converted to this unit before it is compared.</p>
            <Provisional reviewed={!!drug.reviewed_by} />
            <div className="status-row">
              {drug.statuses.map((s) => (
                <span key={s.status}><StatusPill status={s.status} /> {fmt.n(s.n)}</span>
              ))}
            </div>
          </section>

          <div className="grid2">
            <section>
              <h2>Medicare benchmark by quarter</h2>
              <Table rows={drug.asp} columns={[
                { key: "quarter", label: "Quarter" },
                { key: "dosage_text", label: "Dosage" },
                { key: "payment_limit", label: "CMS ASP payment limit", num: true,
                  render: (r) => fmt.usd(r.payment_limit) },
              ]} />
            </section>
            <section>
              <h2>By payer group</h2>
              <Table rows={drug.payers} initialSort={{ key: "median_markup", dir: "desc" }}
                empty="No compared rates." columns={[
                  { key: "payer_group", label: "Payer group" },
                  { key: "hospitals", label: "Hospitals", num: true },
                  { key: "rates", label: "Rates", num: true },
                  { key: "median_markup", label: "Median", num: true,
                    render: (r) => <b>{fmt.x(r.median_markup)}</b> },
                  { key: "max_markup", label: "Range", num: true,
                    render: (r) => `${fmt.x(r.min_markup)} – ${fmt.x(r.max_markup)}` },
                ]} />
            </section>
          </div>

          <section>
            <h2>Hospitals ranked by median markup</h2>
            <MarkupBars rows={drug.hospitals} labelKey="hospital_label" />
            <Table rows={drug.hospitals} initialSort={{ key: "median_markup", dir: "desc" }}
              empty="No hospital has a compared rate for this drug." columns={[
                { key: "hospital_label", label: "Hospital",
                  render: (r) => <Link to={`/hospitals/${r.hospital_key}`}>{r.hospital_label}</Link> },
                { key: "system", label: "System" },
                { key: "payer_groups", label: "Payer groups", num: true },
                { key: "median_price_per_unit", label: "Median $ / unit", num: true,
                  render: (r) => fmt.usd(r.median_price_per_unit) },
                { key: "asp_payment_limit", label: "CMS ASP limit", num: true,
                  render: (r) => <>{fmt.usd(r.asp_payment_limit)}
                    <div className="muted">{r.benchmark_quarter}</div></> },
                { key: "median_markup", label: "Median", num: true,
                  render: (r) => <b>{fmt.x(r.median_markup)}</b> },
                { key: "max_markup", label: "Range", num: true,
                  render: (r) => `${fmt.x(r.min_markup)} – ${fmt.x(r.max_markup)}` },
              ]} />
          </section>

          <section>
            <h2>Every rate for {drug.hcpcs}</h2>
            <RatesTable fixed={{ hcpcs: drug.hcpcs }} />
          </section>
        </>
      )}
    </Loading>
  );
}
