import { useState } from "react";
import { useApi, fmt, postJSON } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function UnitValidation({ user }) {
  const state = useApi("drug-unit-validations");
  const [version, setVersion] = useState(0);
  const scope = useApi("drug-selection-scope", null, [version]);
  const [messages, setMessages] = useState({});
  const [busy, setBusy] = useState("");
  async function saveReview(event, drug) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(drug.hcpcs);
    setMessages((m) => ({ ...m, [drug.hcpcs]: "" }));
    try {
      await postJSON(`drug-selection-scope/${drug.hcpcs}/unit-review`, {
        status: form.get("status"), notes: form.get("notes"),
        clinical_reviewer_name: form.get("clinical_reviewer_name"),
        billing_unit: drug.billing_unit?.unit, billing_qty: drug.billing_unit?.qty,
      });
      setMessages((m) => ({ ...m, [drug.hcpcs]: "Review recorded. Run the Admin data refresh to apply it to Parquet and rebuild the report." }));
      setVersion((v) => v + 1);
    } catch (error) { setMessages((m) => ({ ...m, [drug.hcpcs]: error.message })); }
    finally { setBusy(""); }
  }
  return <>
    <h1>Unit validation</h1>
    <p className="lede">Conversions are not treated as validated findings until the HCPCS unit and supporting evidence have been reviewed.</p>
    <Loading state={state}>{(result) => <>
      {result.status === "blocked" && <div className="banner">No current spend-ranked scope is available. {result.reason}</div>}
      <section><div className="stats"><div className="stat"><div className="stat-label">Rows requiring review</div><div className="stat-value">{fmt.n(result.total)}</div></div><div className="stat"><div className="stat-label">Review workflow</div><div className="stat-value">Enabled</div><div className="stat-hint">{result.review_workflow}</div></div></div></section>
      <section><h2>Unit and benchmark exceptions</h2><Table rows={result.rows || []} columns={[
        { key: "hcpcs", label: "HCPCS" }, { key: "drug_name", label: "Drug" },
        { key: "hospital_label", label: "Hospital" }, { key: "status", label: "Status" },
        { key: "price", label: "Posted price", num: true, render: (r) => fmt.usd(r.price) },
        { key: "drug_unit", label: "Original unit", render: (r) => [r.drug_unit, r.drug_unit_type].filter(Boolean).join(" ") || "—" },
        { key: "billing_units", label: "HCPCS units", num: true }, { key: "unit_note", label: "Conversion note" },
        { key: "asp_payment_limit", label: "ASP limit", num: true, render: (r) => fmt.usd(r.asp_payment_limit) },
        { key: "markup_multiple", label: "Markup", num: true, render: (r) => fmt.x(r.markup_multiple) },
        { key: "source_file", label: "Source file" },
      ]} empty="No unit exceptions are available for the current scope." /></section>
    </>}</Loading>
    <Loading state={scope}>{(selected) => <section><h2>CMS billing-unit review</h2>
      <p className="muted">Review decisions are tied to the exact CMS Part B source hash. Approval requires the billing quantity and unit to match the source ASP dosage.</p>
      {selected.status === "blocked" ? <div className="note">{selected.reason}</div> : <>
        <p className="muted">After recording all reviews, run the Admin data refresh so the saved decisions are applied to Parquet and the comparison/report are rebuilt.</p>
        {(selected.drugs || []).map((drug) => <article className="review-card" key={drug.hcpcs}>
        <div><b>{drug.hcpcs} · {drug.name}</b><div className="muted">CMS dosage: {drug.asp_dosage || "Not available"} · current review: {drug.unit_review?.status || "Pending"}</div>
          {drug.unit_review?.clinical_reviewer_name && <div className="muted">Clinical reviewer: {drug.unit_review.clinical_reviewer_name} · {drug.unit_review.reviewed_at ? new Date(drug.unit_review.reviewed_at).toLocaleDateString() : "date unavailable"}</div>}
          {drug.unit_review?.notes && <div className="muted">Previous rationale: {drug.unit_review.notes}</div>}</div>
        <form className="review-form" onSubmit={(e) => saveReview(e, drug)}>
          <select name="status" aria-label={`Review status for ${drug.hcpcs}`} defaultValue="validated"><option value="validated">Validated</option><option value="rejected">Rejected</option><option value="unit_unresolved">Unit unresolved</option></select>
          <input name="clinical_reviewer_name" aria-label={`Clinical reviewer for ${drug.hcpcs}`} placeholder="External pharmacist / clinical reviewer name" defaultValue={drug.unit_review?.clinical_reviewer_name || ""} required minLength={3} />
          <input name="notes" aria-label={`Review note for ${drug.hcpcs}`} placeholder="Evidence and rationale (required for every decision)" required minLength={10} defaultValue={drug.unit_review?.notes || ""} />
          <button disabled={busy === drug.hcpcs || !user?.roles?.includes("Admin")}>{busy === drug.hcpcs ? "Saving…" : "Record clinical sign-off"}</button>
        </form>
        {messages[drug.hcpcs] && <p className="muted" role="status">{messages[drug.hcpcs]}</p>}
        </article>)}
      </>}
    </section>}</Loading>
  </>;
}
