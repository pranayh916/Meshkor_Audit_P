import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";

import { completeOtpLogin, confirmOtpEnrollment, getJSON, login, logout, restoreLogin, startOtpEnrollment } from "./api.js";
import "./styles.css";
import Overview from "./pages/Overview.jsx";
import DrugDetail from "./pages/DrugDetail.jsx";
import Hospitals from "./pages/Hospitals.jsx";
import HospitalDetail from "./pages/HospitalDetail.jsx";
import Rates from "./pages/Rates.jsx";
import Quality from "./pages/Quality.jsx";
import Method from "./pages/Method.jsx";
import Sources from "./pages/Sources.jsx";
import Reports from "./pages/Reports.jsx";
import ReferenceData from "./pages/ReferenceData.jsx";
import HospitalFiles from "./pages/HospitalFiles.jsx";
import DrugScope from "./pages/DrugScope.jsx";
import UnitValidation from "./pages/UnitValidation.jsx";
import AuditLogs from "./pages/AuditLogs.jsx";
import Settings from "./pages/Settings.jsx";
import PlanAudit from "./pages/PlanAudit.jsx";

function Landing({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [otpChallenge, setOtpChallenge] = useState("");
  const [otpEnrollment, setOtpEnrollment] = useState(null);
  const [firstLoginCodes, setFirstLoginCodes] = useState([]);
  const [readyUser, setReadyUser] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lockoutSeconds, setLockoutSeconds] = useState(0);
  const authFlowMode = Boolean(otpChallenge || otpEnrollment) || firstLoginCodes.length > 0;
  useEffect(() => {
    if (!lockoutSeconds) return undefined;
    const timer = window.setTimeout(() => {
      if (lockoutSeconds === 1) setError("");
      setLockoutSeconds((remaining) => Math.max(0, remaining - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [lockoutSeconds]);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      let result;
      if (otpEnrollment) {
        result = await confirmOtpEnrollment(otpChallenge, otpCode);
      } else if (otpChallenge) {
        result = await completeOtpLogin(otpChallenge, otpCode, recoveryCode);
      } else {
        result = await login(username, password);
      }
      setLockoutSeconds(0);
      if (result.otp_setup_required) {
        const enrollment = await startOtpEnrollment(result.challenge);
        setOtpChallenge(result.challenge);
        setOtpEnrollment(enrollment);
        setError("");
      } else if (result.otp_required) {
        setOtpChallenge(result.challenge);
        setError("");
      } else if (result.user && result.recovery_codes?.length) {
        setFirstLoginCodes(result.recovery_codes);
        setReadyUser(result.user);
      } else {
        onLogin(result.user);
      }
    } catch (e) {
      setError(e.message);
      if (e.retryAfterSeconds) setLockoutSeconds(e.retryAfterSeconds);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className={`landing ${authFlowMode ? "landing--auth-setup" : ""}`}>
      {!authFlowMode && <section className="landing-copy">
        <div className="landing-brand"><span className="landing-mark">MK</span><span>MeshKor Healthcare</span></div>
        <p className="eyebrow landing-kicker">Hospital price transparency</p>
        <h1>Infusion Drug Markup Audit</h1>
        <p className="lede">A clear, source-linked view of hospital infusion and injection prices against Medicare Part B benchmarks.</p>
        <div className="landing-highlights">
          <article><span className="highlight-index">01</span><div><h2>Quarter-specific benchmarks</h2><p>Compare reported rates with the CMS ASP payment limit, including the statutory 6% add-on.</p></div></article>
          <article><span className="highlight-index">02</span><div><h2>Hospital and payer detail</h2><p>Review Ohio price variation by drug, hospital, payer group, and reported setting.</p></div></article>
          <article><span className="highlight-index">03</span><div><h2>Evidence with context</h2><p>Source records, methodology, and data gaps stay visible throughout the audit.</p></div></article>
        </div>
        <p className="landing-footnote">Market analysis for review and planning. Comparisons are not a guarantee of savings.</p>
      </section>}
      <form id="access" className={`login-card ${authFlowMode ? "login-card--auth-setup" : ""}`} onSubmit={submit}>
        {firstLoginCodes.length > 0 ? <>
          <p className="eyebrow">Step 2 of 2 · Save recovery codes</p>
          <h2>Save your recovery codes</h2>
          <p className="muted">These codes are shown once. Save them securely; each can replace an authenticator code one time.</p>
          <ol>{firstLoginCodes.map((item) => <li key={item}><code>{item}</code></li>)}</ol>
          <button type="button" onClick={() => onLogin(readyUser)}>Continue to the dashboard</button>
        </> : <>
        {otpEnrollment && <p className="eyebrow">Step 1 of 2 · Authenticator setup</p>}
        {!otpChallenge && !otpEnrollment && <div className="login-card-heading">
          <span className="eyebrow">Secure sign-in</span>
          <h2>Access your dashboard</h2>
          <p>Sign in to view hospital reports and price comparisons.</p>
        </div>}
        {otpChallenge && <h2>{otpEnrollment ? "Set up Google Authenticator" : "Verify your sign-in"}</h2>}
        {otpEnrollment && <p className="muted">Authenticator setup is required for every account. Scan the code, then enter the current six-digit code.</p>}
        {otpChallenge && !otpEnrollment && <p className="muted">Enter the current six-digit code from your authenticator app.</p>}
        {!otpChallenge && <>
          <label>Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        </>}
        {otpChallenge && <>
          {otpEnrollment && <div className="otp-enrollment">
            <p className="otp-scan-instructions">Open Google Authenticator, tap <b>+</b>, then choose <b>Scan a QR code</b>.</p>
            <div className="otp-qr-frame" aria-label="Google Authenticator setup QR code">
              <QRCodeSVG value={otpEnrollment.otpauth_url} size={208} level="M" includeMargin />
            </div>
            <details className="otp-manual-key"><summary>Can’t scan? Enter setup key manually</summary>
              <p>In Google Authenticator, choose <b>Enter a setup key</b>.</p>
              <span>Account key</span><code>{otpEnrollment.secret}</code>
              <span>Account name</span><code>Infusion Audit · {username}</code>
            </details>
          </div>}
          <label>{otpEnrollment ? "Confirm setup with the six-digit code" : "Authenticator code"}<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={otpCode} onChange={(e) => setOtpCode(e.target.value)} disabled={Boolean(recoveryCode)} required={!recoveryCode} /></label>
          {!otpEnrollment && <>
            <label>Or use a recovery code<input autoComplete="one-time-code" value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} disabled={Boolean(otpCode)} required={!otpCode} /></label>
            <button type="button" className="button-link secondary" onClick={() => { setOtpChallenge(""); setOtpCode(""); setRecoveryCode(""); setError(""); }}>Use another sign-in</button>
          </>}
        </>}
        {error && <div className={`login-error ${lockoutSeconds ? "login-error--lockout" : ""}`} role="alert">
          <span>{error}</span>{lockoutSeconds > 0 && <strong>Retry in {Math.floor(lockoutSeconds / 60)}:{String(lockoutSeconds % 60).padStart(2, "0")}</strong>}
        </div>}
        <button disabled={busy || lockoutSeconds > 0 || (otpChallenge && otpCode.length !== 6 && !recoveryCode)}>{busy ? "Signing in…" : otpEnrollment ? "Enable authenticator and continue" : otpChallenge ? "Verify code" : lockoutSeconds ? "Please wait" : "Sign in"}</button>
        {!otpChallenge && !firstLoginCodes.length && <p className="login-security-note"><span aria-hidden="true">●</span> Protected with Google Authenticator</p>}
        </>}
      </form>
    </main>
  );
}

function LegacyDrugRedirect() {
  const { hcpcs } = useParams();
  return <Navigate to={`/medicare-part-b-drugs/${encodeURIComponent(hcpcs)}`} replace />;
}

function Shell({ user, onLogout }) {
  const [collapsed, setCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const titles = { "/": "Overview", "/reference-data-sets": "Reference data", "/hospital-price-transparency-files": "Hospital price files", "/hospitals": "Hospitals", "/drug-selection-scope": "Drug selection scope", "/drug-unit-validations": "Drug unit validations", "/hospital-drug-price-comparisons": "Hospital drug price comparisons", "/data-sources": "Data sources", "/reports": "Reports & exports", "/audit-logs": "Audit logs", "/application-settings": "Application settings", "/plan-specific-audit": "Plan-specific audit", "/hospital-file-quality": "Hospital file quality", "/methodology": "Methodology" };
  const pageTitle = titles[location.pathname] || "Infusion Drug Markup Audit";
  function submitSearch(event) {
    event.preventDefault();
    navigate(`/hospital-drug-price-comparisons?q=${encodeURIComponent(search.trim())}`);
  }
  return (
    <div className={`app-layout ${collapsed ? "nav-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><span className="mark">MK</span>{!collapsed && <div><div className="title">MeshKor</div><div className="sub">Healthcare analytics</div></div>}</div>
        <div className="sidebar-group"><span className="sidebar-label">AUDIT PLATFORM</span><nav aria-label="Main navigation">
          <NavLink to="/" end><span>◫</span>{!collapsed && "Overview"}</NavLink>
          <NavLink to="/hospitals"><span>⌂</span>{!collapsed && "Hospitals"}</NavLink>
          <NavLink to="/drug-selection-scope"><span>#</span>{!collapsed && "Drug Scope"}</NavLink>
          <NavLink to="/hospital-drug-price-comparisons"><span>↗</span>{!collapsed && "Comparisons"}</NavLink>
          <NavLink to="/reports"><span>▧</span>{!collapsed && "Reports"}</NavLink>
          <details className="sidebar-more">
            <summary><span>•••</span>{!collapsed && "More"}</summary>
            <div className="sidebar-subnav">
              <NavLink to="/hospital-price-transparency-files">Hospital Price Files</NavLink>
              <NavLink to="/reference-data-sets">Reference Data Sets</NavLink>
              <NavLink to="/hospital-file-quality">Hospital File Quality</NavLink>
              <NavLink to="/methodology">Methodology</NavLink>
              {user.roles?.includes("Admin") && <>
                <NavLink to="/data-sources">Data Sources & Import</NavLink>
                <NavLink to="/drug-unit-validations">Drug Unit Review</NavLink>
              </>}
              {user.roles?.includes("Admin") && <NavLink to="/audit-logs">Audit Logs</NavLink>}
              <NavLink to="/application-settings">Application Settings</NavLink>
            </div>
          </details>
        </nav></div>
        <button className="collapse-button" type="button" onClick={() => setCollapsed((v) => !v)} aria-expanded={!collapsed}>{collapsed ? "›" : "‹"}{!collapsed && " Collapse menu"}</button>
      </aside>
      <div className="app-workspace">
      <header className="appbar">
        <div><div className="crumb">MeshKor Healthcare / {pageTitle}</div><h1>{pageTitle}</h1></div>
        <form className="global-search" role="search" onSubmit={submitSearch}><input aria-label="Search price comparisons" placeholder="Search hospital, payer, drug…" value={search} onChange={(e) => setSearch(e.target.value)} /><button type="submit">Search</button></form>
        <div className="account"><div><b>{user.display_name}</b><span className="muted">{user.roles?.join(", ")}</span></div><button type="button" onClick={onLogout}>Logout</button></div>
      </header>
      <main className="page-content">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/reference-data-sets" element={<ReferenceData />} />
          <Route path="/hospital-price-transparency-files" element={<HospitalFiles />} />
          <Route path="/medicare-part-b-drugs/:hcpcs" element={<DrugDetail />} />
          <Route path="/hospitals" element={<Hospitals />} />
          <Route path="/hospitals/:key" element={<HospitalDetail />} />
          <Route path="/drug-selection-scope" element={<DrugScope />} />
          <Route path="/drug-unit-validations" element={<UnitValidation user={user} />} />
          <Route path="/hospital-drug-price-comparisons" element={<Rates />} />
          <Route path="/hospital-file-quality" element={<Quality />} />
          <Route path="/data-sources" element={<Sources user={user} />} />
          <Route path="/reports" element={<Reports user={user} />} />
          <Route path="/audit-logs" element={<AuditLogs />} />
          <Route path="/application-settings" element={<Settings user={user} />} />
          <Route path="/plan-specific-audit" element={<PlanAudit />} />
          <Route path="/methodology" element={<Method />} />
          <Route path="/reference" element={<Navigate to="/reference-data-sets" replace />} />
          <Route path="/hospital-files" element={<Navigate to="/hospital-price-transparency-files" replace />} />
          <Route path="/drugs/:hcpcs" element={<LegacyDrugRedirect />} />
          <Route path="/drug-scope" element={<Navigate to="/drug-selection-scope" replace />} />
          <Route path="/unit-validation" element={<Navigate to="/drug-unit-validations" replace />} />
          <Route path="/rates" element={<Navigate to={`/hospital-drug-price-comparisons${location.search}`} replace />} />
          <Route path="/quality" element={<Navigate to="/hospital-file-quality" replace />} />
          <Route path="/sources" element={<Navigate to="/data-sources" replace />} />
          <Route path="/settings" element={<Navigate to="/application-settings" replace />} />
          <Route path="/plan-audit" element={<Navigate to="/plan-specific-audit" replace />} />
          <Route path="/method" element={<Navigate to="/methodology" replace />} />
          <Route path="/dashboard/*" element={<Navigate to="/" replace />} />
        </Routes>
      </main></div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    restoreLogin()
      .then((result) => setUser(result.authenticated ? result.user : null))
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);
  async function signOut() {
    try { await logout(); } finally { setUser(null); }
  }
  if (checking) return <div className="auth-loading">Checking access…</div>;
  return user ? <Shell user={user} onLogout={signOut} />
    : <Landing onLogin={setUser} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<BrowserRouter><App /></BrowserRouter>);
