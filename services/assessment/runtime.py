"""评估域的应用逻辑：本地投影、评分队列、受版本保护的报告生成。"""
from __future__ import annotations

import hashlib
import json
from services.assessment.ai_evaluation import AiEvaluationError, DIMENSIONS, EVALUATION_PROMPT_VERSION, REPORT_PROMPT_VERSION, generate_ai_evaluation, generate_ai_report
from fastapi import Depends, Response
from services.assessment import evidence as report_evidence, versions as report_versions
from services.assessment.reports import build_report_download_filename, build_report_markdown, build_scored_report, build_timeline_review, build_user_dimension_stats, find_evaluation_by_message_id, find_report_by_id, find_report_by_interview_id, grade_from_score, list_evaluations_by_interview_id, list_reports_by_user_id, parse_json_object, pass_recommendation_from_score, refresh_user_skill_stats
from services.interview import profile_context
from services.interview.jobs import RetryJob
from services.interview.progress import locked_session
from services.interview.prompts import AGENT_QUESTION_MESSAGE_TYPES
from services.interview.queries import error, find_agent_by_interview_id, find_interview_by_user_id, find_message_by_interview_id, json_body, list_agents_by_interview_id, list_messages_by_interview_id, require_auth
from services.interview.job_store import interview_jobs
from services.interview.storage import DB_ENGINE, all_rows, db, one
from services.interview.worker import run_once as run_interview_job
from services.usage import worker as text_usage
from urllib.parse import quote
from uuid import uuid4
from services.interview.bootstrap import initialize_assessment

initialize_assessment()


def enqueue_unscored_answers(interview_id):
    # 升级前的考生可能在首次评分前就已关闭页面。
    missing = all_rows("""
        SELECT m.id FROM interview_messages m
        LEFT JOIN interview_evaluations e ON e.message_id=m.id AND e.interview_id=m.interview_id
        WHERE m.interview_id=? AND m.sender_type='candidate' AND m.message_type IN ('answer','transcript')
          AND (e.id IS NULL OR e.generation_status<>'succeeded' OR e.fallback<>0)
    """, (interview_id,))
    for row in missing:
        enqueue_score_for_answer(interview_id, row["id"])


def insert_queued_report(interview_id, user, report_id=None):
    report_id = report_id or str(uuid4())
    timeline = build_timeline_review(list_messages_by_interview_id(interview_id),
                                     list_evaluations_by_interview_id(interview_id))
    scored_count = sum(item["score"] is not None for item in timeline)
    db.execute(
        """
        INSERT INTO interview_reports (
          id, user_id, interview_id, total_score, grade, pass_recommendation,
          ability_radar, agent_feedback, timeline_review, summary, suggestions,
          provider, model, prompt_version, generation_status, fallback, scored_answer_count, answer_count
        ) VALUES (?, ?, ?, 0, '—', '待生成', '{}', '[]', '[]', '报告正在生成。', '',
                  'pending', 'pending', ?, 'queued', 0, ?, ?)
        """,
        (report_id, user["id"], interview_id, REPORT_PROMPT_VERSION, scored_count, len(timeline)),
    ).close()


def reconcile_queued_reports():
    """后台进程启动时接管升级前的占位记录，每场面试单独提交事务。"""
    for row in all_rows("SELECT interview_id,user_id FROM interview_reports WHERE generation_status='queued'"):
        with locked_session(row["interview_id"], row["user_id"]) as session:
            if session and session["status"] == "completed":
                report = find_report_by_interview_id(row["interview_id"], row["user_id"])
                if report and report["generation_status"] == "queued":
                    enqueue_unscored_answers(row["interview_id"])
                    enqueue_report_if_completed(row["interview_id"], row["user_id"])


def answer_version(message):
    # 接管历史记录时，已有的转录文本可能重新关联题目。
    # 旧租约不能继续按原来的关联关系发布评分。
    fields = ("id", "content", "transcript_text", "reply_to_message_id", "round_agent_id")
    inputs = [EVALUATION_PROMPT_VERSION, *(message.get(field) for field in fields)]
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False).encode()).hexdigest()


