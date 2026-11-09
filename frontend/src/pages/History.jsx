import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNetwork } from '../context/NetworkContext';
import api, { NetworkError } from '../api/client';
import { clearHistory, loadHistory, setLastResult } from '../lib/history';

const LABEL_BADGE = {
  CMD: 'badge badge-cmd',
  CBSD: 'badge badge-cbsd',
  Healthy: 'badge badge-healthy',
};

/** Map a GET /api/v1/history row to the local entry shape used by /result. */
function fromServer(d) {
  return {
    id: d.diagnosis_id,
    at: d.inferred_at,
    label: d.disease_label,
    confidence: d.confidence_score,
    advice: d.advice?.advice_text || null,
    latitude: d.latitude,
    longitude: d.longitude,
  };
}

/**
 * Diagnosis history for the logged-in user.
 * Primary source: GET /api/v1/history (server-side, saved by /diagnose).
 * Fallback: this device's localStorage — used when offline, the backend is
 * unreachable, or the session is demo-only (401).
 */
export default function History() {
  const { user } = useAuth();
  const { online } = useNetwork();
  const navigate = useNavigate();
  const [label, setLabel] = useState('');
  const [serverItems, setServerItems] = useState(null); // null = not loaded yet
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0); // re-render after clear

  useEffect(() => {
    let alive = true;
    if (!online) {
      setServerItems(null);
      setNotice('');
      setLoading(false);
      return () => {};
    }
    setLoading(true);
    api
      .history(1, 50)
      .then((page) => {
        if (alive) {
          setServerItems((page.items || []).map(fromServer));
          setNotice('');
        }
      })
      .catch((err) => {
        if (!alive) return;
        setServerItems(null);
        setNotice(
          err instanceof NetworkError
            ? err.message
            : err?.status === 401
              ? 'Please log in with a backend account to see your saved diagnoses. Showing this device only.'
              : '',
        );
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [online, tick]);

  const localItems = useMemo(() => {
    void tick;
    return loadHistory(user);
  }, [user, tick]);

  // Server rows are authoritative; add local-only entries (demo runs or
  // diagnoses made while offline) that are not already on the server.
  const items = useMemo(() => {
    const merged = [...(serverItems || [])];
    const seen = new Set(merged.map((d) => d.id));
    for (const entry of localItems) {
      if (!seen.has(entry.id)) merged.push(entry);
    }
    return merged;
  }, [serverItems, localItems]);

  const filtered = label ? items.filter((d) => d.label === label) : items;

  function open(entry) {
    setLastResult(entry);
    navigate('/result');
  }

  return (
    <div className="page">
      <section className="card">
        <h2>Diagnosis history</h2>
        <p className="muted small">
          {loading
            ? 'Loading…'
            : serverItems
              ? `${items.length} diagnosis(es) · from your account${
                  items.length > serverItems.length ? ` (+${items.length - serverItems.length} on this device)` : ''
                }`
              : `Stored on this device · ${items.length} diagnosis(es)`}
        </p>
        {notice && <div className="alert alert-warn">{notice}</div>}

        <div className="filter-row">
          <select value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Filter by label">
            <option value="">All labels</option>
            <option value="CMD">CMD</option>
            <option value="CBSD">CBSD</option>
            <option value="Healthy">Healthy</option>
            <option value="Uncertain">Uncertain</option>
          </select>
          {!serverItems && items.length > 0 && (
            <button
              type="button"
              className="chip"
              onClick={() => {
                clearHistory(user);
                setTick((t) => t + 1);
              }}
            >
              Clear
            </button>
          )}
        </div>

        {filtered.length === 0 ? (
          <p className="muted">
            {items.length === 0
              ? 'No diagnoses yet — take your first leaf photo!'
              : 'No diagnoses match this filter.'}
          </p>
        ) : (
          <ul className="list">
            {filtered.map((d) => (
              <li key={d.id}>
                <button type="button" className="list-row list-btn" onClick={() => open(d)}>
                  <span className={LABEL_BADGE[d.label] || 'badge badge-uncertain'}>
                    {d.label}
                  </span>
                  <span>{Math.round(d.confidence * 100)}%</span>
                  <span className="muted small">
                    {new Date(d.at).toLocaleString(undefined, {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </span>
                  {d.latitude != null && <span title="GPS tagged">📍</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link to="/diagnose" className="btn btn-primary btn-block">
        + New diagnosis
      </Link>
    </div>
  );
}
