import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useNetwork } from '../context/NetworkContext';
import api, { NetworkError } from '../api/client';
import { addHistory, setLastResult } from '../lib/history';

/**
 * Home / Upload screen: pick or capture a leaf photo, optionally attach GPS,
 * then call POST {VITE_API_URL}/diagnose and hand the result to /result.
 */
export default function Upload() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { online } = useNetwork();
  const fileRef = useRef(null);
  const timerRef = useRef(null);

  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [gps, setGps] = useState(null); // {lat, lon, accuracy}
  const [gpsStatus, setGpsStatus] = useState('idle'); // idle | locating | ok | denied | unsupported
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(null); // upload checklist
  const [error, setError] = useState('');
  const [isNetworkError, setIsNetworkError] = useState(false);
  const [needLogin, setNeedLogin] = useState(false);

  useEffect(() => () => clearInterval(timerRef.current), []);

  function onPick(e) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setError('');
    setIsNetworkError(false);
    const reader = new FileReader();
    reader.onload = () => setPreview(reader.result);
    reader.readAsDataURL(f);
  }

  function locate() {
    if (!navigator.geolocation) {
      setGpsStatus('unsupported');
      return;
    }
    setGpsStatus('locating');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGps({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        setGpsStatus('ok');
      },
      () => setGpsStatus('denied'),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
  }

  async function submit(e) {
    e?.preventDefault?.();
    if (!file) {
      setError('Please choose or capture a leaf photo first.');
      return;
    }
    setBusy(true);
    setError('');
    setIsNetworkError(false);
    setNeedLogin(false);
    setStage({ uploaded: false, checked: false, inference: false, advice: false });

    const fd = new FormData();
    fd.append('file', file);
    if (gps) {
      fd.append('latitude', String(gps.lat));
      fd.append('longitude', String(gps.lon));
    }

    // Simulated checklist while the real request runs server-side
    clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setStage((s) => {
        if (!s) return s;
        if (!s.uploaded) return { ...s, uploaded: true };
        if (!s.checked) return { ...s, checked: true };
        if (!s.inference) return { ...s, inference: true };
        clearInterval(timerRef.current);
        return s;
      });
    }, 400);

    try {
      const result = await api.diagnose(fd);
      clearInterval(timerRef.current);
      setStage({ uploaded: true, checked: true, inference: true, advice: true });

      const entry = {
        id: result.diagnosis_id || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
        at: new Date().toISOString(),
        label: result.label,
        confidence: result.confidence,
        advice: result.advice,
        all_probabilities: result.all_probabilities,
        latitude: result.latitude,
        longitude: result.longitude,
        hotspot: result.hotspot_message || null,
      };
      addHistory(user, entry);
      setLastResult(entry);
      navigate('/result');
    } catch (err) {
      clearInterval(timerRef.current);
      const network = err instanceof NetworkError;
      setIsNetworkError(network);
      if (err?.status === 401) {
        setNeedLogin(true);
        setError('Please log in with a backend account to run and save diagnoses.');
      } else {
        setError(
          network
            ? err.message // "No internet connection." or "Cannot reach server. …"
            : err.detail || err.message || 'Diagnosis failed.',
        );
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <section className="card">
        <h2>New diagnosis</h2>
        <p className="muted">Fit one leaf inside the frame · daylight works best</p>

        {!online && (
          <div className="alert alert-warn">
            You are offline. Diagnosis needs an active internet connection — the
            Retry button in the banner above will resume once you are back.
          </div>
        )}
        {error && (
          <div className="alert alert-error">
            {error}
            {needLogin && (
              <>
                {' '}
                <Link to="/login" className="btn btn-retry">
                  Log in
                </Link>
              </>
            )}
            {isNetworkError && (
              <>
                {' '}
                <button type="button" className="btn btn-retry" onClick={submit}>
                  Retry
                </button>
              </>
            )}
          </div>
        )}

        <form onSubmit={submit} className="form">
          {/* Image picker: camera or gallery */}
          <div
            className={`dropzone${preview ? ' has-preview' : ''}`}
            onClick={() => fileRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
          >
            {preview ? (
              <img src={preview} alt="Selected leaf" className="preview" />
            ) : (
              <div className="dropzone-hint">
                <span aria-hidden>📷</span>
                <p>Tap to take a photo or choose from gallery</p>
                <p className="muted small">JPEG / PNG / WebP · max 8 MB</p>
              </div>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              onChange={onPick}
              hidden
            />
          </div>

          {/* Optional GPS */}
          <div className="gps-row">
            <button type="button" className="btn btn-secondary btn-sm" onClick={locate}>
              {gpsStatus === 'locating' ? 'Locating…' : '📍 Use my GPS location'}
            </button>
            {gpsStatus === 'ok' && (
              <span className="gps-ok">
                Location detected ✓ ({gps.lat.toFixed(4)}, {gps.lon.toFixed(4)})
              </span>
            )}
            {gpsStatus === 'denied' && (
              <span className="muted small">Location denied — you can still diagnose without GPS.</span>
            )}
            {gpsStatus === 'unsupported' && (
              <span className="muted small">Geolocation not supported on this device.</span>
            )}
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-block btn-lg"
            disabled={busy || !online || !file}
          >
            {busy ? 'Analysing…' : 'Submit for diagnosis'}
          </button>
          {!online && (
            <p className="muted small center">
              Reconnect to the internet to run a diagnosis.
            </p>
          )}
        </form>
      </section>

      {busy && (
        <section className="card analysis-card" aria-live="polite">
          <h3>Analysing…</h3>
          <ul className="checklist">
            <li className={stage?.uploaded ? 'done' : ''}>✓ Image uploaded</li>
            <li className={stage?.checked ? 'done' : ''}>✓ Image quality checked</li>
            <li className={stage?.inference ? 'done' : ''}>
              {stage?.inference ? '✓' : '○'} Running AI model (server)
            </li>
            <li className={stage?.advice ? 'done' : ''}>
              {stage?.advice ? '✓' : '○'} Preparing advice
            </li>
          </ul>
          <p className="muted small">Please keep this screen open. This needs an internet connection.</p>
        </section>
      )}
    </div>
  );
}
