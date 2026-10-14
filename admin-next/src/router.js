import { useEffect, useState } from 'react';

export function parseHash(hash) {
  const [rawPath, rawQuery = ''] = (hash.replace(/^#/, '') || '/overview').split('?');
  return { path: rawPath.replace(/\/$/, '') || '/overview', query: Object.fromEntries(new URLSearchParams(rawQuery)) };
}
export function navigate(path, query = {}) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== '' && value != null) params.set(key, String(value));
  });
  window.location.hash = path + (params.size ? '?' + params.toString() : '');
}
export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const sync = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);
  return route;
}
