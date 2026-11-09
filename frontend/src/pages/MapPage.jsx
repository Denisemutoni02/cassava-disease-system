import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import LeafletMap from '../components/LeafletMap';
import { useNetwork } from '../context/NetworkContext';
import api from '../api/client';

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'CMD', label: 'CMD' },
  { value: 'CBSD', label: 'CBSD' },
];

/**
 * Hotspot map: Leaflet + OpenStreetMap with DBSCAN cluster GeoJSON loaded
 * from the backend (GET /api/v1/hotspots, JWT). If the data is unreachable
 * the map still renders with the user's location.
 */
export default function MapPage() {
  const { online, recheck } = useNetwork();
  const [geojson, setGeojson] = useState({ type: 'FeatureCollection', features: [] });
  const [filter, setFilter] = useState('');
  const [userPos, setUserPos] = useState(null);
  const [error, setError] = useState('');
  const [needLogin, setNeedLogin] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!online) {
      setLoading(false);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    setNeedLogin(false);
    api
      .hotspots(filter || undefined)
      .then(setGeojson)
      .catch((e) => {
        if (e?.status === 401) {
          setNeedLogin(true);
          setError('Please log in with a backend account to view hotspot clusters.');
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  }, [filter, online]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => setUserPos([pos.coords.latitude, pos.coords.longitude]),
        () => {},
        { maximumAge: 120000, timeout: 10000 },
      );
    }
  }, []);

  const features = geojson.features || [];
  const counts = features.reduce(
    (acc, f) => {
      const k = f.properties.dominant_disease;
      acc[k] = (acc[k] || 0) + f.properties.member_count;
      return acc;
    },
    { CMD: 0, CBSD: 0 },
  );

  return (
    <div className="page">
      <section className="card map-header">
        <h2>Hotspot map</h2>
        <p className="muted">
          DBSCAN clusters of confident CMD/CBSD diagnoses · updated after each
          positive case
        </p>

        <div className="stat-row">
          <span className="badge badge-cmd">{counts.CMD} CMD cases</span>
          <span className="badge badge-cbsd">{counts.CBSD} CBSD cases</span>
          <span className="badge badge-uncertain">{features.length} clusters</span>
        </div>

        <div className="filter-row">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className={`chip${filter === f.value ? ' active' : ''}`}
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
          <span className="legend" aria-label="Risk legend">
            <i className="dot" style={{ background: '#d73027' }} /> High
            <i className="dot" style={{ background: '#fc8d59' }} /> Emerging
            <i className="dot" style={{ background: '#fee090' }} /> Low
          </span>
        </div>
      </section>

      {!online && (
        <div className="alert alert-warn">
          You are offline. The map needs an internet connection for tiles and
          cluster data.{' '}
          <button type="button" className="btn btn-retry" onClick={recheck}>
            Retry
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          Hotspot data is unavailable right now ({error}).{' '}
          {needLogin && (
            <Link to="/login" className="btn btn-retry">
              Log in
            </Link>
          )}{' '}
          <button type="button" className="btn btn-retry" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {!loading && online && !error && features.length === 0 && (
        <div className="alert alert-ok">
          No outbreak clusters mapped yet — your location marker is on the map.
        </div>
      )}

      <LeafletMap geojson={geojson} userPosition={userPos} height="62vh" />

      <p className="muted small center">
        Map data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>{' '}
        contributors
        {userPos && <span> · 📍 your location shown</span>}
      </p>

      {features.length > 0 && (
        <section className="card">
          <h3>Clusters</h3>
          <ul className="list">
            {features.map((f) => {
              const p = f.properties;
              return (
                <li key={p.cluster_id} className="list-row wrap">
                  <span className={`badge badge-${String(p.dominant_disease).toLowerCase()}`}>
                    {p.dominant_disease}
                  </span>
                  <span>
                    {p.member_count} cases · ~{Math.round(p.radius_m)} m
                  </span>
                  <span className={`risk risk-${String(p.risk_level).toLowerCase()}`}>
                    {p.risk_level}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {loading && <p className="muted center">Loading clusters…</p>}
    </div>
  );
}
