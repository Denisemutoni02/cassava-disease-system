import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNetwork } from '../context/NetworkContext';
import { NetworkError, SERVER_MESSAGE } from '../api/client';
import PasswordField from '../components/PasswordField';
import { validateLoginIdentifier, validateLoginPassword } from '../lib/validators';

/**
 * Sign-in screen (online-only).
 *
 * Flow:
 * 1. Validates the identifier and password locally (inline messages).
 * 2. POST /api/v1/auth/login — success stores the JWT (Remember me decides
 *    localStorage vs sessionStorage) and returns to the page the user came
 *    from (or the upload screen).
 * 3. Failure causes are kept apart:
 *    - 401 → "Incorrect identifier or password."
 *    - device has no network → "No internet connection…" (no offline login)
 *    - backend unreachable / wrong VITE_API_URL → "Cannot reach server…" with
 *      an explicit "Continue in demo mode" escape hatch
 * 4. "Don't have an account? Register" opens the /register screen.
 */
export default function Login() {
  const { user, login, demoLogin } = useAuth();
  const { online } = useNetwork();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || '/';

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState('');
  const [showDemoButton, setShowDemoButton] = useState(false);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={from} replace />;

  function clearFieldError(name) {
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: '' } : prev));
  }

  function enterDemo() {
    demoLogin(identifier.trim() || 'guest');
    navigate(from, { replace: true });
  }

  async function submit(e) {
    e.preventDefault();
    setError('');
    setShowDemoButton(false);

    // Client-side validation — errors render inline, no request is sent.
    const nextErrors = {
      identifier: validateLoginIdentifier(identifier),
      password: validateLoginPassword(password),
    };
    if (nextErrors.identifier || nextErrors.password) {
      setFieldErrors(nextErrors);
      return;
    }
    setFieldErrors({});

    // Sign-in is online-only; the banner above already reports no network.
    if (!online) {
      setError('No internet connection. Connect to Wi-Fi or mobile data to sign in.');
      return;
    }

    setBusy(true);
    try {
      await login(identifier.trim(), password, remember);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof NetworkError) {
        setError(err.message); // "No internet connection." / "Cannot reach server. …"
        if (err.reason === 'server') setShowDemoButton(true);
      } else if (err?.status === 404 || err?.status === 405) {
        setError(SERVER_MESSAGE); // server answered, but not this API
        setShowDemoButton(true);
      } else if (err?.status === 401 || err?.status === 403) {
        setError(err.detail || 'Incorrect phone/email or password.');
      } else {
        setError(err?.detail || 'Sign-in failed. Please try again.');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-hero">
          <span className="auth-leaf" aria-hidden>
            🌿
          </span>
          <p className="auth-brand">CassavaGuard</p>
          <h1>Cassava Disease Detection</h1>
          <p>Detect CMD &amp; CBSD from a leaf photo — anywhere in the field</p>
        </div>

        {!online && (
          <div className="alert alert-warn" role="status">
            No internet connection. Sign-in needs Wi-Fi or mobile data.
          </div>
        )}
        {error && (
          <div className="alert alert-error" role="alert">
            {error}
            {showDemoButton && (
              <>
                {' '}
                <button type="button" className="btn btn-retry" onClick={enterDemo}>
                  Continue in demo mode
                </button>
              </>
            )}
          </div>
        )}

        <form onSubmit={submit} className="form" noValidate>
          <label htmlFor="login-identifier">
            Email or phone
            <input
              id="login-identifier"
              value={identifier}
              onChange={(e) => {
                setIdentifier(e.target.value);
                clearFieldError('identifier');
              }}
              placeholder="name@example.com  or  +256 7xx xxx xxx"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={fieldErrors.identifier ? true : undefined}
              disabled={busy}
            />
            {fieldErrors.identifier && (
              <span className="field-error" role="alert">
                {fieldErrors.identifier}
              </span>
            )}
          </label>

          <PasswordField
            id="login-password"
            label="Password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              clearFieldError('password');
            }}
            autoComplete="current-password"
            error={fieldErrors.password}
            required
          />

          <div className="check-row">
            <input
              id="remember-me"
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <label htmlFor="remember-me" className="check-label">
              Remember me
            </label>
          </div>

          <button
            className="btn btn-primary btn-block btn-lg"
            disabled={busy}
            aria-busy={busy}
          >
            {busy && <span className="btn-spinner" aria-hidden />}
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="auth-switch">
          Don&rsquo;t have an account? <Link to="/register">Register</Link>
        </p>
        <p className="auth-foot">
          Demo account: <code>farmer1@example.com</code> / <code>Farmer@123</code>
        </p>
      </div>
    </div>
  );
}
