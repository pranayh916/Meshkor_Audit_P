import { Link } from "react-router-dom";
import { fmt, useApi } from "../api.js";
import { Loading, MarkupBars, Table } from "../components.jsx";

export default function Hospitals() {
  const h = useApi("hospitals");
  return (
    <Loading state={h}>
      {(rows) => (
        <>
          <section>
            <h1>Hospitals</h1>
            <p className="lede">One row per stored hospital MRF file. Files with no selected-drug rows and files with parser errors remain visible, so this list can be reconciled to the archive.</p>
            <MarkupBars rows={rows} labelKey="hospital_label" />
          </section>
          <section>
            <Table rows={rows} initialSort={{ key: "median_markup", dir: "desc" }} columns={[
              { key: "hospital_label", label: "Hospital",
                render: (r) => <><Link to={`/hospitals/${r.hospital_key}`}>{r.hospital_label}</Link>
                  {r.locations && <div className="muted">{r.locations}</div>}</> },
              { key: "system", label: "System" },
              { key: "file_status", label: "File status", render: (r) => ({
                rates_found: "Rates found", no_selected_drug_rows: "No selected-drug rows",
                parse_error: "Parse error", comparison_only: "Comparison available",
              }[r.file_status] || r.file_status) },
              { key: "file_last_updated", label: "File date" },
              { key: "drugs_priced", label: "Drugs", num: true },
              { key: "rates", label: "Rates", num: true },
              { key: "items_scanned", label: "Items scanned", num: true },
              { key: "median_markup", label: "Median", num: true,
                render: (r) => <b>{fmt.x(r.median_markup)}</b> },
              { key: "max_markup", label: "Max", num: true, render: (r) => fmt.x(r.max_markup) },
              { key: "excluded_rows", label: "Not compared", num: true,
                render: (r) => fmt.n(r.excluded_rows + r.review_rows) },
              { key: "file_error", label: "Import error" },
            ]} />
          </section>
        </>
      )}
    </Loading>
  );
}
