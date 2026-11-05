import React, { useState } from 'react';

const groups = {
  profile: '简历与个人资料', catalog: '职业目录', posting: '招聘岗位', match: '岗位匹配',
  training: '教学任务', analytics: '个人分析', credential: '证书', interview: '面试流程',
  assessment: '评估与报告', media: '语音与视频',
};
const labels = {
  'profile.read': '查看个人资料', 'profile.write': '修改资料', 'profile.upload': '上传简历', 'profile.analyze': '分析简历',
  'profile.versions.read': '查看版本', 'catalog.read': '查看目录', 'posting.read': '查看岗位',
  'match.read': '查看匹配记录', 'match.create': '发起匹配', 'training.read': '查看任务', 'training.start': '领取任务',
  'analytics.self.read': '查看个人薄弱项', 'credential.apply': '申请证书', 'credential.read': '查看本人证书',
  'assessment.read': '查看报告', 'assessment.generate': '生成报告', 'assessment.evaluate': '生成评估',
  'interview.read': '查看面试', 'interview.create': '创建面试', 'interview.training.start': '进入训练面试',
  'interview.update': '修改面试设置', 'interview.start': '开始面试', 'interview.question.open': '生成开场题',
  'interview.question.current': '获取当前题', 'interview.question.followup': '生成追问', 'interview.turn.submit': '提交回答',
  'interview.turn.spoken': '记录口述题目', 'interview.finish': '结束面试', 'interview.agent.create': '创建面试官',
  'interview.agent.update': '更新面试官', 'interview.message.create': '添加面试消息',
  'interview.diagnostics.read': '查看连接诊断', 'interview.diagnostics.write': '提交连接诊断',
  'media.rtc.read': '查看通话状态', 'media.rtc.token': '领取通话凭证', 'media.rtc.heartbeat': '维持通话',
  'media.rtc.start': '发起实时通话', 'media.rtc.notify': '通知通话助手', 'media.rtc.stop': '结束实时通话',
  'media.rtc.caption': '提交字幕校验', 'media.speech.synthesize': '合成语音', 'media.voice.connect': '建立语音连接',
  'media.voice.disconnect': '断开语音连接', 'media.video.publish': '发布视频', 'media.recording.start': '开始录制',
  'media.recording.stop': '结束录制', 'media.playback.read': '查看回放',
};

export default function NativeStudentGrants({ request, schoolId, studentId }) {
  const [state, setState] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [conflict, setConflict] = useState(false);
  const valid = studentId && !['.', '..'].includes(studentId) && !/[/%\\\s\x00-\x1f]/.test(studentId);
  const path = '/api/admin/identity/v1/students/' + encodeURIComponent(studentId) + '/grants';

  function applyReply(reply) {
    if (reply?.school_id !== schoolId || reply.student_id !== studentId || !Array.isArray(reply.available_scopes)
        || !reply.available_scopes.every(scope => typeof scope === 'string') || typeof reply.configured !== 'boolean'
        || !Array.isArray(reply.scopes) || !Number.isSafeInteger(reply.revision) || reply.revision < 0
        || !reply.scopes.every((scope) => reply.available_scopes.includes(scope))) {
      throw new Error('授权结果与当前学校、学生或权限清单不匹配。');
    }
    setState(reply);
    setSelected(reply.scopes);
    setConflict(false);
  }

  async function load() {
    if (!valid || busy) return;
    setBusy(true); setError(''); setNotice(''); setState(null);
    try { applyReply(await request(path)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function save(event) {
    event.preventDefault();
    if (!valid || !state || busy || conflict) return;
    setBusy(true); setError(''); setNotice('');
    try {
      // 修改绑定到管理员看到的版本。即使要提交的权限集合为空，
      // 版本过期后也必须重新加载表单。
      const reply = await request(path, {method:'PUT', body:JSON.stringify({expected_revision:state.revision, scopes:selected})});
      applyReply(reply);
      setNotice('授权已保存，学生需重新登录。');
    } catch (err) {
      if (err.status === 409) setConflict(true);
      setError(err.status === 409 ? '授权已被修改，请重新读取后再编辑。' : err.message);
    } finally { setBusy(false); }
  }

  const sections = new Map();
  for (const scope of state?.available_scopes || []) {
    const group = scope.split('.')[0];
    if (!sections.has(group)) sections.set(group, []);
    sections.get(group).push(scope);
  }
  return <section className="training-stack" aria-label="学生动作授权"><div className="training-row"><h4>学生动作授权</h4>
    <button type="button" disabled={busy || !valid} onClick={load}>{state ? '重新读取授权' : '读取学生授权'}</button></div>
    {state && <form onSubmit={save} data-action="grants">
      <fieldset className="training-stack" disabled={busy || conflict}>
        <legend>{state.configured ? '已配置个人授权' : '当前沿用默认学生权限'} · 版本 {state.revision}</legend>
        {Array.from(sections, ([group, scopes]) => <details key={group}><summary>{groups[group] || group} · {scopes.filter(a => selected.includes(a)).length}/{scopes.length}</summary>
          <div className="training-row">{scopes.map(scope => <label key={scope}>
            <input type="checkbox" value={scope} checked={selected.includes(scope)} onChange={e => setSelected(
              e.target.checked ? [...selected, scope] : selected.filter(a => a !== scope))} /> {labels[scope] || scope}
          </label>)}</div></details>)}
        <p>已选择 {selected.length} 项。保存后仅开放勾选的业务动作。清空并保存将关闭全部业务动作。</p>
        <div className="training-row"><button type="button" onClick={() => setSelected([])}>清空选择</button>
          <button type="submit">保存学生授权</button></div></fieldset></form>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}
