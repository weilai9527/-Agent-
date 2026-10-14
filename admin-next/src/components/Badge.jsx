export default function Badge({ tone = 'neutral', children }) {
  return <span className={'badge ' + tone}><i aria-hidden="true" />{children}</span>;
}
