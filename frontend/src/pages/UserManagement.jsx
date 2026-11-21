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

    <div className="user-management-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Platform Administration</p>
          <h1 className="header-main-title">User Account Management</h1>
          <p className="header-subtitle">Create new staff accounts, manage assigned roles, reset passwords, and toggle access.</p>
        </div>
      </header>

      {message && <div role="status" className="success-message" style={{ margin: "16px 0" }}>✓ {message}</div>}
      {error && <div role="alert" className="note error" style={{ margin: "16px 0" }}>⚠ {error}</div>}

      <div className="user-management-grid" style={{ display: "grid", gridTemplateColumns: "minmax(320px, 1fr) minmax(0, 2fr)", gap: "24px", alignItems: "start", marginTop: "20px" }}>
        {/* Left Column: Create User Form */}
        <section className="dashboard-panel" style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "12px", padding: "24px" }}>
          <div className="panel-header" style={{ marginBottom: "16px" }}>
            <h2 style={{ fontSize: "18px", margin: "0 0 6px" }}>Create New User</h2>
            <p className="muted" style={{ fontSize: "13px", margin: 0 }}>Create a new platform user with initial credentials.</p>
          </div>

          <form onSubmit={createAccount} style={{ display: "grid", gap: "14px" }}>
            <div style={{ display: "grid", gap: "6px" }}>
              <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>Username *</label>
              <input name="username" autoComplete="off" required maxLength={150} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div style={{ display: "grid", gap: "6px" }}>
                <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>First Name</label>
                <input name="first_name" maxLength={150} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }} />
              </div>
              <div style={{ display: "grid", gap: "6px" }}>
                <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>Last Name</label>
                <input name="last_name" maxLength={150} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }} />
              </div>
            </div>

            <div style={{ display: "grid", gap: "6px" }}>
              <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>Email Address</label>
              <input name="email" type="email" maxLength={254} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }} />
            </div>

            <div style={{ display: "grid", gap: "6px" }}>
              <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>Role Assignment *</label>
              <select name="role" defaultValue="CLIENT" style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }}>
                <option value="SUPER_ADMIN">Super Admin (Full Access)</option>
                <option value="ANALYST">Analyst (Ingestion & Pipelines)</option>
                <option value="REVIEWER">Reviewer (Audit Approvals)</option>
                <option value="CLIENT">Client (Approved Audits Only)</option>
              </select>
            </div>

            <div style={{ display: "grid", gap: "6px" }}>
              <label style={{ fontSize: "12px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.04em" }}>Initial Password *</label>
              <input name="password" type="password" autoComplete="new-password" required minLength={10} placeholder="Min 10 characters" style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--line)" }} />
            </div>

            <button className="button" disabled={busy === "create"} style={{ marginTop: "8px", width: "100%", padding: "10px" }}>
              {busy === "create" ? "Creating Account…" : "Create User Account"}
            </button>
          </form>

          <p className="muted" style={{ fontSize: "12px", marginTop: "14px", lineHeight: 1.4 }}>
            ℹ️ Passwords must be at least 10 characters. Two-factor authentication (MFA) will be configured on initial sign-in.
          </p>
        </section>

        {/* Right Column: Existing Users */}
        <section className="dashboard-panel" style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "12px", padding: "24px" }}>
          <div className="panel-header" style={{ marginBottom: "16px" }}>
            <h2 style={{ fontSize: "18px", margin: "0 0 6px" }}>Platform Users</h2>
            <p className="muted" style={{ fontSize: "13px", margin: 0 }}>Registered accounts and assigned role privileges.</p>
          </div>

          <Loading state={accounts}>
            {(rows) => (
              <div style={{ overflowX: "auto" }}>
                <table className="comparison-table" style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid var(--line)", textAlign: "left" }}>
                      <th style={{ padding: "10px" }}>User</th>
                      <th style={{ padding: "10px" }}>Role</th>
                      <th style={{ padding: "10px" }}>Status</th>
                      <th style={{ padding: "10px" }}>Last Login</th>
                      <th style={{ padding: "10px", textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const roleName = r.roles?.[0] || "CLIENT";
                      return (
                        <tr key={r.id} style={{ borderBottom: "1px solid var(--line)" }}>
                          <td style={{ padding: "12px 10px" }}>
                            <div style={{ fontWeight: "600", color: "var(--ink)" }}>{r.username}</div>
                            <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                              {r.display_name || "—"} {r.email ? `• ${r.email}` : ""}
                            </div>
                          </td>
                          <td style={{ padding: "12px 10px" }}>
                            <span className="role-tag" style={{
                              display: "inline-block", padding: "3px 8px", borderRadius: "4px", fontSize: "11px", fontWeight: "600",
                              background: roleName === "SUPER_ADMIN" ? "#fef3c7" : roleName === "ANALYST" ? "#e0e7ff" : roleName === "REVIEWER" ? "#fce7f3" : "#f3f4f6",
                              color: roleName === "SUPER_ADMIN" ? "#92400e" : roleName === "ANALYST" ? "#3730a3" : roleName === "REVIEWER" ? "#9d174d" : "#374151"
                            }}>
                              {roleName.replace("_", " ")}
                            </span>
                          </td>
                          <td style={{ padding: "12px 10px" }}>
                            <span style={{
                              display: "inline-block", width: "8px", height: "8px", borderRadius: "50%",
                              background: r.is_active ? "#10b981" : "#ef4444", marginRight: "6px"
                            }} />
                            <span style={{ fontSize: "12px", color: r.is_active ? "var(--ink)" : "var(--muted)" }}>
                              {r.is_active ? "Active" : "Disabled"}
                            </span>
                          </td>
                          <td style={{ padding: "12px 10px", fontSize: "12px", color: "var(--muted)" }}>
                            {r.last_login ? new Date(r.last_login).toLocaleDateString() : "Never"}
                          </td>
                          <td style={{ padding: "12px 10px", textAlign: "right" }}>
                            <div style={{ display: "inline-flex", gap: "6px", flexWrap: "wrap", justifyContent: "flex-end" }}>
                              {/* Change Role Selector */}
                              <select
                                value={roleName}
                                disabled={busy === String(r.id)}
                                onChange={(e) => updateAccount(r, { role: e.target.value, is_active: r.is_active })}
                                style={{ fontSize: "11px", padding: "3px 6px", borderRadius: "4px", border: "1px solid var(--line)" }}
                              >
                                <option value="SUPER_ADMIN">Super Admin</option>
                                <option value="ANALYST">Analyst</option>
                                <option value="REVIEWER">Reviewer</option>
                                <option value="CLIENT">Client</option>
                              </select>

                              {r.id !== user?.id && (
                                <>
                                  <button
                                    type="button"
                                    className="button-subtle"
                                    style={{ fontSize: "11px", padding: "3px 8px" }}
                                    onClick={() => setResetFor(resetFor === r.id ? null : r.id)}
                                  >
                                    🔑 Reset Pass
                                  </button>
                                  <button
                                    type="button"
                                    className="button-subtle"
                                    style={{ fontSize: "11px", padding: "3px 8px", color: r.is_active ? "#ef4444" : "#10b981" }}
                                    onClick={() => updateAccount(r, { role: roleName, is_active: !r.is_active })}
                                  >
                                    {r.is_active ? "Disable" : "Enable"}
                                  </button>
                                </>
                              )}
                            </div>

                            {/* Inline Password Reset Form */}
                            {resetFor === r.id && (
                              <form
                                onSubmit={(event) => resetPassword(event, r)}
                                style={{
                                  marginTop: "8px", padding: "10px", background: "var(--bg)",
                                  border: "1px solid var(--line)", borderRadius: "6px", display: "flex", gap: "8px"
                                }}
                              >
                                <input
                                  name="password"
                                  type="password"
                                  autoComplete="new-password"
                                  placeholder="New password (min 10 chars)"
                                  required
                                  minLength={10}
                                  style={{ fontSize: "12px", padding: "4px 8px", flex: 1 }}
                                />
                                <button type="submit" disabled={busy === `password-${r.id}`} style={{ fontSize: "12px", padding: "4px 10px" }}>
                                  {busy === `password-${r.id}` ? "Saving…" : "Save"}
                                </button>
                                <button type="button" onClick={() => setResetFor(null)} style={{ fontSize: "12px", padding: "4px 8px" }}>
                                  ✕
                                </button>
                              </form>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Loading>
        </section>
      </div>
    </div>;
}
