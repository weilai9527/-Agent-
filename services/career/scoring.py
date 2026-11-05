"""按学校策略选用模型生成建议，只发送固定词表中的规则匹配证据。"""
import json

from fastapi import HTTPException

from services.profile import model_policy
from shared.recruitment import SKILL_LEXICON, score_resume_against_posting


JOB_MATCH_PROMPT_VERSION = "job-match-v1"
JOB_MATCH_SYSTEM = (
    "你是中文求职顾问。只输出一个 JSON 对象，不要输出 Markdown，也不要编造简历中不存在的经历。"
    "建议必须具体、可执行，并与岗位要求逐条对应；每条不超过 80 个汉字。"
)
JOB_MATCH_SCHEMA = {
    "summary": "",
    "strengths": [""],
    "gaps": [""],
    "suggestions": [""],
    "interviewFocus": [""],
}


def _normalize_list(value, limit: int = 5, max_length: int = 120) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, str)]
    else:
        return []
    result: list[str] = []
    for item in items:
        text = " ".join(str(item).split()).strip()
        if not text:
            continue
        result.append(text[:max_length])
        if len(result) >= limit:
            break
    return result


def advice_messages(result):
    # 本地规则会保留词典外的技能，其中可能含粘贴的私人文本，向外部仅发送词典项和累计数量。
    findings = {
        "matchScore": result["matchScore"],
        "matchedSkills": [key for key in result["matchedSkills"] if key in SKILL_LEXICON],
        "missingSkills": [key for key in result["missingSkills"] if key in SKILL_LEXICON],
        "requirements": {status: sum(item["status"] == status for item in result["matrices"])
                         for status in ("satisfied", "partial", "missing")},
    }
    return [{"role": "system", "content": JOB_MATCH_SYSTEM},
            {"role": "user", "content": "根据以下规则匹配结果给出求职建议。\n"
             + json.dumps(findings, ensure_ascii=False)
             + "\n请严格返回以下 JSON 结构：\n" + json.dumps(JOB_MATCH_SCHEMA, ensure_ascii=False)}]


def _valid_advice(reply):
    if not isinstance(reply, dict):
        return {}
    advice = {}
    summary = reply.get("summary")
    if isinstance(summary, str) and summary.strip():
        advice["summary"] = " ".join(summary.split())[:400]
    for field in ("strengths", "gaps", "suggestions", "interviewFocus"):
        items = _normalize_list(reply.get(field))
        if items:
            advice[field] = items
    return advice


def score_and_enhance(school_id, *, resume_text, resume_skills="", target_role="", posting, plan=None):
    school_policy = plan is None
    if school_policy:
        plan = model_policy.select_model(school_id, task="career")
    result = score_resume_against_posting(resume_text=resume_text, resume_skills=resume_skills,
                                          target_role=target_role, posting=posting)
    for item in result["matrices"]:
        item["evidence"] = "、".join(item.get("matched") or [])
    result.update(provider="local", model="rules-v1", fallback=False, promptVersion=JOB_MATCH_PROMPT_VERSION)
    if plan.provider == "local":
        return result
    original_policy = plan.cache_key
    try:
        advice = _valid_advice(plan.generate(advice_messages(result)))
    except model_policy.ModelUnavailable:
        advice = {}
    if school_policy and model_policy.select_model(school_id, task="career").cache_key != original_policy:
        raise HTTPException(409, "学校模型配置已更新，请重新对比。")
    if not advice:
        result["fallback"] = True
        return result
    result.update(advice, provider=plan.provider, model=plan.model)
    return result
