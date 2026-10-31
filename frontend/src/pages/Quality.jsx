import { fmt, useApi } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function Quality() {
  const q = useApi("hospital-file-quality");
  return (
    <section>
      <h1>Data quality by file</h1>
      <p className="lede">What the parser found in each hospital file. A file with 0 drug rows
        either has none of the drugs in scope or uses a layout the parser does not read yet.</p>
      <Loading state={q}>
        {(rows) => (
          <Table rows={rows} columns={[
            { key: "system", label: "System" },
            { key: "hospital_name", label: "Hospital",
              render: (r) => <>{r.hospital_name || "—"}<div className="muted mono">{r.source_member}</div></> },
            { key: "format", label: "Format" },
            { key: "cms_version", label: "CMS ver." },
            { key: "file_last_updated", label: "File date" },
            { key: "items_scanned", label: "Items scanned", num: true, render: (r) => fmt.n(r.items_scanned) },
            { key: "drug_rows", label: "Drug rows", num: true, render: (r) => fmt.n(r.drug_rows) },
            { key: "hcpcs_found", label: "Codes found" },
            { key: "error", label: "Error", render: (r) => r.error
              ? <span className="pill s-unit_unresolved">{r.error}</span> : "—" },
          ]} />
        )}
      </Loading>
    </section>
  );
}
