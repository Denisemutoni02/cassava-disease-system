/**
 * Local diagnosis history (per logged-in user) + hand-off of the most recent
 * result from the Upload screen to the Result screen.
 *
 * POST /diagnose is stateless — the server stores nothing — so history lives
 * in localStorage. This is a plain activity list, not offline caching: a new
 * diagnosis always needs a live connection.
 */

const HISTORY_PREFIX = 'cg_history:';
const LAST_RESULT_KEY = 'cg_last_result';
const MAX_ENTRIES = 50;

export function historyKey(user) {
  return HISTORY_PREFIX + (user?.user_id || `demo:${user?.full_name || 'guest'}`);
}

export function loadHistory(user) {
  try {
    const raw = localStorage.getItem(historyKey(user));
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

/** Persist one /diagnose response and return the updated list. */
export function addHistory(user, entry) {
  const list = [entry, ...loadHistory(user)].slice(0, MAX_ENTRIES);
  try {
    localStorage.setItem(historyKey(user), JSON.stringify(list));
  } catch {
    // storage full/blocked → history is best-effort only
  }
  return list;
}

export function clearHistory(user) {
  try {
    localStorage.removeItem(historyKey(user));
  } catch {
    /* ignore */
  }
  return [];
}

export function setLastResult(entry) {
  try {
    sessionStorage.setItem(LAST_RESULT_KEY, JSON.stringify(entry));
  } catch {
    /* ignore */
  }
}

export function getLastResult() {
  try {
    const raw = sessionStorage.getItem(LAST_RESULT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
