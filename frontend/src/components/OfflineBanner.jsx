import { useNetwork } from '../context/NetworkContext';

/**
 * Friendly no-internet state shown on every screen while offline.
 * Diagnosis and map updates require an active connection — the Retry button
 * re-checks the connection and resumes automatically when it is back.
 */
export default function OfflineBanner() {
  const { online, recheck } = useNetwork();
  if (online) return null;
  return (
    <div className="offline-banner" role="alert">
      <div className="offline-text">
        <strong>No internet connection</strong>
        <span>
          Diagnosis and the hotspot map need an active connection — please
          reconnect and try again.
        </span>
      </div>
      <button type="button" className="btn btn-retry" onClick={recheck}>
        Retry
      </button>
    </div>
  );
}
