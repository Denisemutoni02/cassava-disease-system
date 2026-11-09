/**
 * API client for the CassavaGuard PWA.
 *
 * - Backend base URL comes from VITE_API_URL (e.g. http://localhost:8000)
 * - Diagnosis goes to POST {VITE_API_URL}/diagnose  (JWT-protected, saves the row)
 * - Auth & data use {VITE_API_URL}/api/v1/...
 * - Attaches the JWT when the user logged in through the backend; storage
 *   location follows the "Remember me" choice (local vs session storage)
 * - Network failures are classified so the UI can tell the two apart:
 *     reason 'offline' → "No internet connection."
 *     reason 'server'  → "Cannot reach server. Check that the backend is running."
 *   (wrong URL, stopped backend and CORS errors all count as 'server')
 */

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
const API_V1 = `${API_URL}/api/v1`;

export { API_URL };

export const OFFLINE_MESSAGE = 'No internet connection.';
export const SERVER_MESSAGE = 'Cannot reach server. Check that the backend is running.';

export class ApiError extends Error {
  constructor(status, detail, issues = null) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
    /** Parsed FastAPI 422 payload (array of {loc, msg, type}) when present. */
    this.issues = issues;
  }
}

export class NetworkError extends Error {
  /**
   * @param {'offline'|'server'} reason — 'offline' = no internet connection,
   *   'server' = backend unreachable (stopped, wrong URL or CORS-blocked).
   */
  constructor(reason = 'offline') {
    super(reason === 'server' ? SERVER_MESSAGE : OFFLINE_MESSAGE);
    this.name = 'NetworkError';
    this.isNetwork = true;
    this.reason = reason;
  }
}

const TOKEN_KEY = 'cg_token';

/**
 * Read the JWT from either storage — "Remember me" decides where it lives:
 * checked → localStorage (survives closing the browser), unchecked →
 * sessionStorage (cleared when the tab/app closes).
 */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

/** True when the current token was stored by "Remember me" (localStorage). */
export function tokenIsRemembered() {
  return Boolean(localStorage.getItem(TOKEN_KEY));
}

/**
 * @param {string|null} token
 * @param {{remember?: boolean}} [options] — remember=true (default) stores in
 *   localStorage; remember=false stores in sessionStorage. Clearing removes
 *   the key from both.
 */
export function setToken(token, { remember = true } = {}) {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  if (!token) return;
  (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token);
}

async function request(path, { method = 'GET', body, headers = {}, isForm = false, base = API_V1, timeoutMs = 0 } = {}) {
  const finalHeaders = { ...headers };
  const token = getToken();
  if (token) finalHeaders.Authorization = `Bearer ${token}`;

  let payload = body;
  if (body && !isForm && !(body instanceof FormData)) {
    finalHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let res;
  try {
    const controller = timeoutMs ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
    try {
      res = await fetch(`${base}${path}`, {
        method,
        headers: finalHeaders,
        body: payload,
        signal: controller?.signal,
      });
    } finally {
      if (timer) clearTimeout(timer);
    }
  } catch {
    // fetch rejects on connection/DNS failure, CORS errors and aborts.
    // navigator.onLine tells us whether the device has a network at all;
    // if it does, the problem is the backend (down, wrong URL or CORS).
    const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
    throw new NetworkError(offline ? 'offline' : 'server');
  }

  if (res.status === 401 && token) {
    // Only an invalid/expired token ends the session. A 401 without a token
    // (e.g. demo mode hitting a protected route) is left to the page to
    // explain — it must not silently log the user out.
    setToken(null);
    window.dispatchEvent(new CustomEvent('cg:unauthorized'));
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!res.ok) {
    const issues = Array.isArray(data?.detail) ? data.detail : null;
    const detail = issues
      ? issues.map((i) => i.msg).join(' ')
      : typeof data?.detail === 'string'
        ? data.detail
        : data?.detail
          ? JSON.stringify(data.detail)
          : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail, issues);
  }
  return data;
}

export const api = {
  /** POST /diagnose — JWT: run inference, save the diagnosis, refresh hotspots. */
  diagnose: (formData) => request('/diagnose', { method: 'POST', body: formData, isForm: true, base: API_URL }),

  /** POST /api/v1/auth/login — optional; app falls back to demo mode. */
  login: (identifier, password) =>
    request('/auth/login', { method: 'POST', body: { identifier, password } }),

  /** POST /api/v1/auth/register — create an account, returns JWT (auto-login). */
  register: (payload) => request('/auth/register', { method: 'POST', body: payload }),

  /** GET /api/v1/auth/me — re-validates a stored backend token. */
  me: () => request('/auth/me'),

  /** GET /api/v1/history — the logged-in user's past diagnoses (paginated). */
  history: (page = 1, pageSize = 50, label = '') =>
    request(`/history?page=${page}&page_size=${pageSize}${label ? `&label=${label}` : ''}`),

  /** GET /api/v1/hotspots — current DBSCAN clusters as GeoJSON (JWT). */
  hotspots: (disease) =>
    request(`/hotspots${disease ? `?disease=${disease}` : ''}`),

  /** GET /api/v1/clusters/geojson — public alias kept for scripts/legacy. */
  clustersGeoJSON: (disease) =>
    request(`/clusters/geojson${disease ? `?disease=${disease}` : ''}`),

  /** GET /health — backend reachability probe (short timeout, null on failure). */
  health: () => request('/health', { base: API_URL, timeoutMs: 4000 }).catch(() => null),

  /** True when the backend answers /health — used to tell "offline" apart from "backend down". */
  probe: async () => (await api.health()) !== null,
};

export default api;
