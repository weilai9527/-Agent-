import React, { useEffect, useRef, useState } from 'react';

const fields = [
  ['target_role', '目标岗位'],
  ['skills', '技能关键词'],
  ['education_level', '学历层次'],
  ['project_experience', '项目经历摘要'],
  ['resume_summary', '教学摘要'],
];

export default function StudentTeachingProfile({ request, permissions, schoolId, studentId }) {
  const [view, setView] = useState(null);
  const pending = useRef(null);
  const allowed = permissions.canReadStudentProfile === true && Boolean(schoolId)
    && typeof studentId === 'string' && studentId.length > 0 && studentId.length <= 128
    && !['.', '..'].includes(studentId) && !/[/%\\\s\x00-\x1f\x7f]/u.test(studentId);
  // 快照更新时也作废上一次展示。班级归属可能已经变化，即使动作权限仍然存在。
  const current = allowed && view?.permissions === permissions && view.schoolId === schoolId
    && view.studentId === studentId ? view : null;

  function close() {
    pending.current?.abort();
    pending.current = null;
    setView(null);
  }

  useEffect(() => {
    setView(null);
    const hide = () => { if (document.hidden) close(); };
    document.addEventListener('visibilitychange', hide);
    return () => {
      document.removeEventListener('visibilitychange', hide);
      pending.current?.abort();
      pending.current = null;
    };
  }, [permissions, schoolId, studentId]);

  useEffect(() => {
    if (!current?.rows) return undefined;
    // 即使管理端快照轮询中断，也不无限期保留已获取的学生资料。
    const timeout = window.setTimeout(close, 30_000);
    return () => window.clearTimeout(timeout);
  }, [current]);

  async function open() {
    if (!allowed || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    const context = { permissions, schoolId, studentId };
    setView({ ...context, loading: true });
    try {
      const response = await request('/api/admin/students/' + encodeURIComponent(studentId) + '/profile',
        { signal: controller.signal, cache: 'no-store' });
      if (controller.signal.aborted) return;
      if (response?.school_id !== schoolId || response.student_id !== studentId || !Number.isSafeInteger(response.version)
          || response.version < 1 || !fields.every(([key]) => typeof response.profile?.[key] === 'string')) {
        throw new Error('invalid-profile');
      }
      // 只保留教学投影的五项文本，不缓存原始响应、下载地址或个人联系信息。
      const rows = fields.map(([key, label]) => [label, response.profile[key]]).filter(([, value]) => value.trim());
      setView({ ...context, rows, version: response.version });
    } catch (error) {
      if (controller.signal.aborted) return;
      const errors = { 403: '当前账号无权查看该学生的教学档案。', 404: '当前学生暂无教学档案。',
        503: '暂时无法核验教学档案权限，请稍后重试。' };
      setView({ ...context, error: errors[error.status] || '无法核验或读取当前学生的教学档案。' });
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }

  if (!allowed) return null;
  return <section className="training-stack" aria-label="教学档案">
    <div className="training-row"><h4>教学档案</h4>
      {current?.rows || current?.loading ? <button type="button" onClick={close}>收起教学档案</button>
        : <button type="button" onClick={open}>查看教学档案</button>}
    </div>
    {current?.loading && <p role="status">正在核验并读取教学档案…</p>}
    {current?.error && <p role="alert">{current.error}</p>}
    {current?.rows && <><p>档案版本 {current.version}</p>
      {current.rows.length ? <dl>{current.rows.map(([name, value]) =>
        <React.Fragment key={name}><dt>{name}</dt><dd>{value}</dd></React.Fragment>)}</dl> : <p>当前版本暂无教学摘要。</p>}
    </>}
  </section>;
}
