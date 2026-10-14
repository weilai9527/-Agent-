import React, { useEffect, useState } from 'react';
import { Bot, FileText, Mic, Volume2, CheckCircle2, AlertCircle, KeyRound } from 'lucide-react';
import './modelSettings.css';
import InterviewerPolicyEditor from './InterviewerPolicyEditor.jsx';

const groups = [
  { id: 'text', label: '报告与评分', icon: FileText, description: '文本模型、供应商顺序与等待时间', effect: '保存后，新的评分和报告请求会读取配置；已有成绩不会重新计算。' },
  { id: 'realtime', label: '实时面试', icon: Mic, description: '实时对话模型与面试官音色', effect: '保存后需要重启用户端后端，新的实时面试连接才能使用更新后的配置。' },
  { id: 'policy', label: '面试官策略', icon: Bot, description: '默认风格、学生选项与角色分工' },
  { id: 'tts', label: '语音合成', icon: Volume2, description: '将面试追问文本转换为语音', effect: '保存后需要重启用户端后端，新的语音合成请求才能使用更新后的配置。' },
];
const fields = {
  reportOpenaiApiKey: { label: 'OpenAI 文本 API Key', secret: true, configured: 'reportOpenaiApiKeyConfigured', masked: 'reportOpenaiApiKeyMasked' },
  reportOpenaiModel: { label: 'OpenAI 文本模型', fallback: 'gpt-4o-mini' },
  reportOpenaiBaseUrl: { label: 'OpenAI 接入地址', fallback: 'https://api.openai.com/v1' },
  reportQwenApiKey: { label: '千问文本 API Key', secret: true, configured: 'reportQwenApiKeyConfigured', masked: 'reportQwenApiKeyMasked' },
  reportQwenModel: { label: '千问文本模型', fallback: 'qwen-plus' },
  reportQwenBaseUrl: { label: '千问接入地址', fallback: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  reportKimiApiKey: { label: 'Kimi API Key', secret: true, configured: 'reportKimiApiKeyConfigured', masked: 'reportKimiApiKeyMasked' },
  reportKimiModel: { label: 'Kimi 文本模型', fallback: 'moonshot-v1-8k' },
  reportKimiBaseUrl: { label: 'Kimi 接入地址', fallback: 'https://api.moonshot.cn/v1' },
  reportDeepseekApiKey: { label: 'DeepSeek API Key', secret: true, configured: 'reportDeepseekApiKeyConfigured', masked: 'reportDeepseekApiKeyMasked' },
  reportDeepseekModel: { label: 'DeepSeek 文本模型', fallback: 'deepseek-chat' },
  reportDeepseekBaseUrl: { label: 'DeepSeek 接入地址', fallback: 'https://api.deepseek.com' },
  reportCustomApiKey: { label: '自定义服务 API Key', secret: true, configured: 'reportCustomApiKeyConfigured', masked: 'reportCustomApiKeyMasked' },
  reportCustomModel: { label: '自定义服务模型', optional: true },
  reportCustomBaseUrl: { label: '自定义服务接入地址', optional: true, hint: '使用自定义服务时，请同时配置密钥、模型名称和兼容 OpenAI 的 HTTP(S) 接入地址。' },
  reportProviderOrder: { label: '报告供应商顺序', fallback: 'kimi,deepseek,qwen,openai,custom', order: true },
  reportTimeout: { label: '报告超时（秒）', fallback: 60, min: 10, max: 180 },
  reportRetries: { label: '报告网络重试次数', fallback: 0, min: 0, max: 4 },
  reportAttempts: { label: '报告最多尝试供应商数', fallback: 2, min: 1, max: 5 },
  evaluationProviderOrder: { label: '单题评分供应商顺序', fallback: 'kimi,deepseek,qwen,openai,custom', order: true },
  evaluationTimeout: { label: '单题评分超时（秒）', fallback: 12, min: 5, max: 180 },
  evaluationRetries: { label: '单题评分网络重试次数', fallback: 0, min: 0, max: 4 },
  evaluationAttempts: { label: '单题评分最多尝试供应商数', fallback: 1, min: 1, max: 5 },
  openaiApiKey: { label: 'OpenAI 实时 API Key', secret: true, configured: 'openaiApiKeyConfigured', masked: 'openaiApiKeyMasked' },
  openaiRealtimeModel: { label: 'OpenAI 实时模型', fallback: 'gpt-realtime-2' },
  openaiVoice: { label: 'OpenAI 音色', fallback: 'marin' },
  qwenOmniApiKey: { label: '千问实时 API Key', secret: true, configured: 'qwenOmniApiKeyConfigured', masked: 'qwenOmniApiKeyMasked', hint: '未设置独立密钥时，服务端沿用现有千问 / DashScope 密钥。' },
  qwenOmniModel: { label: '千问实时模型', fallback: 'qwen3.5-omni-plus-realtime' },
  qwenOmniVoice: { label: '千问实时音色', fallback: 'Tina' },
  qwenOmniRegion: { label: '千问实时地域', fallback: 'beijing' },
  qwenOmniWorkspaceId: { label: '千问实时业务空间 ID', optional: true },
  qwenOmniEndpoint: { label: '自定义 WebRTC 接入地址', optional: true, hint: '特殊部署时填写；留空使用服务端默认接入地址。' },
  dashscopeApiKey: { label: 'DashScope API Key', secret: true, configured: 'dashscopeApiKeyConfigured', masked: 'dashscopeApiKeyMasked' },
  qwenTtsModel: { label: '语音合成模型', fallback: 'cosyvoice-v3-flash' },
  qwenTtsVoice: { label: '语音合成音色', fallback: 'longanyang' },
  qwenTtsRegion: { label: '语音合成地域', fallback: 'beijing' },
  qwenTtsWorkspaceId: { label: '语音合成业务空间 ID', optional: true, hint: '新加坡地域需要填写，北京地域可留空。' },
};
const groupKeys = {
  text: Object.keys(fields).filter(key => key.startsWith('report') || key.startsWith('evaluation')),
  realtime: ['openaiApiKey', 'openaiRealtimeModel', 'openaiVoice', ...Object.keys(fields).filter(key => key.startsWith('qwenOmni'))],
  tts: ['dashscopeApiKey', ...Object.keys(fields).filter(key => key.startsWith('qwenTts'))],
};
const orders = ['kimi,deepseek,qwen,openai,custom', 'openai,qwen', 'qwen,openai', 'kimi', 'deepseek', 'openai', 'qwen', 'custom'];
const savedValue = (settings, key) => fields[key].secret ? '' : String(settings[key] == null || settings[key] === '-' ? fields[key].fallback ?? '' : settings[key]);

export default function ModelSettingsPage({ settings = {}, canEdit, request, onSettingsSaved, active = 'text' }) {
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [results, setResults] = useState(null);
  const changedKeys = (group) => (groupKeys[group] || []).filter(key => key in draft && draft[key] !== savedValue(settings, key));
  const pending = changedKeys(active);
  const current = groups.find(group => group.id === active);
  const busy = saving || testing;
  useEffect(() => { setMessage(''); setError(''); }, [active]);

  function update(key, value) {
    setDraft(previous => ({ ...previous, [key]: value }));
    setMessage('');
    setError('');
    if (groupKeys.text.includes(key)) setResults(null);
  }
  function discard(keys) {
    setDraft(previous => Object.fromEntries(Object.entries(previous).filter(([key]) => !keys.includes(key))));
  }
  async function save(event) {
    event.preventDefault();
    if (!canEdit || !pending.length || busy) return;
    const payload = Object.fromEntries(pending.map(key => [key, draft[key].trim()]));
    if (pending.some(key => !fields[key].optional && !fields[key].secret && !payload[key])) {
      setError('请填写模型名称与必填参数。');
      return;
    }
    setSaving(true); setMessage(''); setError(''); setResults(null);
    try {
      const result = await request('/api/admin/settings', { method: 'PATCH', body: JSON.stringify(payload) });
      onSettingsSaved(result.settings);
      discard(pending);
      setMessage(`${current.label}配置已保存。${current.effect}`);
    } catch (failure) { setError(failure.message); }
    finally { setSaving(false); }
  }
  async function testProviders() {
    if (!canEdit || busy || changedKeys('text').length) return;
    setTesting(true); setError(''); setResults(null);
    try {
      const result = await request('/api/admin/settings/report-providers/test', { method: 'POST' });
      setResults(result.providers || []);
    } catch (failure) { setError(failure.message); }
    finally { setTesting(false); }
  }
  function field(key) {
    const spec = fields[key];
    const value = draft[key] ?? savedValue(settings, key);
    return <label className="field-block" key={key}>
      <span>{spec.label}{spec.optional ? '（可选）' : ''}</span>
      {spec.order ? <><input aria-label={spec.label} list={`${key}-options`} required value={value} onChange={event => update(key, event.target.value)} />
        <datalist id={`${key}-options`}>{orders.map(order => <option key={order} value={order} />)}</datalist>
        <small>按优先级填写：kimi、deepseek、qwen、openai、custom，以英文逗号分隔，不可重复。</small>
      </> : <input aria-label={spec.label} type={spec.secret ? 'password' : spec.min !== undefined ? 'number' : key.endsWith('BaseUrl') ? 'url' : 'text'}
        autoComplete={spec.secret ? 'new-password' : 'off'} value={value} min={spec.min} max={spec.max} step={spec.min !== undefined ? 1 : undefined}
        required={!spec.optional && !spec.secret} maxLength={spec.secret ? 4096 : undefined}
        placeholder={spec.secret ? settings[spec.configured] ? `已配置 ${settings[spec.masked] || ''}，留空保留` : '填写 API Key' : undefined}
        onChange={event => update(key, event.target.value)} />}
      {spec.secret && <small>留空保留当前密钥，保存后仅显示脱敏状态。</small>}
      {spec.hint && <small>{spec.hint}</small>}
    </label>;
  }
  function provider(title, description, configuredKey, keys) {
    return <section className="provider-card">
      <div className="provider-card-header"><div><KeyRound size={18} /><div><h3>{title}</h3><p>{description}</p></div></div>
        <span className={`provider-pill ${settings[configuredKey] ? 'ready' : 'missing'}`}>{settings[configuredKey] ? '密钥已配置' : '未配置密钥'}</span>
      </div>
      <div className="field-grid">{keys.map(field)}</div>
    </section>;
  }
  if (!canEdit) return <section className="model-access-note"><Bot size={28} /><h2>模型配置由超级管理员维护</h2><p>这里管理报告评分、实时面试和语音合成使用的模型。当前账号无权读取或修改全局模型参数与密钥。</p></section>;

  return <section className="model-settings-page">
    <div className="model-settings-intro"><div><span className="model-eyebrow">AI 服务设置</span><h2>{current.description}</h2><p>{active === 'policy' ? '统一设置面试官的提问方式、学生可选范围和各轮职责，保存后应用于新建面试。' : '本页配置单独保存。密钥已配置表示已填写，连接是否成功请以检测或实际调用结果为准。'}</p></div><span className="model-admin-badge"><Bot size={16} />全局配置</span></div>
    <div hidden={active !== 'policy'}><InterviewerPolicyEditor request={request} active={active === 'policy'} /></div>
    <form hidden={active === 'policy'} className="settings-form model-settings-form" onSubmit={save}>
      <p className="model-effect-note"><AlertCircle size={16} />{current.effect}</p>
      <fieldset disabled={busy} className="model-fields">
        {active === 'text' && <>
          <div className="model-provider-grid">
            {provider('OpenAI 文本模型', '用于报告生成和单题评价的文本分析。', 'reportOpenaiApiKeyConfigured', ['reportOpenaiApiKey', 'reportOpenaiModel', 'reportOpenaiBaseUrl'])}
            {provider('千问文本模型', '可作为首选供应商或备用供应商。', 'reportQwenApiKeyConfigured', ['reportQwenApiKey', 'reportQwenModel', 'reportQwenBaseUrl'])}
            {provider('Kimi 文本模型', '用于报告生成和单题评价；兼容已有 Moonshot 密钥配置。', 'reportKimiApiKeyConfigured', ['reportKimiApiKey', 'reportKimiModel', 'reportKimiBaseUrl'])}
            {provider('DeepSeek 文本模型', '可加入报告和单题评分的供应商顺序。', 'reportDeepseekApiKeyConfigured', ['reportDeepseekApiKey', 'reportDeepseekModel', 'reportDeepseekBaseUrl'])}
            {provider('自定义文本服务', '接入兼容 OpenAI 的文本模型服务。', 'reportCustomApiKeyConfigured', ['reportCustomApiKey', 'reportCustomModel', 'reportCustomBaseUrl'])}
          </div>
          <section className="provider-card"><div className="model-section-heading"><h3>调用策略</h3><p>报告与单题评分分别选择供应商顺序；只会调用服务端已配置的供应商。</p></div>
            <div className="model-runtime-grid">{['reportProviderOrder', 'reportTimeout', 'reportRetries', 'reportAttempts'].map(field)}</div>
            <div className="model-runtime-grid">{['evaluationProviderOrder', 'evaluationTimeout', 'evaluationRetries', 'evaluationAttempts'].map(field)}</div>
            <small className="model-runtime-help">最多尝试供应商数为 1 时只调用首个已配置的供应商；增加后，失败时才会继续尝试备用供应商。</small>
            <div className="provider-test-actions"><button type="button" className="secondary-button" disabled={busy || changedKeys('text').length > 0} onClick={testProviders}>{testing ? '检测中…' : '检测已保存的报告模型'}</button><span>检测会发送少量请求。修改后请先保存；此检测不验证实时语音和单题评分策略。</span></div>
            {results !== null && <div className="provider-test-results" role="status">{results.length ? results.map(item => <div key={item.provider} className={item.status === 'ok' ? 'ready' : 'missing'}><strong>{item.provider.toUpperCase()} · {item.model}</strong><span>{item.status === 'ok' ? `连接成功 · ${item.latency_ms} ms` : item.error || '检测失败'}</span></div>) : <p>没有可检测的报告供应商，请检查密钥与供应商顺序。</p>}</div>}
          </section>
        </>}
        {active === 'realtime' && <div className="model-provider-grid">
          {provider('OpenAI 实时面试', '实时语音对话、转写与面试官回复。', 'openaiApiKeyConfigured', ['openaiApiKey', 'openaiRealtimeModel', 'openaiVoice'])}
          {provider('千问实时面试', '千问 WebRTC 实时语音链路，使用独立的模型与音色。', 'qwenOmniApiKeyConfigured', groupKeys.realtime.filter(key => key.startsWith('qwenOmni')))}
        </div>}
        {active === 'tts' && provider('千问语音合成', '将已经生成的面试追问文本转换为音频，不影响评分规则。', 'dashscopeApiKeyConfigured', groupKeys.tts)}
      </fieldset>
      {error && <p className="settings-message error" role="alert">{error}</p>}
      {message && <p className="settings-message success" role="status"><CheckCircle2 size={16} /> {message}</p>}
      <div className="model-save-bar"><span>{pending.length ? `当前场景有 ${pending.length} 项未保存修改` : '当前场景无未保存修改'}</span><div><button type="button" className="secondary-button" disabled={busy || !pending.length} onClick={() => { discard(groupKeys[active]); setError(''); setMessage(''); }}>撤销修改</button><button type="submit" className="primary-button" disabled={busy || !pending.length}>{saving ? '保存中…' : `保存${current.label}配置`}</button></div></div>
    </form>
  </section>;
}
