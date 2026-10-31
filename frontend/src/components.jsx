import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis } from "recharts";
import { STATUS_TEXT } from "./api.js";

export function Loading({ state, children }) {
  if (state.loading && !state.data) return <div className="loading-skeleton" aria-label="Loading data"><span /><span /><span /></div>;
  if (state.error) return (
    <div className="note error">
      <b>Could not load data.</b> {state.error.message}
      <div>Check the API response and the latest import status under Data Sources.</div>
    </div>
  );
  return children(state.data);
}

export function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function StatusPill({ status }) {
  return <span className={`pill s-${status}`}>{STATUS_TEXT[status] || status}</span>;
}

export function Provisional({ reviewed }) {
  if (reviewed) return null;
  return (
    <div className="banner">
      <b>Not yet reviewed.</b> Unit conversion for this drug has no pharmacist sign-off.
      Treat markups as provisional until a reviewer sign-off is recorded under
      <code> data/raw_essential_inputs/unit_reviews/</code>.
    </div>
  );
}

/** Sortable table. columns: [{key, label, render?, num?}] */
export function Table({ columns, rows, initialSort, empty = "No rows." }) {
  const [sort, setSort] = useState(initialSort || { key: null, dir: "desc" });
  const sorted = useMemo(() => {
    if (!sort.key) return rows;
    const s = [...rows].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (sort.dir === "asc" ? 1 : -1);
    });
    return s;
  }, [rows, sort]);
  if (!rows.length) return <div className="note">{empty}</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num" : ""}
                onClick={() => setSort({ key: c.key,
                  dir: sort.key === c.key && sort.dir === "desc" ? "asc" : "desc" })}>
                {c.label}{sort.key === c.key ? (sort.dir === "desc" ? " ↓" : " ↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : ""}>
                  {c.render ? c.render(r) : r[c.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Horizontal bars of markup multiple with a 1× (= Medicare) reference line. */
export function MarkupBars({ rows, labelKey, valueKey = "median_markup", height,
  reviewRange = [] }) {
  const data = rows.filter((r) => r[valueKey] != null)
    .sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0))
    .map((r) => ({
      name: r[labelKey],
      v: r[valueKey],
      hcpcs: r.hcpcs,
      rates: r.rates,
      hospitals: r.hospitals_priced,
    }));
  if (!data.length) return <div className="note">No compared rates to chart.</div>;
  const h = height || Math.max(220, data.length * 36 + 60);
  const narrow = typeof window !== "undefined" && window.innerWidth < 640;
  const yw = narrow ? 130 : 260;
  const maxChars = narrow ? 16 : 38;

  const CustomTooltip = ({ active, payload }) => {
    if (active && payload && payload.length) {
      const d = payload[0].payload;
      return (
        <div style={{ background: "var(--panel)", border: "1px solid var(--line)", padding: "10px 14px", borderRadius: "6px", boxShadow: "0 4px 12px rgba(0,0,0,0.06)" }}>
          <div style={{ fontWeight: 600, color: "var(--ink)", marginBottom: 4 }}>{d.name}</div>
          <div style={{ color: "var(--accent)", fontWeight: 600 }}>Median markup: {d.v?.toFixed(2)}× CMS ASP payment limit</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 4 }}>
            <span>Valid observations: <b>{d.rates?.toLocaleString()}</b></span> · <span>Hospitals: <b>{d.hospitals?.toLocaleString()}</b></span>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 36, top: 22, bottom: 8 }}>
          <CartesianGrid horizontal={false} stroke="var(--grid)" />
          <XAxis type="number" tickFormatter={(v) => `${+v.toFixed(1)}×`} stroke="var(--muted)"
            fontSize={12} allowDecimals domain={[0, (max) => Math.max(2, Math.ceil(max))]} />
          <YAxis type="category" dataKey="name" width={yw} stroke="var(--muted)" fontSize={12}
            tickFormatter={(s) => (s.length > maxChars ? s.slice(0, maxChars - 1) + "…" : s)} />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine x={1} stroke="var(--ink)" strokeDasharray="4 3"
            label={{ value: "Medicare (1.0×)", position: "top", fill: "var(--muted)", fontSize: 11 }} />
          <Bar dataKey="v" radius={[0, 4, 4, 0]}>
            {data.map((d, i) => (
              <Cell key={i} fill={reviewRange.length === 2 &&
                (d.v < reviewRange[0] || d.v > reviewRange[1]) ? "var(--hot)" : "var(--cool)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
