import { useEffect, useState } from "react";

const API_ROOT = import.meta.env.VITE_API_BASE_URL || "/api/v1";
let accessToken = null;
let refreshPromise = null;
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

function httpErrorMessage(status, statusText, serverMessage) {
  if (status >= 500) return "The service could not complete your request. Please try again.";
  if (serverMessage) return serverMessage;
  if (status === 401) return "Your session has expired. Sign in again to continue.";
  if (status === 403) return "The request could not be verified. Refresh the page and try again.";
  return `${status} ${statusText}`;
}

function csrfCookie() {
  return document.cookie.split(";").map((v) => v.trim()).find((v) => v.startsWith("csrftoken="))?.slice(10) || "";
}

function refreshAccess() {
  if (!refreshPromise) {
    refreshPromise = request(API_ENDPOINTS.refreshAccessToken, {
      method: "POST", body: "{}",
    }, { skipBearer: true, retryAuth: false })
      .then((refreshed) => {
        accessToken = refreshed.access;
        if (!accessToken) throw new Error("The session refresh did not return an access token.");
        return refreshed;
      })
      .catch((error) => {
        accessToken = null;
        window.dispatchEvent(new Event("meshkor:session-expired"));
        throw error;
      })
      .finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

async function fetchWithAuth(url, options = {}, retryAuth = true) {
  const tokenUsed = accessToken;
  const headers = { ...(options.headers || {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const response = await fetch(url, { ...options, headers });
  if (response.status !== 401 || !accessToken) return response;
  if (!retryAuth) {
    accessToken = null;
    window.dispatchEvent(new Event("meshkor:session-expired"));
    return response;
  }
  // A parallel request may already have refreshed the token while this 401 was in flight.
  if (tokenUsed !== accessToken) return fetchWithAuth(url, options, false);
  try {
    await refreshAccess();
    return fetchWithAuth(url, options, false);
  } catch {
    return response;
  }
}

async function request(path, options = {}, { skipBearer = false, retryAuth = true } = {}) {
  const method = options.method || "GET";
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (accessToken && !skipBearer) headers.Authorization = `Bearer ${accessToken}`;
  if (!["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) headers["X-CSRFToken"] = csrfCookie();
  const rawPath = path;
  const queryIndex = rawPath.indexOf("?");
  const endpoint = queryIndex < 0 ? rawPath : rawPath.slice(0, queryIndex);
  const query = queryIndex < 0 ? "" : rawPath.slice(queryIndex);
  const cleanPath = endpoint.split("/").filter(Boolean).join("/");
  const canRefresh = ![
    API_ENDPOINTS.csrfToken, API_ENDPOINTS.signIn, API_ENDPOINTS.totpSetup,
    API_ENDPOINTS.totpConfirmation, API_ENDPOINTS.totpSignInVerification,
    API_ENDPOINTS.refreshAccessToken, API_ENDPOINTS.signOut,
  ].includes(cleanPath);
  const res = await fetch(`${API_ROOT}/${cleanPath}/${query}`, {
    ...options, method, headers, credentials: "same-origin",
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(httpErrorMessage(res.status, res.statusText, body.error));
    error.status = res.status;
    error.code = body.code;
    error.retryAfterSeconds = Number(body.retry_after_seconds) || 0;
    if (res.status === 401 && accessToken && cleanPath !== API_ENDPOINTS.refreshAccessToken) {
      if (retryAuth && canRefresh) {
        try {
          await refreshAccess();
          return request(path, options, { retryAuth: false });
        } catch {
          throw error;
        }
      }
      if (!retryAuth) {
        accessToken = null;
        window.dispatchEvent(new Event("meshkor:session-expired"));
      }
    }
    throw error;
  }
  return body;
}

export async function getJSON(path, params) {
  const qs = params ? "?" + new URLSearchParams(clean(params)).toString() : "";
  return request(path + qs);
}

export async function getAllPages(path, params = {}) {
  const first = await getJSON(path, { ...params, page: 1 });
  if (Array.isArray(first)) return first;
  const items = [...(first.results || [])];
  let page = first.next;
  while (page != null) {
    const result = await getJSON(path, { ...params, page, page_size: first.page_size });
    items.push(...(result.results || []));
    page = result.next;
  }
  return items;
}

export async function login(username, password) {
  accessToken = null;
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
  const response = await fetchWithAuth(`${API_ROOT}/${API_ENDPOINTS.sourceUpload}`, {
    method: "POST", body: form, credentials: "same-origin",
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(httpErrorMessage(response.status, response.statusText, body.error));
  return body;
}

export async function postJSON(path, body = {}) {
  return request(path, { method: "POST", body: JSON.stringify(body) });
}

export function csvUrl(params) {
  return `${API_ROOT}/${API_ENDPOINTS.hospitalDrugPriceComparisonsCsv}?${new URLSearchParams(clean(params)).toString()}`;
}

export async function downloadFile(path, filename) {
  const res = await fetchWithAuth(`${API_ROOT}/${path}`, { credentials: "same-origin" });
  if (!res.ok) throw new Error(httpErrorMessage(res.status, res.statusText, "The download could not be completed."));
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

function clean(p) {
  if (!p) return {};
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v != null));
}

/** Fetch on mount and whenever `deps` change. */
export function useApi(path, params, deps = []) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    if (!path) {
      set({ data: null, error: null, loading: false });
      return;
    }
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
  x: (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v).toFixed(2)}×`),
  usd: (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD",
    maximumFractionDigits: Number(v) < 10 ? 3 : 2 })),
  n: (v) => (v == null ? "—" : v.toLocaleString("en-US")),
  pct: (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v) > 0 ? "+" : ""}${Number(v).toFixed(0)}%`),
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

async function uploadForm(path, form) {
  await request(API_ENDPOINTS.csrfToken);
  const cleanPath = path.split("/").filter(Boolean).join("/");
  const headers = { "X-CSRFToken": csrfCookie() };
  const response = await fetchWithAuth(API_ROOT + "/" + cleanPath + "/", {
    method: "POST", body: form, credentials: "same-origin", headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(httpErrorMessage(response.status, response.statusText, body.error));
    error.payload = body;
    throw error;
  }
  return body;
}

export async function uploadPlanSummary(organizationId, planId, summaryFile, manifestFile) {
  if (!summaryFile || !manifestFile) throw new Error("Choose both the aggregate CSV and its manifest.");
  const form = new FormData();
  form.append("organization_id", String(organizationId));
  form.append("plan_id", String(planId));
  form.append("file", summaryFile);
  form.append("manifest", manifestFile);
  return uploadForm("plan-audits/import-summary/", form);
}

export async function uploadNetworkRoster(planId, rosterFile) {
  if (!rosterFile) throw new Error("Choose a network roster CSV.");
  const form = new FormData();
  form.append("file", rosterFile);
  return uploadForm("plans/" + planId + "/network-roster/", form);
}

export async function patchJSON(path, body = {}) {
  return request(path, { method: "PATCH", body: JSON.stringify(body) });
}

export async function deleteJSON(path) {
  return request(path, { method: "DELETE" });
}
