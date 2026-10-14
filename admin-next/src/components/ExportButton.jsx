import { useState } from 'react';
import { ArrowDownToLine } from 'lucide-react';
import Modal from './Modal.jsx';
import { exportCsv } from '../utils.js';
import { useApp } from '../context.jsx';

export default function ExportButton({ title, columns, rows }) {
  const [open, setOpen] = useState(false);
  const { notify } = useApp();
  return (
    <>
      <button className="secondary" onClick={() => setOpen(true)}><ArrowDownToLine size={16} />导出当前结果</button>
      {open && <Modal title={'导出' + title} onClose={() => setOpen(false)}>
        <p>将导出当前筛选结果的全部 {rows.length} 条记录（含分页内外），字段与列表一致，不包含操作列。</p>
        <p className="info-banner">正式版导出将由服务端生成并记录安全审计日志</p>
        <div className="modal-actions">
          <button className="secondary" onClick={() => setOpen(false)}>取消</button>
          <button className="primary" onClick={() => {
            exportCsv(title, columns, rows);
            setOpen(false);
            notify('演示数据已导出。');
          }}>确认导出</button>
        </div>
      </Modal>}
    </>
  );
}
