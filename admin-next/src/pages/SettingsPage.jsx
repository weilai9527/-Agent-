import { useApp } from '../context.jsx';
import brand from '../brand.js';
import PageHeading from '../components/PageHeading.jsx';

export default function SettingsPage() {
  const { compact, saveCompact, notify } = useApp();
  return (
    <>
      <PageHeading title="个人设置" description="仅管理个人显示偏好，保存于当前浏览器。" />
      <section className="panel content-pad stack settings-panel">
        <h2>机构信息</h2>
        <p>机构名称：{brand.organization}（只读）</p>
        <p className="muted">机构名称由管理员在组织架构中统一配置。</p>
        <h2>显示偏好</h2>
        <label className="checkbox-label"><input type="checkbox" checked={compact} onChange={event => {
          if (saveCompact(event.target.checked)) notify('个人显示偏好已保存。');
        }} />使用紧凑表格</label>
      </section>
    </>
  );
}
