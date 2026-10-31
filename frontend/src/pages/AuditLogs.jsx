import { useApi, fmt } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function AuditLogs() {
  const state = useApi("audit-logs", { limit: 100 });
  return <>
    <h1>Audit logs</h1>
    <p className="lede">Recorded authentication, source-file, and report approval events. Access is restricted to administrators.</p>
    <Loading state={state}>{(rows) => <section><h2>Recent events</h2><Table rows={rows} columns={[
      { key: "created_at", label: "Time", render: (r) => new Date(r.created_at).toLocaleString() },
      { key: "action", label: "Action" }, { key: "actor", label: "User" },
      { key: "entity_type", label: "Record type" }, { key: "entity_id", label: "Record ID" },
      { key: "details", label: "Details", render: (r) => <code>{JSON.stringify(r.details || {})}</code> },
    ]} empty="No audit events have been recorded." /></section>}</Loading>
  </>;
}
