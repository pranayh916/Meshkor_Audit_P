export default function PlanAudit() {
  return <>
    <h1>Plan-specific audit</h1>
    <p className="lede"><span className="pill">Planned</span> This workflow is not operational.</p>
    <section><h2>Future client-side summary</h2>
      <p>Claims stay in the employer or TPA environment. A future extraction tool will emit only aggregate HCPCS, site NPI, quarter, units, allowed amount, paid amount, and member-count band.</p>
      <p>Groups with fewer than 11 members must be suppressed. No member-level claims are uploaded to or stored by this application.</p>
      <p className="muted">A savings comparison will require validated site rates plus evidence of network access, utilization, and clinical suitability.</p>
    </section>
  </>;
}
