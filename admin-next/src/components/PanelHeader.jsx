export default function PanelHeader({ title, description, children }) {
  return (
    <header className="panel-header">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {children}
    </header>
  );
}
