import React, { lazy, Suspense, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { canAccess, hasRole, isClientOnly } from "./rolePolicy.js";

import { completeOtpLogin, confirmOtpEnrollment, getJSON, login, logout, restoreLogin, startOtpEnrollment } from "./api.js";
import "./styles.css";
const Overview = lazy(() => import("./pages/Overview.jsx"));
const DrugDetail = lazy(() => import("./pages/DrugDetail.jsx"));
const Hospitals = lazy(() => import("./pages/Hospitals.jsx"));
const HospitalDetail = lazy(() => import("./pages/HospitalDetail.jsx"));
const Rates = lazy(() => import("./pages/Rates.jsx"));
const Quality = lazy(() => import("./pages/Quality.jsx"));
const Method = lazy(() => import("./pages/Method.jsx"));
const Sources = lazy(() => import("./pages/Sources.jsx"));
const Reports = lazy(() => import("./pages/Reports.jsx"));
const ReferenceData = lazy(() => import("./pages/ReferenceData.jsx"));
const HospitalFiles = lazy(() => import("./pages/HospitalFiles.jsx"));
const DrugScope = lazy(() => import("./pages/DrugScope.jsx"));
const UnitValidation = lazy(() => import("./pages/UnitValidation.jsx"));
const AuditLogs = lazy(() => import("./pages/AuditLogs.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));
const UserManagement = lazy(() => import("./pages/UserManagement.jsx"));
const PlanAudits = lazy(() => import("./pages/PlanAudits.jsx"));
const ClaimsExplorer = lazy(() => import("./pages/ClaimsExplorer.jsx"));
const ClientPlanAudits = lazy(() => import("./pages/ClientPlanAudits.jsx"));

function ThemeToggle({ theme, onToggle }) {
  const dark = theme === "dark";
  return <button
    type="button"
    className="theme-toggle"
    aria-label={`Switch to ${dark ? "light" : "dark"} theme`}
    aria-pressed={dark}
    onClick={onToggle}
  ><span aria-hidden="true">{dark ? "☀" : "☾"}</span><span>{dark ? "Light" : "Dark"}</span></button>;
}

function Landing({ onLogin, theme, onToggleTheme }) {
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
      if (["challenge_expired", "challenge_invalid", "authentication_state_invalid"].includes(e.code)
          && username && password) {
        setOtpChallenge("");
        setOtpCode("");
        setRecoveryCode("");
        try {
          const fresh = await login(username, password);
          if (fresh.otp_required) {
            setOtpChallenge(fresh.challenge);
            setError("Sign-in challenge renewed. Enter the current authenticator code.");
          } else if (fresh.otp_setup_required) {
            const enrollment = await startOtpEnrollment(fresh.challenge);
            setOtpChallenge(fresh.challenge);
            setOtpEnrollment(enrollment);
            setError("");
          } else if (fresh.user) {
            onLogin(fresh.user);
          }
        } catch (renewError) {
          setError(renewError.message);
        }
      } else {
        setError(e.message);
      }
      if (e.retryAfterSeconds) setLockoutSeconds(e.retryAfterSeconds);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className={`landing ${authFlowMode ? "landing--auth-setup" : ""}`}>
      <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      {!authFlowMode && <section className="landing-copy">
        <div className="landing-brand"><span className="landing-mark">MK</span><span>MeshKor Healthcare</span></div>
        <p className="eyebrow landing-kicker">Hospital price transparency</p>
        <h1>Infusion Drug Markup Audit</h1>
        <p className="lede">Compare hospital drug prices with Medicare Part B benchmarks.</p>
        <div className="landing-highlights">
          <article><span className="highlight-index">01</span><div><h2>Quarter-specific benchmarks</h2></div></article>
          <article><span className="highlight-index">02</span><div><h2>Hospital and payer detail</h2></div></article>
          <article><span className="highlight-index">03</span><div><h2>Source-linked results</h2></div></article>
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
        {!otpChallenge && !firstLoginCodes.length && <p className="login-security-note"><span aria-hidden="true">●</span> All accounts use Google Authenticator verification</p>}
        </>}
      </form>
    </main>
  );
}

function LegacyDrugRedirect() {
  const { hcpcs } = useParams();
  return <Navigate to={`/medicare-part-b-drugs/${encodeURIComponent(hcpcs)}`} replace />;
}

function AccessDenied() {
  return <section className="note" role="alert"><h2>Access denied</h2>
    <p>Your account does not have permission to open this workspace.</p><NavLink to="/">Return to your dashboard</NavLink>
  </section>;
}

function RequirePolicy({ user, policy, children }) {
  return canAccess(user, policy) ? children : <AccessDenied />;
}

function InternalWorkspaceOnly({ user, children }) {
  return user?.roles?.some((role) => ["SUPER_ADMIN", "ANALYST", "REVIEWER", "Admin"].includes(role))
    ? children : <Navigate to="/" replace />;
}

function Shell({ user, onLogout, theme, onToggleTheme }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [search, setSearch] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const titles = { "/": "Overview", "/reference-data-sets": "Reference data", "/hospital-price-transparency-files": "Ohio hospital catalog", "/hospitals": "Hospitals", "/drug-selection-scope": "Drug scope", "/drug-unit-validations": "Drug unit review", "/hospital-drug-price-comparisons": "Price comparisons", "/data-sources": "Data imports", "/reports": "Reports and exports", "/plan-specific-audits": "Plan audits", "/claims-explorer": "Claims explorer", "/claims": "Claims explorer", "/audit-logs": "Audit log", "/application-settings": "Application settings", "/hospital-file-quality": "Hospital file quality", "/methodology": "Methodology", "/user-management": "User management" };
  const pageTitle = titles[location.pathname] || "Infusion Drug Markup Audit";
  useEffect(() => setMobileNavOpen(false), [location.pathname]);
  useEffect(() => {
    if (!mobileNavOpen) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    const closeOnDesktop = () => {
      if (window.innerWidth > 720) setMobileNavOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnDesktop);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnDesktop);
    };
  }, [mobileNavOpen]);
  function submitSearch(event) {
    event.preventDefault();
    navigate(`/hospital-drug-price-comparisons?q=${encodeURIComponent(search.trim())}`);
  }
  return (
    <div className={`app-layout ${collapsed ? "nav-collapsed" : ""} ${mobileNavOpen ? "mobile-nav-open" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><span className="mark">MK</span>{!collapsed && <div><div className="title">MeshKor</div><div className="sub">Healthcare analytics</div></div>}
          <button className="mobile-menu-toggle" type="button" aria-label={mobileNavOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-controls="primary-navigation" aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen((open) => !open)}>
            <span /><span /><span />
          </button>
        </div>
        <div className="sidebar-group"><span className="sidebar-label">AUDIT PLATFORM</span><nav id="primary-navigation" aria-label="Main navigation">
          <NavLink to="/" end><span aria-hidden="true">◫</span><span className="nav-label">Overview</span></NavLink>
          {canAccess(user, "market") && <NavLink to="/hospitals"><span aria-hidden="true">⌂</span><span className="nav-label">Hospitals</span></NavLink>}
          {canAccess(user, "drugScope") && <NavLink to="/drug-selection-scope"><span aria-hidden="true">#</span><span className="nav-label">Drug Scope</span></NavLink>}
          {canAccess(user, "market") && <NavLink to="/hospital-drug-price-comparisons"><span aria-hidden="true">↗</span><span className="nav-label">Comparisons</span></NavLink>}
          {canAccess(user, "planAudits") && <NavLink to="/plan-specific-audits"><span aria-hidden="true">◉</span><span className="nav-label">{hasRole(user, "REVIEWER") && !hasRole(user, "ANALYST", "SUPER_ADMIN") ? "Review Queue" : "Plan Audits"}</span></NavLink>}
          {canAccess(user, "claims") && <NavLink to="/claims-explorer"><span aria-hidden="true">▦</span><span className="nav-label">Claims Explorer</span></NavLink>}
          {canAccess(user, "market") && <NavLink to="/reports"><span aria-hidden="true">▧</span><span className="nav-label">Reports</span></NavLink>}
          <details className="sidebar-more">
            <summary><span aria-hidden="true">•••</span><span className="nav-label">More</span></summary>
            <div className="sidebar-subnav">
              <NavLink to="/methodology">Methodology</NavLink>
              {canAccess(user, "analyst") && <>
                <NavLink to="/hospital-price-transparency-files">Hospital Price Files</NavLink>
                <NavLink to="/reference-data-sets">Reference Data Sets</NavLink>
                <NavLink to="/hospital-file-quality">Hospital File Quality</NavLink>
              </>}
              {canAccess(user, "analyst") && <>
                <NavLink to="/data-sources">Data Sources & Import</NavLink>
              </>}
              {canAccess(user, "reviewer") && <>
                <NavLink to="/drug-selection-scope">Drug Scope</NavLink>
                <NavLink to="/drug-unit-validations">{hasRole(user, "REVIEWER") ? "Review Queue · Drug Units" : "Drug Unit Review"}</NavLink>
              </>}
              {canAccess(user, "admin") && <>
                <NavLink to="/audit-logs">Audit Logs</NavLink>
                <NavLink to="/user-management">User Management</NavLink>
              </>}
              <NavLink to="/application-settings">{canAccess(user, "admin") ? "Application Settings" : "Account Security"}</NavLink>
            </div>
          </details>
        </nav></div>
        <button className="collapse-button" type="button" onClick={() => setCollapsed((v) => !v)} aria-expanded={!collapsed}>{collapsed ? "›" : "‹"}{!collapsed && " Collapse menu"}</button>
      </aside>
      {mobileNavOpen && <button className="mobile-nav-backdrop" type="button" aria-label="Close navigation menu" onClick={() => setMobileNavOpen(false)} />}
      <div className="app-workspace">
      <header className="appbar">
        <div><div className="crumb">MeshKor Healthcare / {pageTitle}</div><h1>{pageTitle}</h1></div>
        <form className="global-search" role="search" onSubmit={submitSearch}><input aria-label="Search price comparisons" placeholder="Search hospital, payer, drug…" value={search} onChange={(e) => setSearch(e.target.value)} /><button type="submit">Search</button></form>
        <div className="account"><div><b>{user.display_name}</b><span className="muted">{user.roles?.join(", ")}</span></div><ThemeToggle theme={theme} onToggle={onToggleTheme} /><button type="button" onClick={onLogout}>Logout</button></div>
      </header>
      <main className="page-content">
        <Suspense fallback={<div className="auth-loading" role="status">Loading page…</div>}>
        <Routes>
          <Route path="/" element={<Overview user={user} />} />
          <Route path="/reference-data-sets" element={<RequirePolicy user={user} policy="analyst"><ReferenceData /></RequirePolicy>} />
          <Route path="/hospital-price-transparency-files" element={<RequirePolicy user={user} policy="analyst"><HospitalFiles /></RequirePolicy>} />
          <Route path="/medicare-part-b-drugs/:hcpcs" element={<DrugDetail user={user} />} />
          <Route path="/hospitals" element={<Hospitals user={user} />} />
          <Route path="/hospitals/:key" element={<HospitalDetail user={user} />} />
          <Route path="/drug-selection-scope" element={<RequirePolicy user={user} policy="drugScope"><DrugScope user={user} /></RequirePolicy>} />
          <Route path="/drug-unit-validations" element={<RequirePolicy user={user} policy="reviewer"><UnitValidation user={user} /></RequirePolicy>} />
          <Route path="/hospital-drug-price-comparisons" element={<Rates user={user} />} />
          <Route path="/hospital-file-quality" element={<RequirePolicy user={user} policy="analyst"><Quality /></RequirePolicy>} />
          <Route path="/data-sources" element={<RequirePolicy user={user} policy="analyst"><Sources user={user} /></RequirePolicy>} />
          <Route path="/reports" element={<Reports user={user} />} />
          <Route path="/plan-specific-audits" element={<RequirePolicy user={user} policy="planAudits">{isClientOnly(user) ? <ClientPlanAudits /> : <PlanAudits user={user} />}</RequirePolicy>} />
          <Route path="/claims-explorer" element={<RequirePolicy user={user} policy="claims"><ClaimsExplorer user={user} /></RequirePolicy>} />
          <Route path="/claims" element={<RequirePolicy user={user} policy="claims"><Navigate to="/claims-explorer" replace /></RequirePolicy>} />
          <Route path="/audit-logs" element={<RequirePolicy user={user} policy="admin"><AuditLogs /></RequirePolicy>} />
          <Route path="/user-management" element={<RequirePolicy user={user} policy="admin"><UserManagement user={user} /></RequirePolicy>} />
          <Route path="/application-settings" element={<Settings user={user} />} />
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
          <Route path="/plan-audit" element={<Navigate to="/plan-specific-audits" replace />} />
          <Route path="/method" element={<Navigate to="/methodology" replace />} />
          <Route path="/dashboard/*" element={<Navigate to="/" replace />} />
        </Routes>
        </Suspense>
      </main></div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [theme, setTheme] = useState(() => {
    try { return window.localStorage.getItem("meshkor-theme") === "dark" ? "dark" : "light"; }
    catch { return "light"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { window.localStorage.setItem("meshkor-theme", theme); } catch { /* Storage may be unavailable in private browsing. */ }
  }, [theme]);
  useEffect(() => {
    const clearInvalidSession = () => setUser(null);
    window.addEventListener("meshkor:session-expired", clearInvalidSession);
    restoreLogin()
      .then((result) => setUser(result.authenticated ? result.user : null))
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
    return () => window.removeEventListener("meshkor:session-expired", clearInvalidSession);
  }, []);
  async function signOut() {
    try { await logout(); } finally { setUser(null); }
  }
  if (checking) return <div className="auth-loading">Checking access…</div>;
  const toggleTheme = () => setTheme((current) => current === "dark" ? "light" : "dark");
  return user ? <Shell user={user} onLogout={signOut} theme={theme} onToggleTheme={toggleTheme} />
    : <Landing onLogin={setUser} theme={theme} onToggleTheme={toggleTheme} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<BrowserRouter><App /></BrowserRouter>);
