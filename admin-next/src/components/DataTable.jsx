export default function DataTable({ columns, rows, caption }) {
  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{columns.map(column => <th scope="col" key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.map(row => <tr key={row.id}>{columns.map(column => <td key={column.key}>{column.render ? column.render(row) : row[column.key]}</td>)}</tr>)}
          {!rows.length && <tr><td className="empty-state" colSpan={columns.length}>暂无符合条件的记录</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
