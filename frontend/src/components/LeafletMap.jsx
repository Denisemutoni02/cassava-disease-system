import { MapContainer, TileLayer, CircleMarker, Circle, Popup, Marker, useMap } from 'react-leaflet';
import { useEffect } from 'react';
import L from 'leaflet';

// Fix default marker icons (bundled by Vite)
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

// Severity colours (paired with text labels in popups for accessibility)
export const RISK_COLORS = {
  High: '#d73027',
  Emerging: '#fc8d59',
  Low: '#fee090',
};

const DISEASE_COLORS = {
  CMD: '#e6550d',
  CBSD: '#a50f15',
  Healthy: '#31a354',
};

/** Re-centre the map when the user's position becomes available. */
function FlyToUser({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) {
      map.flyTo(position, 13, { duration: 1.2 });
    }
  }, [position, map]);
  return null;
}

/**
 * Interactive outbreak hotspot map.
 * Features come from GET /clusters/geojson (DBSCAN output).
 */
export default function LeafletMap({ geojson, userPosition, height = '60vh' }) {
  const centre = userPosition || [-0.34, 32.58]; // default: central Uganda
  const features = geojson?.features || [];

  return (
    <MapContainer
      center={centre}
      zoom={userPosition ? 12 : 9}
      style={{ height, width: '100%', borderRadius: 12, zIndex: 0 }}
      scrollWheelZoom
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FlyToUser position={userPosition} />

      {userPosition && (
        <Marker position={userPosition}>
          <Popup>
            <strong>You are here</strong>
            <br />
            {userPosition[0].toFixed(5)}, {userPosition[1].toFixed(5)}
          </Popup>
        </Marker>
      )}

      {features.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        const p = f.properties;
        const color = DISEASE_COLORS[p.dominant_disease] || RISK_COLORS[p.risk_level] || '#333';
        return (
          <div key={p.cluster_id}>
            {/* Radius circle: approximate outbreak extent */}
            <Circle
              center={[lat, lon]}
              radius={p.radius_m}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: 0.12,
                weight: 1,
                dashArray: '4 4',
              }}
            />
            <CircleMarker
              center={[lat, lon]}
              radius={Math.min(28, 8 + p.member_count)}
              pathOptions={{
                color: '#fff',
                weight: 1.5,
                fillColor: color,
                fillOpacity: 0.85,
              }}
            >
              <Popup>
                <strong>
                  {p.dominant_disease} cluster · {p.member_count} case{p.member_count === 1 ? '' : 's'}
                </strong>
                <br />
                Risk level: <strong>{p.risk_level}</strong>
                <br />
                Radius: ~{Math.round(p.radius_m)} m
                <br />
                Algorithm: {p.algorithm} (eps={p.eps_m} m, min={p.min_samples})
                <br />
                <small>
                  Updated:{' '}
                  {p.computed_at ? new Date(p.computed_at).toLocaleString() : '—'}
                </small>
              </Popup>
            </CircleMarker>
          </div>
        );
      })}
    </MapContainer>
  );
}