def enqueue_score_for_answer(interview_id, message_id):
    """调用方持有会话写锁，在同一事务提交回答和任务。"""
    message = find_message_by_interview_id(message_id, interview_id)
    if not message or message["sender_type"] != "candidate" or message["message_type"] not in {"answer", "transcript"}:
        raise ValueError("A score task needs a stored candidate answer")
    return interview_jobs.enqueue("score", interview_id, message_id, answer_version(message))


def score_protected_by_review(interview_id):
    # 报告及其最新版本由会话锁保护，与教师复核及持有效租约的发布任务共用此锁。
    # 普通的缺失评分仍可走补评流程。
    report = one("""
        SELECT r.review_status,
               (SELECT v.source FROM assessment_report_versions v
                WHERE v.report_id=r.id ORDER BY v.version DESC LIMIT 1) AS version_source
        FROM interview_reports r WHERE r.interview_id=?
    """, (interview_id,))
    return report and (report["version_source"] == "teacher" or report["review_status"] in {"approved", "rejected"})


@text_usage.metered(interview_jobs)
def prepare_score_job(job):
    """在队列事务外计算，仅持有效租约的发布任务可以写入。"""
    from services.interview.jobs import RetryJob

    interview_id, message_id = job["interview_id"], job["subject_id"]
    message = find_message_by_interview_id(message_id, interview_id)
    if not message:
        return lambda: None

    def publish_latest():
        if find_message_by_interview_id(message_id, interview_id):
            enqueue_score_for_answer(interview_id, message_id)

    if answer_version(message) != job["version"]:
        return publish_latest
    owner = one("SELECT user_id FROM interview_sessions WHERE id=?", (interview_id,))
    interview = find_interview_by_user_id(interview_id, owner["user_id"]) if owner else None
    if not interview:
        return lambda: None

    # 补评只使用作答时已有的对话，即使重试发生在面试结束后也如此。
    history = [item for item in list_messages_by_interview_id(interview_id)
               if item["order_index"] < message["order_index"]]
    questions = [item for item in history
                 if item["sender_type"] == "agent" and item["message_type"] in AGENT_QUESTION_MESSAGE_TYPES]
    question = next((item for item in questions if item["id"] == message.get("reply_to_message_id")),
                    questions[-1] if questions else {})
    agent_id = question.get("agent_id") or message.get("round_agent_id") or message.get("agent_id")
    agent = find_agent_by_interview_id(agent_id, interview_id) if agent_id else None
    try:
        evaluation = generate_ai_evaluation(interview=interview, agent=agent, question=question.get("content") or "",
                                             answer=message["content"], messages=history)
    except (AiEvaluationError, ValueError, TypeError, AttributeError) as exc:
        # 旧库的分数字段不能为空；查询接口对 pending_retry 返回空值。
        evaluation = {
            "score": 0, "strengths": "", "issues": "", "suggestions": "",
            "dimension_scores": {}, "dimension_evidence": {},
            "provider": "none", "model": "none", "prompt_version": EVALUATION_PROMPT_VERSION,
            "fallback": True, "generation_error": str(exc)[:1000],
        }

    def publish():
        # 队列已锁定会话并核实租约。
        # 更新分数或报告前，仍须在同一锁内重新检查回答。
        latest = find_message_by_interview_id(message_id, interview_id)
        if not latest:
            return
        if answer_version(latest) != job["version"]:
            return publish_latest()
        existing = find_evaluation_by_message_id(interview_id, message_id)
        if existing and existing.get("score") is not None:
            # 模型调用期间教师可能已作出决定。
            if score_protected_by_review(interview_id):
                return
            if evaluation["fallback"]:
                # 启用计量的网页服务实例可能没有后台评分进程使用的模型凭据。
                # 等待重新评分时，继续展示上次的实际得分。
                return RetryJob() if question.get("content") and text_usage.policy(interview_jobs) else None
        values = (
            evaluation["score"], evaluation["strengths"], evaluation["issues"], evaluation["suggestions"],
            json.dumps(evaluation["dimension_scores"], ensure_ascii=False),
            json.dumps(evaluation["dimension_evidence"], ensure_ascii=False),
            evaluation["provider"], evaluation["model"], evaluation["prompt_version"],
            "pending_retry" if evaluation["fallback"] else "succeeded",
            evaluation.get("generation_error"), int(evaluation["fallback"]), agent_id,
        )
        if existing:
            db.execute("""
                UPDATE interview_evaluations
                SET score=?, strengths=?, issues=?, suggestions=?, dimension_scores=?, dimension_evidence=?,
                    provider=?, model=?, prompt_version=?, generation_status=?, generation_error=?, fallback=?,
                    agent_id=?, generated_at=CURRENT_TIMESTAMP, review_status='pending', reviewed_by=NULL,
                    reviewed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=? AND interview_id=?
            """, (*values, existing["id"], interview_id)).close()
        else:
            db.execute("""
                INSERT INTO interview_evaluations
                    (score, strengths, issues, suggestions, dimension_scores, dimension_evidence,
                     provider, model, prompt_version, generation_status, generation_error, fallback, agent_id,
                     id, interview_id, message_id, generated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            """, (*values, str(uuid4()), interview_id, message_id)).close()
        db.execute("UPDATE interview_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (interview_id,)).close()
        enqueue_report_if_completed(interview_id, owner["user_id"])
        # 历史转录若缺少前置问题，反复重试也无法补齐上下文。
        # 保留记录供手动重试。
        if evaluation["fallback"] and question.get("content"):
            return RetryJob()

    return publish


def create_evaluation(
    interview_id: str,
    response: Response,
    body: dict | None = None,
    user: dict = Depends(require_auth),
):
    from services.interview.worker import run_once

    payload = json_body(body)
    message_id = str(payload.get("message_id") or "").strip()
    with locked_session(interview_id, user["id"]) as session:
        if not session:
            raise error(404, "面试不存在。")
        if not message_id:
            raise error(400, "请提供要评价的 message_id。")
        message = find_message_by_interview_id(message_id, interview_id)
        if not message:
            raise error(404, "消息不存在。")
        if message["sender_type"] != "candidate" or message["message_type"] not in {"answer", "transcript"}:
            raise error(400, "只能评价候选人的回答消息。")
        existing = find_evaluation_by_message_id(interview_id, message_id)
        force = payload.get("force") is True
        if existing and existing.get("score") is not None:
            if not force:
                response.status_code = 200
                return {"evaluation": existing}
            if score_protected_by_review(interview_id):
                raise error(403, "本报告的成绩已经由负责教师确定，不能重新评分。")
        job_id = enqueue_score_for_answer(interview_id, message_id)
        interview_jobs.request_retry(job_id, include_done=force or bool(existing and existing.get("score") is None))

    # 旧客户端需要同步取得评分，与独立后台进程一样领取持久租约。
    # 即使调用期间连接中断，评分任务也会保留。
    claimed = run_once(interview_jobs, prepare_score_job, job_id=job_id)
    result = find_evaluation_by_message_id(interview_id, message_id)
    # 取得租约时，强制重评可能仍未完成。
    # 等待期间返回的可能是上一次有效评分。
    if not result or ((force or not claimed) and interview_jobs.get(job_id)["state"] != "done"):
        response.status_code = 202
        return {"evaluation": result or {"message_id": message_id, "generation_status": "queued", "score": None},
                "job_id": job_id, "assessment_pending": True}
    if existing:
        response.status_code = 200
    return {"evaluation": result}


def list_evaluations(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    return {"evaluations": list_evaluations_by_interview_id(interview["id"])}


def frozen_report_resume(interview_id, user_id):
    frozen = profile_context.load(interview_id)
    if frozen and frozen.get("analysis"):
        return frozen["analysis"]
    snapshot = one("SELECT analysis_json FROM assessment_resume_snapshots WHERE interview_id=?", (interview_id,))
    return parse_json_object(snapshot["analysis_json"]) if snapshot else None

def report_inputs(interview_id, user_id):
    interview = find_interview_by_user_id(interview_id, user_id)
    agents = list_agents_by_interview_id(interview_id)
    messages = list_messages_by_interview_id(interview_id)
    evaluations = list_evaluations_by_interview_id(interview_id)
    turns = all_rows("""
        SELECT agent_id, action, decision_json FROM interview_turns
        WHERE interview_id=? AND action IN ('switch_agent','finish_interview') ORDER BY submission_id
    """, (interview_id,))
    local = build_scored_report(interview, agents, messages, evaluations, turns)
    resume = frozen_report_resume(interview_id, user_id)
    prompt = {key: interview.get(key) for key in ("target_role", "interview_type", "difficulty")}
    roles = [{key: agent.get(key) for key in ("id", "agent_name", "agent_type")} for agent in agents]
    # 即使评分覆盖率和均分未变，输入内容或评分证据仍可能变化。
    source = [(m["id"], m["content"], m.get("reply_to_message_id")) for m in messages]
    encoded = json.dumps([REPORT_PROMPT_VERSION, prompt, roles, source, local, resume],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return digest, dict(interview=interview, agents=agents, fallback_report=local, resume_analysis=resume)


def current_report_evidence_version(interview_id, user_id):
    digest, _ = report_inputs(interview_id, user_id)
    return report_evidence.current_version(db, one, interview_id, digest)


def enqueue_report_if_completed(interview_id, user_id):
    # 调用前须持有会话行锁，从评分发布流程调用时也一样。
    session = one("SELECT status FROM interview_sessions WHERE id=? AND user_id=?", (interview_id, user_id))
    if not session or session["status"] != "completed":
        return None
    row = one("SELECT id FROM interview_reports WHERE interview_id=? AND user_id=?", (interview_id, user_id))
    if not row:
        insert_queued_report(interview_id, {"id": user_id})
        row = one("SELECT id FROM interview_reports WHERE interview_id=?", (interview_id,))
    version = current_report_evidence_version(interview_id, user_id)
    return interview_jobs.enqueue("report", interview_id, row["id"], version)


@text_usage.metered(interview_jobs)
def prepare_report_job(job):
    interview_id, report_id = job["interview_id"], job["subject_id"]
    row = one("SELECT user_id FROM interview_reports WHERE id=? AND interview_id=?", (report_id, interview_id))
    if not row:
        return lambda: None
    user_id = row["user_id"]
    with locked_session(interview_id, user_id) as session:
        if not session or session["status"] != "completed":
            return lambda: None
        digest, inputs = report_inputs(interview_id, user_id)
        version = report_evidence.current_version(db, one, interview_id, digest)
        if version != job["version"]:
            interview_jobs.enqueue("report", interview_id, report_id, version)
            return lambda: None
        previous = report_versions.latest(report_id)
        if (previous and previous["evidence_version"] == version
                and not report_versions.can_repair_degraded(report_id, version)):
            return lambda: None

    local = inputs["fallback_report"]
    report = local
    if local.get("generation_status") != "insufficient_evidence":
        try:
            report = generate_ai_report(**inputs)
        except AiEvaluationError as exc:
            report = {**local, "provider": "local", "model": "rules-v1",
                      "prompt_version": REPORT_PROMPT_VERSION, "fallback": True, "generation_error": str(exc)}

    def publish():
        # 后台进程持有会话锁和有效租约，但在模型调用期间，
        # 即使覆盖率不变，也可能有新的单题评分写入。
        head = current_report_evidence_version(interview_id, user_id)
        if head != version:
            interview_jobs.enqueue("report", interview_id, report_id, head)
            return
        status = report.get("generation_status") or ("degraded" if report.get("fallback") else "succeeded")
        repairing = not report_versions.should_publish_report(report_id, version)
        if repairing:
            if not report_versions.can_repair_degraded(report_id, version):
                return
            if status != "succeeded":
                return RetryJob()  # 保留已发布的备用报告及其原始版本。

        db.execute("""
            UPDATE interview_reports SET scored_answer_count=?, answer_count=?, total_score=?, grade=?,
                pass_recommendation=?, ability_radar=?, agent_feedback=?, timeline_review=?, summary=?,
                suggestions=?, provider=?, model=?, prompt_version=?, generation_status=?, generation_error=?,
                fallback=?, generated_at=CURRENT_TIMESTAMP, review_status='pending', reviewed_by=NULL,
                reviewed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?
        """, (local["scored_answer_count"], local["answer_count"], report["total_score"], report["grade"],
              report["pass_recommendation"], json.dumps(report["ability_radar"], ensure_ascii=False),
              json.dumps(report["agent_feedback"], ensure_ascii=False), json.dumps(report["timeline_review"], ensure_ascii=False),
              report["summary"], report["suggestions"], report["provider"], report["model"], report["prompt_version"],
              status, report.get("generation_error"), int(bool(report.get("fallback"))), report_id, user_id)).close()
        report_versions.record_generated_report(report_id, version, repairing=repairing)
        if status == "degraded":
            return RetryJob()
    return publish


def prepare_interview_job(job):
    if job["kind"] == "score":
        return prepare_score_job(job)
    if job["kind"] == "report":
        return prepare_report_job(job)
    from services.interview.delivery import prepare_delivery
    return prepare_delivery(interview_jobs, job)


def create_report(interview_id: str, response: Response, body: dict | None = None, user: dict = Depends(require_auth)):
    with locked_session(interview_id, user["id"]) as session:
        if not session:
            raise error(404, "面试不存在。")
        if session["status"] != "completed":
            raise error(409, "请先结束面试，再生成报告。")
        existing = find_report_by_interview_id(interview_id, user["id"])
        if existing:
            response.status_code = 200
        job_id = enqueue_report_if_completed(interview_id, user["id"])
        if existing and existing["generation_status"] in {"failed", "degraded"}:
            interview_jobs.request_retry(job_id)
    run_interview_job(interview_jobs, prepare_interview_job, job_id=job_id)
    return {"report": find_report_by_interview_id(interview_id, user["id"])}


def get_interview_report(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    report = find_report_by_interview_id(interview["id"], user["id"])
    if not report:
        raise error(404, "报告不存在。")
    pending = one("""SELECT id FROM interview_jobs WHERE interview_id=?
                     AND kind IN ('score','report') AND state<>'done' LIMIT 1""", (interview_id,))
    return {"report": {**report, "assessment_pending": bool(pending)}}


def download_interview_report(interview_id: str, user: dict = Depends(require_auth)):
    interview = find_interview_by_user_id(interview_id, user["id"])
    if not interview:
        raise error(404, "面试不存在。")
    report = find_report_by_interview_id(interview["id"], user["id"])
    if not report:
        raise error(404, "报告不存在。")
    filename = build_report_download_filename(report)
    content_disposition = f"attachment; filename=interview-report.md; filename*=UTF-8''{quote(filename)}"
    return Response(
        content="\ufeff" + build_report_markdown(report, user.get("name") or "候选人"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": content_disposition},
    )


def list_reports(user: dict = Depends(require_auth)):
    return {"reports": list_reports_by_user_id(user["id"])}


def get_report(report_id: str, user: dict = Depends(require_auth)):
    report = find_report_by_id(report_id, user["id"])
    if not report:
        raise error(404, "报告不存在。")
    return {"report": report}


def get_stats(user: dict = Depends(require_auth)):
    return {"stats": refresh_user_skill_stats(user["id"])}


def get_dimensions(user: dict = Depends(require_auth)):
    refresh_user_skill_stats(user["id"])
    return {"dimensions": build_user_dimension_stats(user["id"])}
