"""评分证据、报告查询、导出格式及学生能力统计。"""
from __future__ import annotations

import json
import math
import re
from services.assessment.ai_evaluation import DIMENSIONS, EVALUATION_PROMPT_VERSION, REPORT_PROMPT_VERSION
from datetime import datetime, timezone
from services.interview.prompts import AGENT_QUESTION_MESSAGE_TYPES
from services.interview.storage import all_rows, db, one
from typing import Any
from uuid import uuid4


def clamp_stat_score(score: float) -> int:
    return max(0, min(100, round(score)))


def average(numbers: list[Any], fallback: float = 0) -> float:
    valid = [float(number) for number in numbers if isinstance(number, (int, float)) and math.isfinite(number)]
    return sum(valid) / len(valid) if valid else fallback


def parse_json_object(value: Any, fallback: dict | None = None) -> dict:
    if fallback is None:
        fallback = {}
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, dict) else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def find_evaluation_by_message_id(interview_id: str, message_id: str) -> dict | None:
    return one(
        """
        SELECT evaluations.id, evaluations.interview_id, evaluations.message_id, evaluations.agent_id,
               agents.agent_name, agents.agent_type,
               CASE WHEN evaluations.generation_status = 'succeeded' AND evaluations.fallback = 0
                    THEN evaluations.score ELSE NULL END AS score,
               evaluations.strengths, evaluations.issues, evaluations.suggestions,
               evaluations.dimension_scores, evaluations.dimension_evidence, evaluations.provider, evaluations.model,
               evaluations.prompt_version, evaluations.generation_status,
               evaluations.generation_error, evaluations.fallback,
               evaluations.generated_at, evaluations.review_status,
               evaluations.reviewed_by, evaluations.reviewed_at,
               evaluations.created_at, evaluations.updated_at
        FROM interview_evaluations AS evaluations
        LEFT JOIN interview_agents AS agents ON agents.id = evaluations.agent_id
        WHERE evaluations.interview_id = ? AND evaluations.message_id = ?
        """,
        (interview_id, message_id),
    )


def list_evaluations_by_interview_id(interview_id: str) -> list[dict]:
    return all_rows(
        """
        SELECT evaluations.id, evaluations.interview_id, evaluations.message_id, evaluations.agent_id,
               agents.agent_name, agents.agent_type,
               CASE WHEN evaluations.generation_status = 'succeeded' AND evaluations.fallback = 0
                    THEN evaluations.score ELSE NULL END AS score,
               evaluations.strengths, evaluations.issues, evaluations.suggestions,
               evaluations.dimension_scores, evaluations.dimension_evidence, evaluations.provider, evaluations.model,
               evaluations.prompt_version, evaluations.generation_status,
               evaluations.generation_error, evaluations.fallback,
               evaluations.generated_at, evaluations.review_status,
               evaluations.reviewed_by, evaluations.reviewed_at,
               evaluations.created_at, evaluations.updated_at,
               messages.content AS message_content, messages.order_index AS message_order_index
        FROM interview_evaluations AS evaluations
        LEFT JOIN interview_agents AS agents ON agents.id = evaluations.agent_id
        JOIN interview_messages AS messages ON messages.id = evaluations.message_id
        WHERE evaluations.interview_id = ?
        ORDER BY messages.order_index ASC, evaluations.created_at ASC
        """,
        (interview_id,),
    )


