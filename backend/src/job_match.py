"""单校旧部署的岗位建议入口，使用本地评分并过滤隐私信息。"""
from typing import Any

from services.career.scoring import JOB_MATCH_PROMPT_VERSION, score_and_enhance
from services.profile.model_policy import legacy_model


def build_job_match(
    *,
    resume_text: str,
    resume_skills: str = "",
    target_role: str = "",
    posting: dict[str, Any],
) -> dict[str, Any]:
    # 旧部署明确绑定一所学校。涉及私密信息的任务遵循专用模型策略，禁用通用供应商顺序和跨供应商重试。
    return score_and_enhance(None, resume_text=resume_text, resume_skills=resume_skills,
                             target_role=target_role, posting=posting, plan=legacy_model("career"))
