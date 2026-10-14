export default function Progress({ progress }) {
  return (
    <div>
      <div className="progress" role="progressbar" aria-label="计划完成比例" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}>
        <i style={{ width: progress.percent + '%' }} />
      </div>
      <div className="progress-caption"><span>已完成 {progress.completed} / {progress.total} 人</span><strong>{progress.percent}%</strong></div>
    </div>
  );
}
