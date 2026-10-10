import cascLogo from './assets/casc-composite.png';
import { brand } from '../../shared/branding.js';

export function V4Logo({ className = '' }) {
  return (
    <span className={`v4-logo ${className}`} aria-hidden="true">
      <img src={cascLogo} alt="" />
    </span>
  );
}

export function V4Brand() {
  return <div className="v4-brand"><V4Logo /><div>{brand.name}<small>AI 面试与成长平台</small></div></div>;
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
