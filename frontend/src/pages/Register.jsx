import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNetwork } from '../context/NetworkContext';
import { NetworkError, SERVER_MESSAGE } from '../api/client';
import PasswordField from '../components/PasswordField';
import {
  validateContact,
  validateName,
  validatePassword,
  validatePasswordConfirm,
} from '../lib/validators';

/**
 * Registration screen — opened from "Don't have an account? Register".
 *
 * Collects only the essentials (full name, email or phone, password +
 * confirm, role) and validates everything before sending. On success the
 * backend returns a JWT immediately (auto sign-in) — a short confirmation is
 * shown and the app opens on the upload screen.
 *
 * Server-side failures stay friendly: 409 → "An account with this phone
 * number or email already exists.", network problems → the same clear
 * messages as the sign-in screen. Registration is online-only.
 */
export default function Register() {
  const { user, register } = useAuth();
  const { online } = useNetwork();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || '/';

  const [fullName, setFullName] = useState('');
  const [contact, setContact] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [role, setRole] = useState('farmer');
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(false);

  if (user) return <Navigate to={from} replace />;

  function clearFieldError(name) {
    setFieldErrors((prev) => (prev[name] ? { ...prev, [name]: '' } : prev));
  }

  async function submit(e) {
    e.preventDefault();
    setError('');

    // Client-side validation — every message renders under its field.
    const nextErrors = {
      name: validateName(fullName),
      identifier: validateContact(contact),
      password: validatePassword(password),
      confirm: validatePasswordConfirm(password, confirm),
    };
    if (Object.values(nextErrors).some(Boolean)) {
      setFieldErrors(nextErrors);
      return;
    }
    setFieldErrors({});

    if (!online) {
      setError('No internet connection. Registration needs Wi-Fi or mobile data.');
      return;
    }

    setBusy(true);
    try {
      const value = contact.trim();
      await register(
        {
          full_name: fullName.trim(),
          password,
          role,
          ...(value.includes('@') ? { email: value } : { phone: value }),
        },
        true, // remember the new session (auto sign-in)
      );
      setCreated(true);
      setTimeout(() => navigate(from, { replace: true }), 700);
    } catch (err) {
      if (err instanceof NetworkError) {
        setError(err.message);
      } else if (err?.status === 404 || err?.status === 405) {
        setError(SERVER_MESSAGE);
      } else if (err?.status === 409) {
        setError(err.detail || 'An account with this phone number or email already exists.');
      } else {
        setError(err?.detail || 'Registration failed. Please try again.');
      }
    } finally {
      setBusy(false);
    }
  }

  const pending = busy || created;

  return (
    <div className="auth-page">
      <div className="auth-card">
        <Link to="/login" className="auth-back">
          ← Back to sign in
        </Link>

        <div className="auth-hero">
          <span className="auth-leaf" aria-hidden>
            🌱
          </span>
          <p className="auth-brand">CassavaGuard · MuZARDI</p>
          <h1>Create your account</h1>
          <p>Save your diagnoses, review history and see nearby hotspots</p>
        </div>

        {!online && (
          <div className="alert alert-warn" role="status">
            No internet connection. Registration needs Wi-Fi or mobile data.
          </div>
        )}
        {created && (
          <div className="alert alert-ok" role="status">
            Account created — signing you in…
          </div>
        )}
        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}

        <form onSubmit={submit} className="form" noValidate>
          <label htmlFor="reg-name">
            Full name
            <input
              id="reg-name"
              value={fullName}
              onChange={(e) => {
                setFullName(e.target.value);
                clearFieldError('name');
              }}
              placeholder="e.g. Peter Okello"
              autoComplete="name"
              maxLength={120}
              aria-invalid={fieldErrors.name ? true : undefined}
              disabled={pending}
            />
            {fieldErrors.name && (
              <span className="field-error" role="alert">
                {fieldErrors.name}
              </span>
            )}
          </label>

          <label htmlFor="reg-identifier">
            Email or phone
            <input
              id="reg-identifier"
              value={contact}
              onChange={(e) => {
                setContact(e.target.value);
                clearFieldError('identifier');
              }}
              placeholder="name@example.com  or  +256 7xx xxx xxx"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              aria-invalid={fieldErrors.identifier ? true : undefined}
              disabled={pending}
            />
            {fieldErrors.identifier && (
              <span className="field-error" role="alert">
                {fieldErrors.identifier}
              </span>
            )}
          </label>

          <PasswordField
            id="reg-password"
            label="Password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              clearFieldError('password');
              if (confirm) clearFieldError('confirm');
            }}
            autoComplete="new-password"
            error={fieldErrors.password}
            hint="At least 6 characters, with letters and numbers."
            required
          />

          <PasswordField
            id="reg-confirm"
            label="Confirm password"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              clearFieldError('confirm');
            }}
            autoComplete="new-password"
            error={fieldErrors.confirm}
            required
          />

          <label htmlFor="reg-role">
            Role
            <select
              id="reg-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              disabled={pending}
            >
              <option value="farmer">Farmer</option>
              <option value="officer">Extension officer</option>
            </select>
          </label>

          <button
            className="btn btn-primary btn-block btn-lg"
            disabled={pending}
            aria-busy={pending}
          >
            {pending && <span className="btn-spinner" aria-hidden />}
            {created ? 'Account created' : busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
        <p className="auth-foot">
          Admin accounts are provisioned by MuZARDI. Accounts created here are
          farmers or extension officers.
        </p>
      </div>
    </div>
  );
}
