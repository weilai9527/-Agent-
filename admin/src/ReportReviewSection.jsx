import React from 'react';
import { feedbackView, timelineView } from './reportReview.js';
import './reportReview.css';

function Score({ score }) {
  return <span className={`report-review-score${score === null ? ' unscored' : ''}`}>
    {score === null ? '暂无评分' : <><strong>{score}</strong><span> / 100</span></>}
  </span>;
}

function Insights({ item }) {
  return <div className="report-review-insights">
    {[[item.strengths, '优点', 'strength'], [item.issues, '待改进', 'issue'], [item.suggestions, '改进建议', 'suggestion']]
      .filter(([text]) => text).map(([text, label, kind]) => <div className={`report-review-insight ${kind}`} key={kind}>
        <strong>{label}</strong><p>{text}</p>
      </div>)}
  </div>;
}

export default function ReportReviewSection({ kind, value }) {
  const feedback = kind === 'feedback';
  const section = feedback ? feedbackView(value) : timelineView(value);
  const title = feedback ? '面试官反馈' : '逐题复盘';
  return <section className="detail-block report-review-section" aria-label={title}>
    <div className="report-review-heading"><h3>{title}</h3>
      {section.items.length > 0 && <span>{section.items.length} {feedback ? '位面试官' : '题'}</span>}
    </div>
    {!feedback && section.items.length > 0 && <p className="report-review-hint">按问答顺序复盘，点击题目展开提问、回答和评价。</p>}
    {section.text ? <p>{section.text}</p> : section.invalid ? <p className="report-review-empty">此部分内容暂时无法读取，请重新加载报告或联系管理员检查。</p>
      : !section.items.length ? <p className="report-review-empty">{feedback ? '暂无面试官评价。' : '暂无逐题复盘记录。'}</p>
        : feedback ? <div className="report-feedback-list">{section.items.map((item, index) => <article className="report-feedback-card" key={`${item.id}-${index}`}>
          <header><div><h4>{item.name}</h4>{item.role && <span>{item.role}</span>}</div><Score score={item.score} /></header>
          {item.comment && <p>{item.comment}</p>}
          <Insights item={item} />
        </article>)}</div>
          : <div className="report-round-list">{section.items.map((item, index) => <details className="report-round" open={index === 0} key={`${item.id}-${index}`}>
            <summary><span className="report-round-number">{String(index + 1).padStart(2, '0')}</span>
              <span className="report-round-title"><strong>第 {index + 1} 题 · {item.name || '面试官'}</strong><span>{item.question || '未记录对应问题'}</span></span>
              <Score score={item.score} />
            </summary>
            <div className="report-round-body">
              <div className="report-round-question"><h4>面试官提问</h4><p>{item.question || '未记录对应问题。'}</p></div>
              <div className="report-round-answer"><h4>学生回答</h4><p>{item.answer || '未记录学生回答。'}</p></div>
              <Insights item={item} />
              {!item.strengths && !item.issues && !item.suggestions && <p className="report-review-hint">本题暂无详细评价。</p>}
            </div>
          </details>)}</div>}
  </section>;
}
