import { useEffect, useState } from "react";
import { getJSON, fmt } from "../api.js";
import { Loading, Table } from "../components.jsx";

const PAGE_SIZE = 100;
const labels = {
  asp: "ASP limits", crosswalk: "NDC–HCPCS crosswalk", "ndc-products": "NDC products",
  "ndc-packages": "NDC packages", hospitals: "Ohio hospitals", nadac: "NADAC",
  providers: "NPPES providers", enrollments: "Hospital enrollments", "partb-spending": "Part B drug scope",
};

export default function ReferenceData() {
  const [catalog, setCatalog] = useState({ data: null, error: null, loading: true });
  const [table, setTable] = useState("asp");
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState({ data: null, error: null, loading: true });

  useEffect(() => { getJSON("reference-data-sets").then((v) => setCatalog({ data: v, error: null, loading: false }))
    .catch((e) => setCatalog({ data: null, error: e, loading: false })); }, []);
  useEffect(() => {
    let active = true;
    setData((s) => ({ ...s, loading: true, error: null }));
    getJSON(`reference-data-sets/${table}`, { q: applied, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then((v) => active && setData({ data: v, error: null, loading: false }))
      .catch((e) => active && setData({ data: null, error: e, loading: false }));
    return () => { active = false; };
  }, [table, applied, page]);

  const loaded = catalog.data?.filter((r) => r.status === "loaded").length || 0;
  const chosen = catalog.data?.find((r) => r.key === table);
  const columns = (data.data?.columns || []).slice(0, 12).map((key) => ({
    key, label: key.replaceAll("_", " "),
    render: (row) => row[key] == null ? "—" : typeof row[key] === "object" ? JSON.stringify(row[key]) : String(row[key]),
  }));
  return <>
    <h1>Reference data</h1>
    <p className="lede">Searchable CMS, FDA, and provider reference tables. Loaded status, periods, lineage, and known gaps come from the current local Parquet outputs.</p>
    <section><div className="stats"><div className="stat"><div className="stat-label">Reference tables loaded</div><div className="stat-value">{fmt.n(loaded)} / {fmt.n(catalog.data?.length)}</div></div></div></section>
    <Loading state={catalog}>{(rows) => <section>
      <h2>Source tables</h2>
      <div className="source-grid">{rows.map((r) => <button type="button" className={`reference-card ${table === r.key ? "selected" : ""}`} key={r.key} onClick={() => { setTable(r.key); setPage(0); }}>
        <b>{r.label}</b><span className={`pill ${r.status === "loaded" ? "s-ok" : "s-review_range"}`}>{r.status}</span>
        <span>{fmt.n(r.rows)} records</span><span className="muted">{r.periods?.join(", ") || "No period field available"}</span>
      </button>)}</div>
    </section>}</Loading>
    <section>
      <div className="section-heading"><h2>{labels[table] || table}</h2><span className="muted">{chosen?.status === "missing" ? "Not loaded" : `${fmt.n(data.data?.total)} records`}</span></div>
      <form className="filters" onSubmit={(e) => { e.preventDefault(); setApplied(query); setPage(0); }}>
        <input aria-label="Search reference records" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search across text columns" />
        <button className="button">Search</button>
      </form>
      {data.error ? <div className="note error" role="alert">Could not load this reference table: {data.error.message}</div>
        : data.loading ? <div className="skeleton-line" aria-label="Loading reference rows" />
          : data.data?.status === "missing" ? <div className="note">This source has not been imported. No records are shown until the official source is available and validated.</div>
            : <>
              <Table rows={data.data?.rows || []} columns={columns} empty="No matching reference records." />
              <div className="pager"><button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button><span>{fmt.n((data.data?.offset || 0) + 1)}–{fmt.n(Math.min((data.data?.offset || 0) + PAGE_SIZE, data.data?.total || 0))} of {fmt.n(data.data?.total)}</span><button disabled={(data.data?.offset || 0) + PAGE_SIZE >= (data.data?.total || 0)} onClick={() => setPage((p) => p + 1)}>Next</button></div>
            </>}
    </section>
  </>;
}
