import { STATUS_TEXT } from "../api.js";
import { StatusPill } from "../components.jsx";

export default function Method() {
  return (
    <section className="prose">
      <h1>Method and limits</h1>

      <h2>What is compared</h2>
      <p>Each hospital publishes a machine-readable price file under federal price transparency
        rules. We keep the rows for the drugs in scope, identified by HCPCS code or by an NDC that
        the CMS NDC-HCPCS crosswalk maps to that code.</p>
      <p>The benchmark is the CMS Medicare Part B payment limit for the same HCPCS code. That
        limit already includes the ASP + 6% adjustment, so no further 6% is added.
        The comparison uses the ASP quarter containing the hospital file's "last updated" date.
        If that quarter is unavailable, the row is marked as missing its ASP benchmark and is
        left unpriced.</p>

      <h2>The calculation</h2>
      <ol>
        <li>Read the quantity and measurement unit the hospital priced from its source file.</li>
        <li>Convert that quantity to HCPCS billing units using the verified dosage for the
          selected code. If the units cannot be verified or converted, leave the row unpriced.</li>
        <li>Price per billing unit = hospital rate ÷ billing units.</li>
        <li>Markup = price per billing unit ÷ ASP payment limit. 1.00× equals Medicare.</li>
      </ol>
      <p>Headline figures use negotiated dollar rates with status "Compared" only.</p>

      <h2>Row statuses</h2>
      <ul className="plain">
        {Object.keys(STATUS_TEXT).map((s) => <li key={s}><StatusPill status={s} /></li>)}
      </ul>
      <p>A row whose unit cannot be converted is shown but never priced. Markups outside the
        configured review range are held for a manual check because they may indicate a unit error.</p>

      <h2>Limits</h2>
      <ul>
        <li><b>Unit risk.</b> A wrong unit changes a result by 10× or more. Each drug needs a
          pharmacist or clinical reviewer to check the conversion before results are published.</li>
        <li><b>340B.</b> Some hospitals buy drugs at 340B discounts. That lowers the hospital's
          cost, not what the health plan pays.</li>
        <li><b>Site of care.</b> Moving a patient to a lower-cost site needs the prescriber's
          agreement and an in-network site that can give the infusion.</li>
        <li><b>Posted rates.</b> Files show contracted rates, not claims paid. Percent-of-charges
          and formula contracts are listed but not priced unless the file posts a dollar
          estimate.</li>
        <li><b>Coverage.</b> Only hospitals with a downloadable file are included. See the Data
          quality page for each file.</li>
      </ul>

      <h2>Sources</h2>
      <ul>
        <li>CMS ASP Pricing Files and NDC-HCPCS Crosswalk</li>
        <li>Official Hospital Standard Charges Price Transparency Portals</li>
        <li>CMS Hospital Price Transparency Guidelines</li>
      </ul>
      <p>Every row keeps its source file reference, so any figure can be traced to the exact source file it came from.</p>
    </section>
  );
}
