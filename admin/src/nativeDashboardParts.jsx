import React, { useEffect, useState } from 'react';

export function useResource(request, path, revision) {
  const [reply, setReply] = useState(null);
  useEffect(() => {
    if (!path) { setReply(null); return; }
    const controller = new AbortController();
    request(path, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) setReply({ path, revision, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setReply({ path, revision, status: error.status || 503 });
    });
    return () => controller.abort();
  }, [request, path, revision]);
  // 查询条件或权限变化时立即隐藏旧响应，避免切班后短暂显示原班级的学生。
  if (!path) return { status: 403 };
  return reply?.revision === revision && reply.path === path ? reply : {};
}

export function Result({ reply, label, valid, children }) {
  if (reply.status === 401 || reply.status === 403) return <p className="nt-message">当前账号无权查看{label}。</p>;
  if (reply.status === 422) return <p role="alert" className="nt-message">{label}未能汇总，请检查筛选条件或缩小查询范围。</p>;
  if (reply.status === 404) return <p className="nt-message">{label}不存在或已不可见。</p>;
  if (reply.status || ('data' in reply && (!reply.data || !valid(reply.data)))) return <p className="nt-message" role="alert">{label}暂不可用，请刷新后重试。</p>;
  if (!reply.data) return <p className="nt-message" role="status">正在读取{label}…</p>;
  return children(reply.data);
}

export const counts = (row, keys) => keys.every((key) => Number.isSafeInteger(row?.[key]) && row[key] >= 0);
export function Panel({ title, note, children }) {
  return <section className="wb-panel nt-panel"><header><div><h2>{title}</h2><p>{note}</p></div></header><div>{children}</div></section>;
}

export function Metric({ label, count, unit }) {
  return <div><dt>{label}</dt><dd>{count}<small>{unit}</small></dd></div>;
}
