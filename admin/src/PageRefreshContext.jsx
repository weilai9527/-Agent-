import { createContext, useContext, useEffect, useRef } from 'react';

export const PageRefreshContext = createContext(null);

// 刷新当前页面时保留筛选条件和未保存的表单内容。
export function usePageRefresh(refresh, enabled = true) {
  const register = useContext(PageRefreshContext);
  const latest = useRef(refresh);
  latest.current = refresh;
  useEffect(() => {
    if (!enabled || !register) return undefined;
    return register(() => latest.current());
  }, [register, enabled]);
}
