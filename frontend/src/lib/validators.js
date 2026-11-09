/**
 * Client-side validation for the sign-in and register screens.
 *
 * Each validator returns '' when the value is acceptable, or a short
 * human-readable message that is shown inline under the field. Rules mirror
 * the backend (RegisterRequest / LoginRequest) so users never hit a raw 422.
 */

// Backend phone pattern: ^\+?[0-9\s\-]{7,20}$
const PHONE_RE = /^\+?[0-9\s\-]{7,20}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export function isEmail(value) {
  return EMAIL_RE.test(value.trim());
}

export function isPhone(value) {
  return PHONE_RE.test(value.trim());
}

/** Sign-in: identifier may be an email or a phone number. */
export function validateLoginIdentifier(value) {
  const v = (value || '').trim();
  if (!v) return 'Enter your phone number or email.';
  if (v.length < 3) return 'Enter at least 3 characters.';
  if (v.includes('@') && !isEmail(v)) return 'Enter a valid email address, e.g. name@example.com.';
  return '';
}

/** Sign-in: only require the password to be present — the server decides
 *  whether the credentials are right (never block a correct password). */
export function validateLoginPassword(value) {
  if (!value) return 'Enter your password.';
  return '';
}

/** Register: full name (2–120 chars, like the backend). */
export function validateName(value) {
  const v = (value || '').trim();
  if (!v) return 'Enter your full name.';
  if (v.length < 2) return 'Full name must be at least 2 characters.';
  if (v.length > 120) return 'Full name must be 120 characters or fewer.';
  return '';
}

/** Register: email OR phone — strict format, both accepted. */
export function validateContact(value) {
  const v = (value || '').trim();
  if (!v) return 'Enter your email address or phone number.';
  if (v.includes('@')) {
    return isEmail(v) ? '' : 'Enter a valid email address, e.g. name@example.com.';
  }
  return isPhone(v) ? '' : 'Enter a valid phone number, e.g. +256 772 000 000.';
}

/** Register: new passwords must be strong enough (server floor is 6 chars). */
export function validatePassword(value) {
  if (!value) return 'Choose a password.';
  if (value.length < 6) return 'Password must be at least 6 characters.';
  if (!/[A-Za-z]/.test(value) || !/[0-9]/.test(value)) {
    return 'Weak password — use at least 6 characters with letters and numbers.';
  }
  if (value.length > 128) return 'Password must be 128 characters or fewer.';
  return '';
}

/** Register: confirm-password match. */
export function validatePasswordConfirm(password, confirm) {
  if (!confirm) return 'Confirm your password.';
  if (password !== confirm) return 'Passwords do not match.';
  return '';
}
