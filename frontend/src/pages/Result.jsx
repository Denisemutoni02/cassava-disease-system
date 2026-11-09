import { Link } from 'react-router-dom';
import { getLastResult } from '../lib/history';

const LABEL_BADGE = {
  CMD: 'badge badge-cmd',
  CBSD: 'badge badge-cbsd',
  Healthy: 'badge badge-healthy',
};

const LABEL_TITLE = {
  CMD: 'Cassava Mosaic Disease (CMD)',
  CBSD: 'Cassava Brown Streak Disease (CBSD)',
  Healthy: 'Leaf appears Healthy',
};

/** Result of POST /diagnose: label, confidence, advice, probabilities, GPS. */
export default function Result() {
  const r = getLastResult();

  if (!r) {
    return (
      <div className="page">
        <section className="card">
          <h2>No diagnosis to show</h2>
          <p className="muted">
            Start a new diagnosis and the result will appear here.
          </p>
          <Link to="/diagnose" className="btn btn-primary btn-block">
            New diagnosis
          </Link>
        </section>
      </div>
    );
  }

  const pct = Math.round(r.confidence * 100);
  const probs = r.all_probabilities || { [r.label]: r.confidence };
  const lowConfidence = pct < 70;

  return (
    <div className="page">
      <section className={`card result-card${lowConfidence ? ' warn' : ''}`}>
        <h2>
          {r.label === 'Healthy' ? '✅' : '🍂'} {LABEL_TITLE[r.label] || r.label}
        </h2>

        <div className="result-meta">
          <span className={LABEL_BADGE[r.label] || 'badge badge-uncertain'}>{r.label}</span>
          <span className="confidence">
            Confidence <strong>{pct}%</strong>
          </span>
          {r.latitude != null && r.longitude != null && (
            <span className="gps-ok" title="Diagnosis tagged with your GPS location">
              📍 {r.latitude.toFixed(4)}, {r.longitude.toFixed(4)}
            </span>
          )}
        </div>

        {r.hotspot && (
          <div className="alert alert-warn">
            🗺️ {r.hotspot} <Link to="/map">View the hotspot map</Link>
          </div>
        )}

        {r.advice && (
          <div className="advice">
            <h3>Risk advice</h3>
            <pre className="advice-text">{r.advice}</pre>
          </div>
        )}

        <div className="probs">
          <h3>Model scores</h3>
          {Object.entries(probs)
            .sort((a, b) => b[1] - a[1])
            .map(([name, p]) => (
              <div className="prob-row" key={name}>
                <span className="prob-label">{name}</span>
                <span className="prob-track">
                  <span
                    className={`prob-fill prob-${name.toLowerCase()}`}
                    style={{ width: `${Math.max(2, Math.round(p * 100))}%` }}
                  />
                </span>
                <span className="prob-value">{Math.round(p * 100)}%</span>
              </div>
            ))}
        </div>
      </section>

      <div className="btn-row">
        <Link to="/map" className="btn btn-primary btn-block">
          🗺️ View hotspot map
        </Link>
        <Link to="/diagnose" className="btn btn-secondary btn-block">
          New diagnosis
        </Link>
        <Link to="/history" className="btn btn-ghost btn-block">
          History
        </Link>
      </div>
    </div>
  );
}
