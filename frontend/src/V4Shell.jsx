export function V4Logo({ className = '' }) {
  return (
    <svg className={`v4-logo ${className}`} viewBox="0 0 64 100" fill="currentColor" aria-hidden="true">
      <path d="M13 12C13 0 51 0 51 12L47 21C40 14 24 14 17 21ZM10 14 23 33 15 39 3 25ZM54 14 41 33 49 39 61 25ZM25 35H39L47 41 40 53H24L17 41ZM24 56H40L51 86 32 100 13 86Z" />
    </svg>
  );
}

export function V4Brand() {
  return <div className="v4-brand"><V4Logo /><div>Astrainterview<small>PREPARE. PRACTICE. PROGRESS.</small></div></div>;
}

export function V4PageHeading({ eyebrow, title, description, action, className = '' }) {
  return (
    <header className={`v4-page-heading ${className}`}>
      <div>
        {eyebrow && <span className="v4-eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </header>
  );
}
