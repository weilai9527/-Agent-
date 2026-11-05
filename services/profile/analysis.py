"""简历证据的本地提取、方向推断与模型返回值的结构化处理。"""
import re
from typing import Any


def _normalize_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:limit]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、\n]", value) if item.strip()][:limit]
    return []


def resume_analysis_source_text(profile: dict[str, Any] | None) -> str:
    """优先采用当前简历正文；旧表单没有正文时才组合已保存的简历字段。"""
    if not profile:
        return ""
    resume_text = str(profile.get("resume_text") or "").strip()
    if resume_text:
        return resume_text
    fallback_fields = [
        profile.get("education_level"),
        profile.get("experience_level") or profile.get("years_of_experience"),
        profile.get("skills"),
        profile.get("project_keywords"),
        profile.get("project_experience"),
    ]
    return "\n".join(str(item).strip() for item in fallback_fields if str(item or "").strip())


def _redact_personal_info(value: str) -> str:
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[邮箱已隐藏]", value, flags=re.I)
    text = re.sub(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_candidate_summary(value: Any) -> str:
    fallback = "候选人有项目经历，可围绕真实职责、技术方案和结果指标继续验证岗位适配度。"
    if isinstance(value, str):
        summary = value
    elif isinstance(value, dict):
        safe_keys = (
            "candidate_overview",
            "personal_overview",
            "major",
            "education_level",
            "experience_level",
            "career_goal",
            "strengths",
        )
        parts = []
        for key in safe_keys:
            raw_item = value.get(key)
            if isinstance(raw_item, str) and raw_item.strip():
                parts.append(raw_item.strip())
            elif isinstance(raw_item, list):
                parts.extend(str(item).strip() for item in raw_item if isinstance(item, (str, int, float)) and str(item).strip())
        summary = "；".join(parts)
    else:
        summary = ""
    return (_redact_personal_info(summary) or fallback)[:240]


def _normalize_resume_analysis(value: dict[str, Any]) -> dict[str, Any]:
    projects = []
    raw_projects = value.get("projects")
    if isinstance(raw_projects, list):
        for item in raw_projects[:5]:
            if not isinstance(item, dict):
                continue
            projects.append(
                {
                    "name": str(item.get("name") or "未命名项目").strip()[:80],
                    "role": str(item.get("role") or "参与者").strip()[:80],
                    "highlights": _normalize_list(item.get("highlights"), 6),
                    "possible_questions": _normalize_list(item.get("possible_questions"), 6),
                }
            )
    directions = []
    raw_directions = value.get("recommended_directions")
    if isinstance(raw_directions, list):
        for item in raw_directions[:4]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:80]
            if not name:
                continue
            try:
                score = int(float(item.get("score") or 0))
            except (TypeError, ValueError):
                score = 0
            directions.append(
                {
                    "name": name,
                    "score": max(1, min(100, score)),
                    "reasons": _normalize_list(item.get("reasons"), 4),
                    "gaps": _normalize_list(item.get("gaps"), 4),
                    "evidence": _normalize_list(item.get("evidence"), 5),
                }
            )
    directions.sort(key=lambda item: (-item["score"], item["name"]))
    return {
        "candidate_summary": _normalize_candidate_summary(value.get("candidate_summary")),
        "core_skills": _normalize_list(value.get("core_skills"), 12),
        "projects": projects,
        "risk_points": _normalize_list(value.get("risk_points"), 8),
        "recommended_directions": directions,
    }


