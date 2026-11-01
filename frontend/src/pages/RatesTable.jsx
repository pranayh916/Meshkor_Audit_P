import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { csvUrl, fmt, getJSON, PRICE_TYPE_TEXT, STATUS_TEXT } from "../api.js";
import { StatusPill } from "../components.jsx";

const PAGE = 50;
const PAYERS = ["", "Anthem", "UnitedHealthcare", "Aetna", "Cigna", "Medical Mutual", "Humana",
  "CareSource", "Molina", "Medicare Advantage", "Medicaid MCO", "Other", "Not stated", "All payers"];

/** Server-side filtered, sorted, paged rate table with CSV export. */
export default function RatesTable({ fixed = {}, user }) {
  const isAdmin = user?.roles?.includes("Admin");
  const [searchParams] = useSearchParams();
  const [f, setF] = useState({ price_type: "", status: "", payer_group: "", q: "" });
  const [sort, setSort] = useState({ sort: "markup_multiple", order: "desc" });
  const [offset, setOffset] = useState(0);
  const [res, setRes] = useState({ rows: [], total: 0, error: null, loading: true });
  const params = { ...fixed, ...f, ...sort };
  const key = JSON.stringify(params);

  useEffect(() => { setF((old) => ({ ...old, q: searchParams.get("q") || "" })); }, [searchParams]);

  useEffect(() => { setOffset(0); }, [key]);
  useEffect(() => {
    let live = true;
    setRes((r) => ({ ...r, loading: true }));
    getJSON("hospital-drug-price-comparisons", { ...params, limit: PAGE, offset })
      .then((d) => live && setRes({ ...d, error: null, loading: false }))
      .catch((e) => live && setRes({ rows: [], total: 0, error: e, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, offset]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const th = (k, label, num) => (
    <th className={num ? "num" : ""} onClick={() => setSort({ sort: k,
      order: sort.sort === k && sort.order === "desc" ? "asc" : "desc" })}>
      {label}{sort.sort === k ? (sort.order === "desc" ? " ↓" : " ↑") : ""}
    </th>
  );

  return (
    <div>
      <div className="filters">
        <select value={f.price_type} onChange={set("price_type")}>
          <option value="">All price types</option>
          {Object.entries(PRICE_TYPE_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {isAdmin && <select value={f.status} onChange={set("status")}>
          <option value="">All statuses</option>
          {Object.entries(STATUS_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>}
        <select value={f.payer_group} onChange={set("payer_group")}>
          {PAYERS.map((p) => <option key={p} value={p}>{p || "All payer groups"}</option>)}
        </select>
        <input placeholder="Search hospital, payer, plan, description" value={f.q}
          onChange={set("q")} />
        <a className="button" href={csvUrl({ ...fixed, ...f })}>Export CSV</a>
      </div>
      {res.error && <div className="note error">{res.error.message}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {th("hospital_label", "Hospital")}
              {!fixed.hcpcs && th("drug_name", "Drug")}
              {th("payer_group", "Payer / plan")}
              <th>Hospital priced</th>
              {th("price", "Price", true)}
              <th className="num">Gross charge</th>
              <th className="num">Discounted cash</th>
              <th className="num">Negotiated %</th>
              <th className="num">Median / P10–P90</th>
              <th className="num">Billing units</th>
              {th("price_per_billing_unit", "$ / unit", true)}
              <th className="num">CMS ASP payment limit</th>
              {th("markup_multiple", "Markup", true)}
              {th("status", "Status")}
            </tr>
          </thead>
          <tbody>
            {res.rows.map((r, i) => (
              <tr key={i} title={isAdmin ? `${r.source_file || ""} :: ${r.source_member || ""}`.trim() : undefined}>
                <td><Link to={`/hospitals/${r.hospital_key}`}>{r.hospital_label}</Link>
                  <div className="muted">{r.setting || ""}</div></td>
                {!fixed.hcpcs && <td><Link to={`/drugs/${r.hcpcs}`}>{r.hcpcs}</Link>
                  <div className="muted">{r.drug_name}</div></td>}
                <td>{r.payer_group}<div className="muted">{[r.payer_name, r.plan_name]
                  .filter(Boolean).join(" · ")}</div></td>
                <td>{r.description}<div className="muted">
                  {r.drug_unit != null ? `${r.drug_unit} ${r.drug_unit_type}` : "no unit given"}
                  {r.matched_via === "ndc_crosswalk" ? ` · via NDC ${r.ndc11}` : ""}</div></td>
                <td className="num">{r.price_type === "contract_terms"
                  ? (r.negotiated_percentage != null ? `${r.negotiated_percentage}% of charges`
                    : "formula") : fmt.usd(r.price)}
                  <div className="muted">{PRICE_TYPE_TEXT[r.price_type]}</div></td>
                <td className="num">{fmt.usd(r.gross_charge)}</td>
                <td className="num">{fmt.usd(r.discounted_cash)}</td>
                <td className="num">{r.negotiated_percentage == null ? "—" : `${r.negotiated_percentage}%`}</td>
                <td className="num">{[r.median_amount, r.p10_amount, r.p90_amount].some((v) => v != null)
                  ? `${fmt.usd(r.median_amount)} / ${fmt.usd(r.p10_amount)}–${fmt.usd(r.p90_amount)}` : "—"}</td>
                <td className="num">{r.billing_units == null ? "—" : +r.billing_units.toFixed(3)}</td>
                <td className="num">{fmt.usd(r.price_per_billing_unit)}</td>
                <td className="num">{fmt.usd(r.asp_payment_limit)}
                  <div className="muted">{r.benchmark_quarter}</div></td>
                <td className="num"><b>{fmt.x(r.markup_multiple)}</b></td>
                <td><StatusPill status={r.status} />
                  {r.status !== "ok" && r.unit_note && <div className="muted">{r.unit_note}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!res.loading && !res.rows.length && <div className="note">No rows match.</div>}
      </div>
      <div className="pager">
        <span className="muted">{fmt.n(res.total)} rows</span>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Prev</button>
        <span>{res.total ? `${offset + 1}–${Math.min(offset + PAGE, res.total)}` : "0"}</span>
        <button disabled={offset + PAGE >= res.total} onClick={() => setOffset(offset + PAGE)}>Next →</button>
      </div>
    </div>
  );
}
