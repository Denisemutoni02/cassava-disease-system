import { useState } from 'react';

/**
 * Password input with a Show/Hide toggle (large touch target for field use),
 * inline error and optional hint. Label is rendered above the input, matching
 * the rest of the auth forms.
 */
export default function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete = 'current-password',
  error = '',
  hint = '',
  required = false,
}) {
  const [show, setShow] = useState(false);

  return (
    <label htmlFor={id}>
      {label}
      <span className="input-wrap">
        <input
          id={id}
          type={show ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          autoComplete={autoComplete}
          aria-invalid={error ? true : undefined}
          required={required}
        />
        <button
          type="button"
          className="pw-toggle"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={show}
        >
          {show ? 'Hide' : 'Show'}
        </button>
      </span>
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </label>
  );
}