LOCAL_DIRECTION_PROFILES = [
    {
        "name": "信息安全运维工程师",
        "keywords": ["信息安全", "网络安全", "安全防护", "防火墙", "日志分析", "应急响应", "漏洞", "linux", "网络"],
        "weights": {"信息安全": 18, "网络安全": 18, "安全防护": 14, "防火墙": 10, "日志分析": 10, "应急响应": 14, "漏洞": 8, "linux": 5, "网络": 4},
        "gaps": ["补充 Linux 与网络运维实践", "准备安全事件分析或应急响应案例"],
    },
    {
        "name": "渗透测试工程师",
        "keywords": ["渗透测试", "web安全", "漏洞复现", "burp", "sql注入", "xss", "攻防", "ctf"],
        "weights": {"渗透测试": 20, "web安全": 14, "漏洞复现": 16, "burp": 10, "sql注入": 10, "xss": 10, "攻防": 12, "ctf": 10},
        "gaps": ["补充合法授权下的渗透测试项目", "说明漏洞验证、修复与复测闭环"],
    },
    {
        "name": "后端开发工程师",
        "keywords": ["后端", "python", "java", "spring", "fastapi", "django", "接口", "数据库", "mysql", "redis"],
        "weights": {"后端": 18, "python": 5, "java": 7, "spring": 12, "fastapi": 12, "django": 10, "接口": 8, "数据库": 8, "mysql": 7, "redis": 7},
        "gaps": ["补充接口设计和数据库建模证据", "准备性能、异常处理与部署案例"],
    },
    {
        "name": "前端开发工程师",
        "keywords": ["前端", "html", "css", "javascript", "typescript", "react", "vue", "vite", "组件"],
        "weights": {"前端": 18, "html": 6, "css": 6, "javascript": 7, "typescript": 8, "react": 12, "vue": 12, "vite": 7, "组件": 8},
        "gaps": ["补充完整前端项目和个人职责", "准备工程化、性能与兼容性案例"],
    },
    {
        "name": "AI 应用开发工程师",
        "keywords": ["大模型", "智能体", "agent", "llm", "rag", "向量数据库", "模型部署", "提示词工程", "ai聊天机器人"],
        "weights": {"大模型": 18, "智能体": 16, "agent": 14, "llm": 14, "rag": 14, "向量数据库": 12, "模型部署": 10, "提示词工程": 8, "ai聊天机器人": 14},
        "gaps": ["补充大模型应用的真实业务场景", "说明评估方法、模型边界和失败案例"],
    },
    {
        "name": "测试开发工程师",
        "keywords": ["软件测试", "自动化测试", "测试用例", "pytest", "selenium", "接口测试", "质量保障"],
        "weights": {"软件测试": 18, "自动化测试": 16, "测试用例": 12, "pytest": 9, "selenium": 12, "接口测试": 14, "质量保障": 12},
        "gaps": ["补充测试设计与缺陷闭环案例", "准备自动化测试或质量平台实践"],
    },
    {
        "name": "数据分析师",
        "keywords": ["数据分析", "pandas", "numpy", "sql", "tableau", "power bi", "可视化", "统计分析"],
        "weights": {"数据分析": 18, "pandas": 10, "numpy": 8, "sql": 7, "tableau": 12, "power bi": 12, "可视化": 8, "统计分析": 14},
        "gaps": ["补充数据分析问题与业务结论", "说明数据清洗、指标口径和验证过程"],
    },
    {
        "name": "云计算与运维工程师",
        "keywords": ["云计算", "运维", "docker", "kubernetes", "k8s", "部署", "监控", "nginx", "服务器"],
        "weights": {"云计算": 18, "运维": 16, "docker": 12, "kubernetes": 16, "k8s": 16, "部署": 7, "监控": 10, "nginx": 8, "服务器": 6},
        "gaps": ["补充部署、监控和故障处理实践", "准备稳定性与自动化运维案例"],
    },
]


def _contains_direction_keyword(text: str, keyword: str) -> bool:
    lowered = keyword.lower()
    if re.fullmatch(r"[a-z0-9.+# -]+", lowered):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", text))
    return lowered in text


def build_local_direction_recommendations(profile: dict[str, Any], source_text: str) -> list[dict[str, Any]]:
    text = source_text.lower()
    results = []
    for direction in LOCAL_DIRECTION_PROFILES:
        hits = [keyword for keyword in direction["keywords"] if _contains_direction_keyword(text, keyword)]
        weights = direction.get("weights") or {}
        evidence_score = sum(int(weights.get(keyword, 6)) for keyword in hits)
        category_project_evidence = bool(hits and re.search(r"项目|负责|实现|开发|部署|优化|比赛|竞赛", source_text.lower()))
        score = min(94, 24 + evidence_score + (5 if category_project_evidence else 0))
        results.append(
            {
                "name": direction["name"],
                "score": score,
                "reasons": [f"简历中体现了{keyword}" for keyword in hits[:3]] or ["当前证据较少，可作为探索方向"],
                "gaps": direction["gaps"][:2],
                "evidence": hits[:5],
                "evidence_score": evidence_score,
            }
        )
    results.sort(key=lambda item: (-item["score"], -item["evidence_score"], item["name"]))
    for item in results:
        item.pop("evidence_score", None)
    return results[:3]


def build_local_resume_analysis(profile: dict[str, Any]) -> dict[str, Any]:
    skills = _normalize_list(profile.get("skills"), 12)
    keywords = _normalize_list(profile.get("project_keywords"), 12)
    source_text = resume_analysis_source_text(profile)
    recommended_directions = build_local_direction_recommendations(profile, source_text)
    if str(profile.get("resume_text") or "").strip():
        evidence = list(dict.fromkeys(item for direction in recommended_directions for item in direction.get("evidence", [])))
        skills = evidence[:12]
        keywords = []
    project_name = keywords[0] if keywords else "核心项目"
    highlights = keywords[:4] or skills[:4] or ["项目背景", "技术方案", "个人职责"]
    possible_questions = [
        f"{project_name}当时要解决什么业务问题？",
        "你具体负责了哪一层，和其他角色如何协作？",
        "最终效果如何衡量，有哪些量化指标？",
    ]
    if re.search(r"性能|优化|耗时|加载|渲染", source_text):
        possible_questions.append("性能瓶颈是如何定位和验证优化效果的？")
    risk_points = ["结果指标不够明确", "个人职责边界需要继续确认"]
    if not skills:
        risk_points.append("技能标签较少，需要从项目回答中反推技术深度")
    summary_bits = [profile.get("experience_level") or profile.get("years_of_experience") or "有一定经验"]
    direction_summary = "、".join(item["name"] for item in recommended_directions[:2]) or "待探索方向"
    return {
        "candidate_summary": f"{summary_bits[0]}，当前证据更接近{direction_summary}；推荐结果需由学生结合个人意愿确认。",
        "core_skills": skills or keywords[:8],
        "projects": [
            {
                "name": project_name,
                "role": "候选人简历相关项目参与者",
                "highlights": highlights,
                "possible_questions": possible_questions[:6],
            }
        ],
        "risk_points": risk_points[:8],
        "recommended_directions": recommended_directions,
    }
