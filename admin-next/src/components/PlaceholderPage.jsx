import PanelHeader from './PanelHeader.jsx';

export default function PlaceholderPage({ page }) {
  return (
    <section className="panel">
      <PanelHeader title={page.label} description={page.description} />
      <div className="content-pad">
        <p className="info-banner">该模块沿用现有管理端功能，新版界面待设计</p>
        <ul className="feature-list">{page.points.map(point => <li key={point}>{point}</li>)}</ul>
      </div>
    </section>
  );
}
