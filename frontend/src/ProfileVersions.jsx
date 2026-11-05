import React, { useEffect, useState } from 'react';
import { localDate, readError } from './trainingUi.js';
import './training.css';

const versionsPath = '/api/profile/versions';
const pageSize = 10;
const sources = { profile: '编辑个人资料', form: '保存简历表单', upload: '上传简历', import: '导入资料' };
const fieldsBySection = [
  ['profile', '个人资料', {
    nickname: '昵称', target_role: '目标岗位', experience_level: '经验水平', company_type: '公司类型',
    target_city: '目标城市', expected_salary: '期望薪资', years_of_experience: '工作年限', education_level: '学历',
    skills: '技能', project_keywords: '项目关键词', project_experience: '项目经历', portfolio_links: '作品链接',
    preferred_interview_type: '面试类型', preferred_difficulty: '面试难度', preferred_interviewer_style: '面试官风格',
    resume_filename: '简历文件', resume_text: '简历正文',
  }],
  ['form', '简历表单', {
    college: '学院', major: '专业', professional_skills: '职业技能与经验', advantages: '优势', education: '教育经历',
    honors: '荣誉及职务', projects: '项目经历', languages: '语言', works: '作品', skills: '技能',
    certificates: '证书', bonus: '加分项',
  }],
];

function VersionSnapshot({ request, version }) {
  const [result, setResult] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    request(versionsPath + '/' + encodeURIComponent(version), { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setResult({ data });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ error: readError(error) });
      });
    return () => controller.abort();
  }, [request, version]);

  if (!result) return <p role="status">正在读取此版本…</p>;
  if (result.error) return <p role="alert">{result.error}</p>;
  return fieldsBySection.map(([section, title, labels]) => {
    const fields = Object.entries(labels).filter(([key]) => result.data[section]?.[key]);
    return <section key={section}><h4>{title}</h4>{fields.length ? <dl>{fields.map(([key, label]) =>
      <React.Fragment key={key}><dt>{label}</dt><dd><pre>{result.data[section][key]}</pre></dd></React.Fragment>)}
    </dl> : <p>此版本未填写{title}。</p>}</section>;
  });
}

function VersionList({ request }) {
  const [cursors, setCursors] = useState([null]);
  const [selected, setSelected] = useState(null);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);
  const before = cursors[cursors.length - 1];
  const current = result?.before === before && result.revision === revision ? result : null;
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: String(pageSize + 1) });
    if (before !== null) params.set('before', String(before));
    request(versionsPath + '?' + params, { signal: controller.signal })
      .then(({ versions }) => {
        if (!controller.signal.aborted) setResult({ before, revision, versions });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setResult({ before, revision, error: readError(error) });
      });
    return () => controller.abort();
  }, [request, before, revision]);
  function navigate(pages) {
    setSelected(null);
    setCursors(pages);
  }
  return <div className="training-stack">
    {!current ? <p role="status">正在读取版本记录…</p> : current.error ? <p role="alert">{current.error}</p> :
      current.versions.length === 0 ? <p>尚无已保存版本。</p> : <ol className="training-list">
        {current.versions.slice(0, pageSize).map((item) => <li key={item.version}>
          <button type="button" aria-expanded={selected === item.version}
            onClick={() => setSelected(selected === item.version ? null : item.version)}>
            第 {item.version} 版 · {sources[item.source] || '保存资料'} · {localDate(item.created_at)}
          </button>
          {selected === item.version && <VersionSnapshot key={item.version} request={request} version={item.version} />}
        </li>)}
      </ol>}
    <div className="training-row">
      <button type="button" onClick={() => { navigate([null]); setRevision((n) => n + 1); }}>刷新记录</button>
      <button type="button" disabled={cursors.length === 1} onClick={() => navigate(cursors.slice(0, -1))}>上一页</button>
      <button type="button" disabled={!(current?.versions?.length > pageSize)}
        onClick={() => navigate([...cursors, current.versions[pageSize - 1].version])}>下一页</button>
    </div>
  </div>;
}

export default function ProfileVersions({ request }) {
  const [open, setOpen] = useState(false);
  // 只在学生展开列表或选择某个版本时读取对应资料。查看历史不会写回当前简历。
  return <details className="training-page training-card training-candidate" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>查看个人资料与简历历史版本</summary>
    {open && <VersionList request={request} />}
  </details>;
}
