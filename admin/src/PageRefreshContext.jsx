import { createContext, useContext, useEffect, useRef } from 'react';

export const PageRefreshContext = createContext(null);

// Refresh the mounted page without resetting its filters or unsaved form state.
export function usePageRefresh(refresh, enabled = true) {
  const register = useContext(PageRefreshContext);
  const latest = useRef(refresh);
  latest.current = refresh;
  useEffect(() => {
    if (!enabled || !register) return undefined;
    return register(() => latest.current());
  }, [register, enabled]);
}
