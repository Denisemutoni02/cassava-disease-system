import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

/**
 * Tracks usable connectivity for this online-only system.
 *
 * `online` is true when EITHER:
 *  - the OS reports a network connection (navigator.onLine), OR
 *  - the backend answers GET /health — covers LAN-only setups (local backend
 *    reachable but no internet/WAN), which must NOT be shown as offline.
 *
 * Only when both fail is the app truly offline ("No internet connection").
 * A reachable-but-broken backend (wrong URL / stopped / CORS) is a per-request
 * error, surfaced by the API client as "Cannot reach server …".
 *
 * `recheck()` powers the Retry buttons in the offline banner.
 */
const NetworkContext = createContext({ online: true, recheck: () => {} });

function osOnline() {
  return typeof navigator === 'undefined' || navigator.onLine !== false;
}

async function evaluate() {
  if (osOnline()) return true;
  // OS says offline — check whether the local backend is still reachable.
  try {
    return await api.probe();
  } catch {
    return false;
  }
}

export function NetworkProvider({ children }) {
  const [online, setOnline] = useState(osOnline);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const refresh = () => {
      evaluate().then((ok) => {
        if (alive.current) setOnline(ok);
      });
    };
    if (!osOnline()) refresh(); // upgrade a false "offline" if the backend answers
    window.addEventListener('online', refresh);
    window.addEventListener('offline', refresh);
    return () => {
      alive.current = false;
      window.removeEventListener('online', refresh);
      window.removeEventListener('offline', refresh);
    };
  }, []);

  const recheck = useCallback(() => {
    evaluate().then((ok) => {
      if (alive.current) setOnline(ok);
    });
  }, []);

  return <NetworkContext.Provider value={{ online, recheck }}>{children}</NetworkContext.Provider>;
}

export function useNetwork() {
  return useContext(NetworkContext);
}
