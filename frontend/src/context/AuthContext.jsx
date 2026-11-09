import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import api, { ApiError, getToken, setToken, tokenIsRemembered } from '../api/client';

/**
 * Session state.
 *
 * Two ways in (the brief allows mocking auth):
 * 1. Real backend login  — POST /api/v1/auth/login; the role returned by the
 *    backend is used for role-aware UI (farmer / officer).
 * 2. Demo login          — local session when the backend auth service is
 *    unreachable or absent; role is chosen on the login screen.
 *
 * The cached user object lives in the same storage as its token, so a
 * "Remember me"-off session (sessionStorage) disappears cleanly when the
 * tab closes — no half-signed-in state.
 */
const AuthContext = createContext(null);

const USER_KEY = 'cg_user';

function readStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function storeUser(user, { persist = true } = {}) {
  localStorage.removeItem(USER_KEY);
  sessionStorage.removeItem(USER_KEY);
  if (!user) return;
  (persist ? localStorage : sessionStorage).setItem(USER_KEY, JSON.stringify(user));
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(readStoredUser);
  const [loading, setLoading] = useState(() => {
    const stored = readStoredUser();
    return stored ? !stored.demo : false;
  });

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      storeUser(null);
    };
    window.addEventListener('cg:unauthorized', onUnauthorized);
    return () => window.removeEventListener('cg:unauthorized', onUnauthorized);
  }, []);

  // Re-validate a stored backend token on first load (demo sessions skip this)
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        storeUser(u, { persist: tokenIsRemembered() });
      })
      .catch((err) => {
        // Only drop the session when the token is actually rejected (401);
        // a temporary network failure must not log the farmer out.
        if (err instanceof ApiError && err.status === 401) {
          setToken(null);
          setUser(null);
          storeUser(null);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  /**
   * Real backend login. Throws ApiError / NetworkError for the caller.
   * @param {boolean} remember — false keeps the token in sessionStorage only
   *   (session ends when the tab/app closes) — the "Remember me" choice.
   */
  const login = useCallback(async (identifier, password, remember = true) => {
    const data = await api.login(identifier, password);
    setToken(data.access_token, { remember });
    const u = { ...data.user, demo: false };
    setUser(u);
    storeUser(u, { persist: remember });
    return u;
  }, []);

  /** Create a backend account; the register response logs the user in. */
  const register = useCallback(async (payload, remember = true) => {
    const data = await api.register(payload);
    setToken(data.access_token, { remember });
    const u = { ...data.user, demo: false };
    setUser(u);
    storeUser(u, { persist: remember });
    return u;
  }, []);

  /** Local demo session — no server involved. */
  const demoLogin = useCallback((identifier, role = 'farmer') => {
    const u = {
      user_id: `demo:${identifier || 'guest'}`,
      full_name: identifier || 'Guest',
      role,
      demo: true,
    };
    setToken(null);
    setUser(u);
    storeUser(u);
    return u;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    storeUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, demoLogin, logout }),
    [user, loading, login, register, demoLogin, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
