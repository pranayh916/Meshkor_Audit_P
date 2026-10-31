import { useEffect, useState } from "react";

const API_ROOT = import.meta.env.VITE_API_BASE_URL || "/api/v1";
let accessToken = null;
const API_ENDPOINTS = Object.freeze({
  csrfToken: "authentication/csrf-token",
  signIn: "authentication/sign-in",
  totpStatus: "authentication/totp/status",
  totpSetup: "authentication/totp/setup",
  totpConfirmation: "authentication/totp/confirmation",
  totpSignInVerification: "authentication/totp/sign-in-verification",
  refreshAccessToken: "authentication/access-token/refresh",
  signOut: "authentication/sign-out",
  currentUser: "authentication/current-user",
  sourceUpload: "data-sources/uploads/",
  hospitalDrugPriceComparisonsCsv: "hospital-drug-price-comparisons/exports/csv/",
});

function csrfCookie() {
  return document.cookie.split(";").map((v) => v.trim()).find((v) => v.startsWith("csrftoken="))?.slice(10) || "";
}

async function request(path, options = {}) {
  const method = options.method || "GET";
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) headers["X-CSRFToken"] = csrfCookie();
  const rawPath = path;
  const queryIndex = rawPath.indexOf("?");
  const endpoint = queryIndex < 0 ? rawPath : rawPath.slice(0, queryIndex);
  const query = queryIndex < 0 ? "" : rawPath.slice(queryIndex);
  const cleanPath = endpoint.split("/").filter(Boolean).join("/");
  const res = await fetch(`${API_ROOT}/${cleanPath}/${query}`, {
    ...options, method, headers, credentials: "same-origin",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(body.error || `${res.status} ${res.statusText}`);
    error.status = res.status;
    error.retryAfterSeconds = Number(body.retry_after_seconds) || 0;
    throw error;
  }
  return body;
}

export async function getJSON(path, params) {
  const qs = params ? "?" + new URLSearchParams(clean(params)).toString() : "";
  return request(path + qs);
}

export async function login(username, password) {
  await request(API_ENDPOINTS.csrfToken);
  const result = await request(API_ENDPOINTS.signIn, { method: "POST", body: JSON.stringify({ username, password }) });
  accessToken = result.access;
  return result;
}

export async function completeOtpLogin(challenge, code, recoveryCode = "") {
  const result = await request(API_ENDPOINTS.totpSignInVerification, {
    method: "POST", body: JSON.stringify({ challenge, code, recovery_code: recoveryCode }),
  });
  accessToken = result.access;
  return result;
}

export async function startOtpEnrollment(challenge) {
  return request(API_ENDPOINTS.totpSetup, {
    method: "POST", body: JSON.stringify({ challenge }),
  });
}

export async function confirmOtpEnrollment(challenge, code) {
  const result = await request(API_ENDPOINTS.totpConfirmation, {
    method: "POST", body: JSON.stringify({ challenge, code }),
  });
  accessToken = result.access;
  return result;
}

export async function restoreLogin() {
  await request(API_ENDPOINTS.csrfToken);
  try {
    const result = await request(API_ENDPOINTS.refreshAccessToken, { method: "POST", body: "{}" });
    accessToken = result.access;
    return request(API_ENDPOINTS.currentUser);
  } catch {
    accessToken = null;
    return { authenticated: false };
  }
}

export async function logout() {
  try { return await request(API_ENDPOINTS.signOut, { method: "POST", body: "{}" }); }
  finally { accessToken = null; }
}

export async function uploadSource(sourceKey, file, metadata = {}) {
  await request(API_ENDPOINTS.csrfToken);
  const form = new FormData();
  form.append("source_key", sourceKey);
  form.append("file", file);
  if (metadata.system) form.append("system", metadata.system);
  if (metadata.snapshotDate) form.append("snapshot_date", metadata.snapshotDate);
  const headers = { "X-CSRFToken": csrfCookie() };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(`${API_ROOT}/${API_ENDPOINTS.sourceUpload}`, {
    method: "POST", body: form, credentials: "same-origin",
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status} ${response.statusText}`);
  return body;
}

export async function postJSON(path, body = {}) {
  return request(path, { method: "POST", body: JSON.stringify(body) });
}

export function csvUrl(params) {
  return `${API_ROOT}/${API_ENDPOINTS.hospitalDrugPriceComparisonsCsv}?${new URLSearchParams(clean(params)).toString()}`;
}

export async function downloadFile(path, filename) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${API_ROOT}/${path}`, { headers, credentials: "same-origin" });
  if (!res.ok) throw new Error(`Download failed: ${res.statusText}`);
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

function clean(p) {
  if (!p) return {};
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v != null));
}

/** Fetch on mount and whenever `deps` change. */
export function useApi(path, params, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    set((s) => ({ ...s, loading: true }));
    getJSON(path, params)
      .then((data) => live && set({ data, error: null, loading: false }))
      .catch((error) => live && set({ data: null, error, loading: false }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(clean(params)), ...deps]);
  return state;
}

export const fmt = {
  x: (v) => (v == null ? "—" : `${v.toFixed(2)}×`),
  usd: (v) => (v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD",
    maximumFractionDigits: v < 10 ? 3 : 2 })),
  n: (v) => (v == null ? "—" : v.toLocaleString("en-US")),
  pct: (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`),
};

export const STATUS_TEXT = {
  ok: "Compared",
  review_range: "Check by hand (outside configured review range)",
  unit_unresolved: "Unit not convertible",
  billing_unit_mismatch: "ASP unit differs from config",
  missing_asp: "ASP quarter unavailable",
  no_benchmark: "No ASP benchmark",
  percent_of_charges: "% of charges only",
  algorithm_only: "Formula only",
};

export const PRICE_TYPE_TEXT = {
  negotiated_dollar: "Negotiated $",
  estimated_amount: "Estimated $",
  median_allowed: "Median allowed $",
  cash: "Cash price",
  gross_charge: "Gross charge",
  contract_terms: "Contract terms",
};
