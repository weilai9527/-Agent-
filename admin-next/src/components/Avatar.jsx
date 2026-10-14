export default function Avatar({ student }) {
  return <span className="avatar" aria-hidden="true">{student.name.slice(-2)}</span>;
}
