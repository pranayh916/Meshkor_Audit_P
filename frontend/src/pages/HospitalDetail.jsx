import { Link, useParams } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, StatusPill, Table } from "../components.jsx";
import RatesTable from "./RatesTable.jsx";

export default function HospitalDetail({ user }) {
  const isAdmin = user?.roles?.includes("Admin");
  const { key } = useParams();
  const h = useApi(`hospitals/${key}`, null, [key]);
  return (
    <Loading state={h}>
      {(d) => (
        <>
          <section>
            <div className="crumb"><Link to="/hospitals">Hospitals</Link> / {d.hospital_label}</div>
            <h1>{d.hospital_label}</h1>
            <p className="lede">{d.system} · file dated {d.file_last_updated || "not stated"}</p>
            {d.locations && <p className="muted">{isAdmin ? "Locations on this file:" : "Locations:"} {d.locations}</p>}
            {isAdmin && d.file_status && <p className={d.file_error ? "note error" : "muted"}>
              File status: {d.file_status.replaceAll("_", " ")} · {d.items_scanned ?? 0} items scanned · {d.drug_rows ?? d.n_rows ?? 0} selected-drug rows
              {d.file_error ? ` · ${d.file_error}` : ""}
            </p>}
            {isAdmin && <p className="muted mono">{d.source_file}</p>}
            {isAdmin && <div className="status-row">
              {d.statuses.map((s) => (
                <span key={s.status}><StatusPill status={s.status} /> {fmt.n(s.n)}</span>
              ))}
            </div>}
          </section>
          <section>
            <h2>Drugs</h2>
            <Table rows={d.drugs} initialSort={{ key: "median_markup", dir: "desc" }}
              empty="No compared negotiated rates in this file." columns={[
                { key: "hcpcs", label: "HCPCS",
                  render: (r) => <Link to={`/drugs/${r.hcpcs}`}>{r.hcpcs}</Link> },
                { key: "drug_name", label: "Drug" },
                { key: "rates", label: "Rates", num: true },
                { key: "median_price_per_unit", label: "Median $ / unit", num: true,
                  render: (r) => fmt.usd(r.median_price_per_unit) },
                { key: "asp_payment_limit", label: "CMS ASP limit", num: true,
                  render: (r) => fmt.usd(r.asp_payment_limit) },
                { key: "median_markup", label: "Median", num: true,
                  render: (r) => <b>{fmt.x(r.median_markup)}</b> },
                { key: "max_markup", label: "Range", num: true,
                  render: (r) => `${fmt.x(r.min_markup)} – ${fmt.x(r.max_markup)}` },
              ]} />
          </section>
          <section>
            <h2>{isAdmin ? "Every rate in this file" : "Released price comparisons"}</h2>
            {d.n_rows === 0 ? <p className="note">This file has no comparison rows. See its import status above and the Data Quality page for details.</p>
              : <RatesTable fixed={{ hospital_key: key }} user={user} />}
          </section>
        </>
      )}
    </Loading>
  );
}
