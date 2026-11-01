import { useState } from "react";
import { postJSON, useApi } from "../api.js";
import { Loading, Table } from "../components.jsx";

export default function UserManagement({ user }) {
  const [version, setVersion] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [resetFor, setResetFor] = useState(null);
  const accounts = useApi("user-accounts", null, [version]);

  async function createAccount(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy("create"); setError(""); setMessage("");
    try {
      const created = await postJSON("user-accounts", {
        username: form.get("username"), first_name: form.get("first_name"),
        last_name: form.get("last_name"), email: form.get("email"),
        role: form.get("role"), password: form.get("password"),
      });
      formElement.reset();
      setMessage(`${created.username} was created as ${created.roles[0]}.`);
      setVersion((v) => v + 1);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  }

  async function updateAccount(account, change) {
    setBusy(String(account.id)); setError(""); setMessage("");
    try {
      await postJSON(`user-accounts/${account.id}/management`, change);
      setMessage(`Updated account ${account.username}.`);
      setVersion((v) => v + 1);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  }

  async function resetPassword(event, account) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const password = new FormData(formElement).get("password");
    setBusy(`password-${account.id}`); setError(""); setMessage("");
    try {
      await postJSON(`user-accounts/${account.id}/management`, { password });
      formElement.reset();
      setResetFor(null);
      setMessage(`Password reset for ${account.username}. Share the new password with them privately.`);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  }

  return <>
    <h1>User management</h1>
    <p className="lede">Create and manage the two application roles. Admins use Google Authenticator; Viewers can access released reports only.</p>
    <section>
      <h2>Create account</h2>
      <form className="source-upload-form" onSubmit={createAccount}>
        <label>Username<input name="username" autoComplete="off" required maxLength={150} /></label>
        <label>First name<input name="first_name" maxLength={150} /></label>
        <label>Last name<input name="last_name" maxLength={150} /></label>
        <label>Email<input name="email" type="email" maxLength={254} /></label>
        <label>Role<select name="role" defaultValue="Viewer"><option>Viewer</option><option>Admin</option></select></label>
        <label>Initial password<input name="password" type="password" autoComplete="new-password" required minLength={10} /></label>
        <button className="button" disabled={busy === "create"}>{busy === "create" ? "Creating…" : "Create account"}</button>
      </form>
      <p className="muted">New Admins must enroll an authenticator at first sign-in. At least two active Admin accounts are required to release a report.</p>
      {message && <p role="status" className="success-message">{message}</p>}
      {error && <p role="alert" className="note error">{error}</p>}
    </section>
    <Loading state={accounts}>{(rows) => <section>
      <h2>Application accounts</h2>
      <Table rows={rows} columns={[
        { key: "username", label: "Username" },
        { key: "display_name", label: "Name" },
        { key: "email", label: "Email" },
        { key: "roles", label: "Role", render: (r) => r.roles?.join(", ") || "No role" },
        { key: "is_active", label: "Status", render: (r) => r.is_active ? "Active" : "Disabled" },
        { key: "last_login", label: "Last sign-in", render: (r) => r.last_login ? new Date(r.last_login).toLocaleString() : "Never" },
        { key: "actions", label: "Actions", render: (r) => <div className="account-actions">
          <div className="filters">
            {!r.roles?.includes("Admin") && <button type="button" disabled={busy === String(r.id)} onClick={() => updateAccount(r, { role: "Admin", is_active: r.is_active })}>Make Admin</button>}
            {r.roles?.includes("Admin") && r.id !== user?.id && <button type="button" className="secondary" disabled={busy === String(r.id)} onClick={() => updateAccount(r, { role: "Viewer", is_active: r.is_active })}>Make Viewer</button>}
            {r.id !== user?.id && <>
              <button type="button" className="secondary" disabled={busy.startsWith("password-")} onClick={() => setResetFor(resetFor === r.id ? null : r.id)}>Reset password</button>
              <button type="button" className="secondary" disabled={busy === String(r.id)} onClick={() => updateAccount(r, { role: r.roles?.[0] || "Viewer", is_active: !r.is_active })}>{r.is_active ? "Disable" : "Enable"}</button>
            </>}
          </div>
          {resetFor === r.id && <form className="inline-password-reset" onSubmit={(event) => resetPassword(event, r)}>
            <label>New password<input name="password" type="password" autoComplete="new-password" required minLength={10} /></label>
            <button type="submit" disabled={busy === `password-${r.id}`}>{busy === `password-${r.id}` ? "Saving…" : "Save password"}</button>
          </form>}
        </div> },
      ]} />
    </section>}</Loading>
  </>;
}
