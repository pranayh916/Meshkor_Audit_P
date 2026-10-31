import { useApi, fmt } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function HospitalFiles() {
  const files = useApi("hospital-file-quality");
  const catalog = useApi("reference-data-sets/hospitals");
  return <>
    <h1>Hospital price files</h1>
    <p className="lede">Ohio acute-care coverage and MRF processing status from loaded CMS hospital and hospital-file records.</p>
    <Loading state={catalog}>{(hospitals) => <section><h2>Ohio hospital frame</h2><p>{fmt.n(hospitals.total)} hospital records in the CMS reference catalog.</p><Table rows={hospitals.rows || []} columns={[
      { key: "ccn", label: "CCN" }, { key: "hospital_name", label: "Hospital" },
      { key: "city", label: "City" }, { key: "county", label: "County" },
      { key: "hospital_type", label: "CMS type" }, { key: "npi", label: "NPI", render: (r) => r.npi || "Pending NPPES/enrollment match" },
    ]} empty="No hospital catalog rows." /></section>}</Loading>
    <Loading state={files}>{(rows) => <section><h2>MRF file processing</h2><p className="muted">Each row represents an observed file processing result. Presence in the input folder does not imply successful parsing.</p><Table rows={rows} columns={[
      { key: "system", label: "System" }, { key: "source_file", label: "Source file" },
      { key: "source_member", label: "Member" }, { key: "file_last_updated", label: "File date" },
      { key: "drug_rows", label: "Drug rows", num: true }, { key: "status", label: "Status" },
      { key: "error", label: "Validation error" },
    ]} empty="No MRF processing records." /></section>}</Loading>
  </>;
}
