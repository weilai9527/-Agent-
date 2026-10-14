export default function PageHeading({ title, description, children }) {
  return (
    <div className="page-heading">
      <div><h1>{title}</h1>{description && <p>{description}</p>}</div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
