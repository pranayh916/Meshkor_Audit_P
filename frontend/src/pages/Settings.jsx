import { useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { postJSON, useApi } from "../api.js";
import { Loading } from "../components.jsx";

function UserAuthenticator({ user }) {
  const [version, setVersion] = useState(0);
  const [enrollment, setEnrollment] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState([]);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const otp = useApi("authentication/totp/status", null, [version]);

  async function run(action) {
    setBusy(true); setError(""); setMessage("");
    try {
      if (action === "setup") setEnrollment(await postJSON("authentication/totp/setup", {}));
      if (action === "confirm") {
        const confirmed = await postJSON("authentication/totp/confirmation", { code });
        setRecoveryCodes(confirmed.recovery_codes || []);
        setEnrollment(null); setCode(""); setMessage("Google Authenticator is enabled for this account.");
        setVersion((v) => v + 1);
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return <section>
    <h2>Google Authenticator</h2>
    <p>A rotating authenticator code is required for every account after the password.</p>
    <Loading state={otp}>{(state) => <>
      <p>Status: <b>{state.enabled ? "Enabled" : state.setup_pending ? "Setup in progress" : "Off"}</b></p>
      {!state.enabled && !enrollment && <button className="button" type="button" onClick={() => run("setup")} disabled={busy}>Set up Google Authenticator</button>}
      {enrollment && <div className="otp-enrollment">
        <p className="otp-scan-instructions">Open Google Authenticator, tap <b>+</b>, then choose <b>Scan a QR code</b>.</p>
        <div className="otp-qr-frame" aria-label="Google Authenticator setup QR code">
          <QRCodeSVG value={enrollment.otpauth_url} size={208} level="M" includeMargin />
        </div>
        <details className="otp-manual-key"><summary>Can’t scan? Enter setup key manually</summary>
          <p>Use the account key in Google Authenticator’s manual setup.</p>
          <code>{enrollment.secret}</code>
        </details>
        <label>Enter the six-digit code to confirm
          <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <button className="button" type="button" onClick={() => run("confirm")} disabled={busy || code.length !== 6}>Confirm and enable</button>
      </div>}
      {state.enabled && <div className="otp-enrollment">
        <p>Recovery codes remaining: <b>{state.recovery_codes_remaining ?? 0}</b>. Each code works once.</p>
        <label>Current authenticator code
          <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <p>Authenticator verification is mandatory and cannot be disabled.</p>
      </div>}
      {recoveryCodes.length > 0 && <div className="otp-enrollment" role="status">
        <h3>Save these one-time recovery codes</h3>
        <p>They are shown only once. Store them somewhere safe; each code can be used once instead of an authenticator code.</p>
        <ol>{recoveryCodes.map((item) => <li key={item}><code>{item}</code></li>)}</ol>
        <button className="button secondary" type="button" onClick={() => setRecoveryCodes([])}>I saved these codes</button>
      </div>}
    </>}</Loading>
    {message && <p role="status" className="success-message">{message}</p>}
    {error && <p role="alert" className="note error">{error}</p>}
  </section>;
}

export default function Settings({ user }) {
  const state = useApi("application-settings");
  return <>
    <h1>Settings</h1>
    <p className="lede">Read-only view of configuration used by the current application build. Edit versioned project configuration, then rebuild data to change analytical behavior.</p>
    <Loading state={state}>{(cfg) => <>
      <section><h2>Report scope</h2><p>{cfg.report.title} · Target {cfg.report.target_drug_count} drugs</p><ul>{cfg.report.required_inputs.map((x) => <li key={x.key}>{x.label}: {x.purpose}</li>)}</ul></section>
      <section><h2>Comparison rules</h2><p>Benchmark quarter: <code>{cfg.comparison.benchmark_quarter}</code></p><p>Review range: <code>{cfg.comparison.review_range?.join("× to ")}×</code></p><p>Operational database: <code>{cfg.database_backend}</code></p><p>Hospital market frame: <code>{cfg.hospital_taxonomy.state_code}</code> · {cfg.hospital_taxonomy.hospital_types.join(", ")}</p></section>
      <section><h2>Planned employer audit</h2><p>{cfg.plan_specific_audit}. Member-level claims are not accepted by this application.</p></section>
    </>}</Loading>
    <UserAuthenticator user={user} />
  </>;
}