def grade_from_score(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def pass_recommendation_from_score(score: int) -> str:
    if score >= 85:
        return "strong_pass"
    if score >= 75:
        return "pass"
    if score >= 60:
        return "borderline"
    return "no_pass"


def report_dimensions(evaluation: dict, answer: str, evidence: dict) -> dict:
    score = evaluation.get("score")
    provider = str(evaluation.get("provider") or "").strip().lower()
    model = str(evaluation.get("model") or "").strip().lower()
    if (evaluation.get("generation_status") != "succeeded"
            or evaluation.get("fallback") not in (False, 0, "0")
            or provider in {"", "local", "rules", "mock", "pending", "none", "unknown", "placeholder"}
            or model in {"", "none", "unknown"} or model.startswith(("rules", "mock", "pending", "placeholder"))
            or type(score) not in (int, float) or not 0 <= score <= 100):
        return {}
    dimensions = evaluation.get("dimension_scores")
    if not isinstance(dimensions, dict):
        dimensions = parse_json_object(dimensions)
    dimensions = {key: value for key, value in dimensions.items()
                  if key in DIMENSIONS and type(value) in (int, float) and 0 <= value <= 100}
    # 旧版 AI 评价未存引文，仅兼容当时可识别的来源；新版评价必须能逐维核对原文。
    known_legacy_source = provider in {"qwen", "dashscope", "kimi", "deepseek", "openai", "custom", "ai"}
    if evaluation.get("prompt_version") == EVALUATION_PROMPT_VERSION or not known_legacy_source:
        if not all(isinstance(evidence.get(key), str) and evidence[key].strip()
                   and evidence[key].strip() in answer for key in dimensions):
            return {}
    return dimensions


def build_ability_radar(timeline: list[dict]) -> dict:
    """先在题组内平均同一维度，再平均考察了该维度的各组。

    例如主问题和追问分别为 80、60 分，另一道主问题为 90 分，
    这一维度得到 ((80 + 60) / 2 + 90) / 2 = 80 分。多追问一次不会增加整组的权重。
    """
    groups = {}
    for answer in timeline:
        group = groups.setdefault(answer["question_group_id"], {})
        for dimension, score in answer["dimension_scores"].items():
            group.setdefault(dimension, []).append(score)
    radar = {}
    for dimension in DIMENSIONS:
        means = [average(group[dimension]) for group in groups.values() if dimension in group]
        if means:
            radar[dimension] = round(average(means))
    return radar


def build_agent_feedback(agents: list[dict], timeline: list[dict], turns=()) -> list[dict]:
    endings = {}
    labels = {"evidence_sufficient": "已收集到本轮所需的回答证据", "turn_limit": "已达到本轮回答次数上限"}
    for turn in turns:
        if turn["action"] not in {"switch_agent", "finish_interview"}:
            continue
        decision = parse_json_object(turn["decision_json"])
        reason, count = decision.get("reason"), decision.get("round_count")
        if isinstance(reason, str) and reason in labels and type(count) is int and count > 0:
            endings[turn["agent_id"]] = {
                "reason": reason, "round_count": count,
                "round_summary": f"本轮共回答 {count} 次，{labels[reason]}。",
            }
    feedback = []
    for agent in agents:
        related = [item for item in timeline if item["agent_id"] == agent["id"] and item["score"] is not None]
        radar = build_ability_radar(related)
        score = round(average(list(radar.values()))) if radar else None
        comment = "暂无有效单题评价。"
        if related:
            comment = f"根据 {len(related)} 条有效评价，综合得分 {score} 分。"
            for field, label in [("strengths", "主要优势"), ("issues", "优先改进")]:
                excerpt = next((item[field] for item in related if item[field]), "")
                if excerpt:
                    comment += f"{label}：{excerpt[:100]}。"
        feedback.append({"agent_id": agent["id"], "agent_name": agent["agent_name"],
                         "agent_type": agent["agent_type"], "score": score, "comment": comment,
                         **endings.get(agent["id"], {})})
    return feedback


def build_timeline_review(messages: list[dict], evaluations: list[dict]) -> list[dict]:
    """按作答顺序生成报告快照。追问沿用主问题的组号，显式回复按所指问题归组。"""
    by_message = {evaluation["message_id"]: evaluation for evaluation in evaluations}
    questions = {}
    latest_question = {}
    group_id = None
    timeline = []
    for message in messages:
        kind = message.get("message_type")
        if message["sender_type"] == "agent" and kind in AGENT_QUESTION_MESSAGE_TYPES:
            if kind == "question" or not group_id or message.get("agent_id") != latest_question.get("agent_id"):
                group_id = message["id"]
            latest_question = message
            questions[message["id"]] = (message, group_id)
            continue
        content = str(message.get("content") or "").strip()
        if message["sender_type"] != "candidate" or kind not in {"answer", "transcript"} or not content:
            continue
        question, root = questions.get(message.get("reply_to_message_id"), (latest_question, group_id))
        evaluation = by_message.get(message["id"], {})
        evidence = evaluation.get("dimension_evidence")
        if not isinstance(evidence, dict):
            evidence = parse_json_object(evidence)
        dimensions = report_dimensions(evaluation, content, evidence)
        status = evaluation.get("generation_status") or "pending_retry"
        if not dimensions:
            if status == "succeeded":
                status = "degraded" if evaluation.get("fallback") else "pending_retry"
            evaluation = {}
        question_content = question.get("content") or ""
        timeline.append({
            "message_id": message["id"], "order_index": message["order_index"],
            "sender_type": "candidate", "message_type": kind,
            "question_group_id": root or message["id"], "question_id": question.get("id"),
            "agent_id": question.get("agent_id") or message.get("round_agent_id") or evaluation.get("agent_id"),
            "agent_name": question.get("agent_name") or evaluation.get("agent_name"),
            "question_preview": question_content[:160], "answer_preview": content[:240],
            "content_preview": content[:80], "score": evaluation.get("score"),
            "generation_status": status,
            "dimension_scores": dimensions,
            "dimension_evidence": {key: evidence[key] for key in dimensions if key in evidence},
            "strengths": str(evaluation.get("strengths") or "")[:500],
            "issues": str(evaluation.get("issues") or "")[:500],
            "suggestions": str(evaluation.get("suggestions") or "")[:500],
        })
    return timeline


def build_scored_report(interview: dict, agents: list[dict], messages: list[dict], evaluations: list[dict], turns=()) -> dict:
    timeline = build_timeline_review(messages, evaluations)
    radar = build_ability_radar(timeline)
    # 覆盖按回答条数计算，权重按主问题分组计算；有效的 0 分也计作一次已评回答。
    scored_count = sum(item["score"] is not None for item in timeline)
    report = {
        "ability_radar": radar,
        "agent_feedback": build_agent_feedback(agents, timeline, turns),
        "timeline_review": timeline,
        "answer_count": len(timeline), "scored_answer_count": scored_count,
    }
    if not radar:
        reason = "尚无有效单题评分" if timeline else "未记录到候选人回答"
        return {
            **report, "total_score": 0, "grade": "-", "pass_recommendation": "insufficient_evidence",
            "summary": f"{reason}，无法形成综合评分或推进建议。", "suggestions": "",
            "provider": "local", "model": "evidence-check-v1", "prompt_version": REPORT_PROMPT_VERSION,
            "fallback": False, "generation_error": None, "generation_status": "insufficient_evidence",
        }
    total_score = round(average(list(radar.values())))
    return {
        **report, "total_score": total_score, "grade": grade_from_score(total_score),
        "pass_recommendation": pass_recommendation_from_score(total_score),
        "summary": f"本次面向{interview['target_role']}的面试共记录 {len(timeline)} 条回答，"
                   f"其中 {scored_count} 条有有效评分，已考察维度的综合得分为 {total_score} 分。",
        "suggestions": next((item["suggestions"] for item in timeline if item["suggestions"]), ""),
    }


def find_report_by_interview_id(interview_id: str, user_id: str) -> dict | None:
    return one(
        """
        SELECT reports.id, reports.user_id, reports.interview_id,
               interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
               reports.total_score, reports.grade, reports.pass_recommendation,
               reports.scored_answer_count, reports.answer_count,
               reports.ability_radar, reports.agent_feedback, reports.timeline_review,
               reports.summary, reports.suggestions, reports.provider, reports.model,
               reports.prompt_version, reports.generation_status, reports.generation_error,
               reports.fallback, reports.generated_at, reports.review_status,
               reports.reviewed_by, reports.reviewed_at, reports.created_at, reports.updated_at
        FROM interview_reports AS reports
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        WHERE reports.interview_id = ? AND reports.user_id = ?
        """,
        (interview_id, user_id),
    )


def find_report_by_id(report_id: str, user_id: str) -> dict | None:
    return one(
        """
        SELECT reports.id, reports.user_id, reports.interview_id,
               interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
               reports.total_score, reports.grade, reports.pass_recommendation,
               reports.scored_answer_count, reports.answer_count,
               reports.ability_radar, reports.agent_feedback, reports.timeline_review,
               reports.summary, reports.suggestions, reports.provider, reports.model,
               reports.prompt_version, reports.generation_status, reports.generation_error,
               reports.fallback, reports.generated_at, reports.review_status,
               reports.reviewed_by, reports.reviewed_at, reports.created_at, reports.updated_at
        FROM interview_reports AS reports
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        WHERE reports.id = ? AND reports.user_id = ?
        """,
        (report_id, user_id),
    )


def list_reports_by_user_id(user_id: str) -> list[dict]:
    return all_rows(
        """
        SELECT reports.id, reports.user_id, reports.interview_id,
               interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
               reports.total_score, reports.grade, reports.pass_recommendation,
               reports.scored_answer_count, reports.answer_count,
               reports.summary, reports.provider, reports.model, reports.prompt_version,
               reports.generation_status, reports.generation_error, reports.fallback,
               reports.generated_at, reports.review_status, reports.reviewed_by, reports.reviewed_at,
               reports.created_at, reports.updated_at,
               (
                 SELECT COUNT(*)
                 FROM interview_messages AS messages
                 WHERE messages.interview_id = reports.interview_id
                   AND messages.sender_type = 'agent'
                   AND messages.message_type IN ('question', 'follow_up')
                   AND TRIM(messages.content) <> ''
               ) AS question_count,
               (
                 SELECT COUNT(*)
                 FROM interview_messages AS messages
                 WHERE messages.interview_id = reports.interview_id
                   AND messages.sender_type = 'candidate'
                   AND TRIM(messages.content) <> ''
               ) AS candidate_answer_count,
               (
                 SELECT COUNT(*)
                 FROM interview_evaluations AS evaluations
                 WHERE evaluations.interview_id = reports.interview_id
               ) AS evaluation_count,
               EXISTS (
                 SELECT 1
                 FROM interview_messages AS messages
                 WHERE messages.interview_id = reports.interview_id
                   AND messages.sender_type = 'candidate'
                   AND TRIM(messages.content) <> ''
               ) AS has_candidate_answer
        FROM interview_reports AS reports
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        WHERE reports.user_id = ?
        ORDER BY reports.updated_at DESC, reports.created_at DESC
        """,
        (user_id,),
    )


def list_full_reports_by_user_id(user_id: str) -> list[dict]:
    return all_rows(
        """
        SELECT reports.id, reports.user_id, reports.interview_id,
               interviews.target_role, interviews.interview_type, interviews.status AS interview_status,
               interviews.difficulty, interviews.created_at AS interview_date,
               reports.scored_answer_count, reports.answer_count,
               reports.total_score, reports.ability_radar, reports.provider, reports.model,
               reports.prompt_version, reports.generation_status, reports.generation_error,
               reports.fallback, reports.generated_at, reports.review_status,
               reports.reviewed_by, reports.reviewed_at, reports.created_at, reports.updated_at,
               EXISTS (
                 SELECT 1
                 FROM interview_messages AS messages
                 WHERE messages.interview_id = reports.interview_id
                   AND messages.sender_type = 'candidate'
                   AND TRIM(messages.content) <> ''
               ) AS has_candidate_answer
        FROM interview_reports AS reports
        JOIN interview_sessions AS interviews ON interviews.id = reports.interview_id
        WHERE reports.user_id = ?
        ORDER BY interviews.created_at ASC, interviews.id ASC
        """,
        (user_id,),
    )


def compute_dimension_trend(values: list[int]) -> str:
    if len(values) < 2:
        return "stable"
    delta = values[-1] - values[0]
    if delta >= 5:
        return "up"
    if delta <= -5:
        return "down"
    return "stable"


def is_scored_skill_report(report: dict) -> bool:
    """判断报告能否进入长期能力统计；当场可展示的部分评分仍可能不满足比较条件。"""
    status = report.get("generation_status")
    scored = report.get("scored_answer_count")
    if scored is None:
        # 老报告没有覆盖计数；失败或依靠旧规则生成的分数不可用于趋势。
        if status not in {None, "succeeded"} or report.get("fallback"):
            return False
    elif status not in {"succeeded", "degraded"} or scored <= 0 or scored != report.get("answer_count"):
        # 新报告即使摘要降级，数值仍由有效回答计算。只有所有回答补评完毕才进入趋势。
        return False
    if "has_candidate_answer" in report and not bool(report.get("has_candidate_answer")):
        return False
    return isinstance(report.get("total_score"), (int, float))


def find_user_skill_stats(user_id: str) -> dict | None:
    return one(
        """
        SELECT id, user_id, total_interviews, completed_interviews, average_total_score,
               technical_depth_avg, expression_clarity_avg, business_understanding_avg,
               dimension_trends, weak_points, recent_training_focus, updated_at
        FROM user_skill_stats
        WHERE user_id = ?
        """,
        (user_id,),
    )


def comparable_skill_reports(reports: list[dict]) -> list[dict]:
    """以最近一次有效报告为基准，仅比较同岗位、同难度、同一报告评分版本的场次。"""
    valid = [report for report in reports if is_scored_skill_report(report)]
    if not valid:
        return []
    latest = valid[-1]
    keys = ("target_role", "difficulty", "prompt_version")
    return [report for report in valid if all(report.get(key) == latest.get(key) for key in keys)]


def refresh_user_skill_stats(user_id: str) -> dict:
    interview_counts = one(
        """
        SELECT
          COUNT(*) AS total_interviews,
          SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_interviews
        FROM interview_sessions
        WHERE user_id = ?
        """,
        (user_id,),
    ) or {"total_interviews": 0, "completed_interviews": 0}
    reports = list_full_reports_by_user_id(user_id)
    scored_reports = comparable_skill_reports(reports)
    dimensions = ["technical_depth", "expression_clarity", "business_understanding"]
    dimension_values: dict[str, list[int]] = {dimension: [] for dimension in dimensions}
    for report in scored_reports:
        radar = parse_json_object(report.get("ability_radar"))
        for dimension in dimensions:
            value = radar.get(dimension)
            if isinstance(value, (int, float)):
                dimension_values[dimension].append(round(value))

    dimension_averages = {dimension: clamp_stat_score(average(values, 0)) for dimension, values in dimension_values.items()}
    dimension_trends = {dimension: compute_dimension_trend(values) for dimension, values in dimension_values.items()}
    weak_points = sorted(
        [{"dimension": dimension, "score": score} for dimension, score in dimension_averages.items() if score > 0],
        key=lambda item: item["score"],
    )[:2]
    recent_focus = scored_reports[-1]["target_role"] if scored_reports else None
    average_total_score = clamp_stat_score(average([report["total_score"] for report in scored_reports], 0))
    existing = one("SELECT id FROM user_skill_stats WHERE user_id = ?", (user_id,))
    stats_id = existing["id"] if existing else str(uuid4())

    if existing:
        db.execute(
            """
            UPDATE user_skill_stats
            SET total_interviews = ?, completed_interviews = ?, average_total_score = ?,
                technical_depth_avg = ?, expression_clarity_avg = ?, business_understanding_avg = ?,
                dimension_trends = ?, weak_points = ?, recent_training_focus = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (
                interview_counts.get("total_interviews") or 0,
                interview_counts.get("completed_interviews") or 0,
                average_total_score,
                dimension_averages["technical_depth"],
                dimension_averages["expression_clarity"],
                dimension_averages["business_understanding"],
                json.dumps(dimension_trends, ensure_ascii=False),
                json.dumps(weak_points, ensure_ascii=False),
                recent_focus,
                user_id,
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO user_skill_stats (
              id, user_id, total_interviews, completed_interviews, average_total_score,
              technical_depth_avg, expression_clarity_avg, business_understanding_avg,
              dimension_trends, weak_points, recent_training_focus
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stats_id,
                user_id,
                interview_counts.get("total_interviews") or 0,
                interview_counts.get("completed_interviews") or 0,
                average_total_score,
                dimension_averages["technical_depth"],
                dimension_averages["expression_clarity"],
                dimension_averages["business_understanding"],
                json.dumps(dimension_trends, ensure_ascii=False),
                json.dumps(weak_points, ensure_ascii=False),
                recent_focus,
            ),
        )
    db.commit()
    stats = find_user_skill_stats(user_id) or {}
    return {**stats, "valid_report_count": len(scored_reports), "valid_report_ids": [item["id"] for item in scored_reports]}


DIMENSION_LABELS = {
    "technical_accuracy": "技术准确性",
    "technical_depth": "技术深度",
    "expression_clarity": "表达清晰度",
    "business_understanding": "业务理解",
    "tradeoff_reasoning": "权衡决策",
    "risk_awareness": "风险意识",
    "result_quantification": "结果量化",
    "role_fit": "岗位匹配度",
}


def build_user_dimension_stats(user_id: str) -> list[dict]:
    reports = list_full_reports_by_user_id(user_id)
    histories: dict[str, list[dict]] = {dimension: [] for dimension in DIMENSIONS}
    for report in comparable_skill_reports(reports):
        radar = parse_json_object(report.get("ability_radar"))
        for dimension in DIMENSIONS:
            value = radar.get(dimension)
            if not isinstance(value, (int, float)):
                continue
            histories[dimension].append(
                {
                    "score": clamp_stat_score(round(value)),
                    "recorded_at": report.get("interview_date") or report.get("updated_at") or report.get("created_at"),
                    "target_role": report.get("target_role"),
                    "interview_id": report.get("interview_id"),
                }
            )

    result = []
    for dimension in DIMENSIONS:
        history = histories[dimension]
        values = [item["score"] for item in history]
        latest_score = values[-1] if values else 0
        previous_score = values[-2] if len(values) > 1 else latest_score
        result.append(
            {
                "key": dimension,
                "label": DIMENSION_LABELS.get(dimension, dimension),
                "average_score": clamp_stat_score(average(values, 0)),
                "latest_score": latest_score,
                "change": latest_score - previous_score,
                "trend": compute_dimension_trend(values),
                "evidence_count": len(values),
                "history": history[-8:],
            }
        )
    return result


def _download_json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _download_markdown_text(value: Any, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


def build_report_markdown(report: dict, candidate_name: str) -> str:
    recommendation_labels = {
        "strong_pass": "强烈建议通过",
        "pass": "建议通过",
        "borderline": "谨慎通过",
        "no_pass": "暂不建议通过",
        "insufficient_evidence": "证据不足，未作判断",
    }
    ability_radar = _download_json_value(report.get("ability_radar"), {})
    agent_feedback = _download_json_value(report.get("agent_feedback"), [])
    timeline_review = _download_json_value(report.get("timeline_review"), [])
    suggestions_value = report.get("suggestions")
    suggestions = suggestions_value if isinstance(suggestions_value, list) else str(suggestions_value or "").splitlines()
    suggestions = [str(item).strip() for item in suggestions if str(item).strip()]
    score = report.get("total_score")
    unscored = report.get("generation_status") in {"insufficient_evidence", "pending_retry", "queued", "failed"}
    score_text = "未评分" if unscored or score is None else f"{int(score)}/100"
    coverage = []
    if report.get("scored_answer_count") is not None and report.get("answer_count") is not None:
        coverage.append(f"- 有效评分覆盖：{report['scored_answer_count']}/{report['answer_count']} 条回答")
    lines = [
        "# AI 智能面试综合复盘报告",
        "",
        f"- 候选人：{_download_markdown_text(candidate_name, '候选人')}",
        f"- 应聘岗位：{_download_markdown_text(report.get('target_role'), '目标岗位')}",
        f"- 综合评分：{score_text}",
        *coverage,
        f"- 等级：{_download_markdown_text(report.get('grade'))}",
        f"- 结论：{recommendation_labels.get(report.get('pass_recommendation'), _download_markdown_text(report.get('pass_recommendation'), '待判断'))}",
        f"- 报告来源：{_download_markdown_text(report.get('provider'), 'local')} · {_download_markdown_text(report.get('model'), 'rules-v1')}",
        f"- 报告编号：{_download_markdown_text(report.get('id'))}",
        f"- 生成时间：{_download_markdown_text(report.get('updated_at') or report.get('created_at'))}",
        "",
        "## 报告摘要",
        "",
        _download_markdown_text(report.get("summary"), "暂无报告摘要。"),
    ]
    if isinstance(ability_radar, dict) and ability_radar:
        lines.extend(["", "## 能力评分", "", "| 维度 | 分数 |", "| --- | ---: |"])
        for dimension, score in ability_radar.items():
            safe_dimension = _download_markdown_text(dimension).replace("|", "\\|")
            lines.append(f"| {safe_dimension} | {int(score or 0)}/100 |")
    if suggestions:
        lines.extend(["", "## 训练建议", ""])
        lines.extend(f"- {item}" for item in suggestions)
    if isinstance(agent_feedback, list) and agent_feedback:
        lines.extend(["", "## 面试官综合评价", ""])
        for item in agent_feedback:
            if not isinstance(item, dict):
                continue
            lines.extend([
                f"### {_download_markdown_text(item.get('agent_name'), 'AI 面试官')}",
                "",
                _download_markdown_text(item.get("comment"), "暂无评价。"),
                "",
            ])
            if item.get("round_summary"):
                lines.extend([str(item["round_summary"]), ""])
    answers = [item for item in timeline_review if isinstance(item, dict) and item.get("sender_type") == "candidate"] if isinstance(timeline_review, list) else []
    if answers:
        lines.extend(["", "## 逐题问答复盘", ""])
        for index, item in enumerate(answers, start=1):
            lines.extend([
                f"### 第 {index} 轮 · {_download_markdown_text(item.get('agent_name'), 'AI 面试官')}",
                "",
                f"**问题：** {_download_markdown_text(item.get('question_preview'), '未记录对应问题')}",
                "",
                f"**回答：** {_download_markdown_text(item.get('answer_preview') or item.get('content_preview'), '未记录候选人回答')}",
                "",
                f"**得分：** {item['score']}/100" if item.get("score") is not None else "**得分：** 未评分",
                "",
                f"**亮点：** {_download_markdown_text(item.get('strengths'), '暂无')}",
                "",
                f"**问题：** {_download_markdown_text(item.get('issues'), '暂无')}",
                "",
                f"**建议：** {_download_markdown_text(item.get('suggestions'), '暂无')}",
                "",
            ])
            evidence = item.get("dimension_evidence")
            dimensions = item.get("dimension_scores")
            if isinstance(evidence, dict) and isinstance(dimensions, dict):
                for key, excerpt in evidence.items():
                    if key in DIMENSION_LABELS and key in dimensions and excerpt:
                        lines.append(f"- {DIMENSION_LABELS[key]} {dimensions[key]} 分，作答依据：“{excerpt}”")
                lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_report_download_filename(report: dict) -> str:
    role = re.sub(r'[^\w\u4e00-\u9fff.-]+', '-', str(report.get("target_role") or "目标岗位"), flags=re.UNICODE).strip("-._")[:80]
    created_date = str(report.get("updated_at") or report.get("created_at") or datetime.now(timezone.utc).date())[:10]
    return f"面试复盘报告-{role or '目标岗位'}-{created_date}.md"
