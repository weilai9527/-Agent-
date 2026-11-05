"""候选页面的历史字段名与表单到个人资料的映射。"""

from urllib.parse import urlsplit

from fastapi import HTTPException


PROFILE_LIMITS = {
    "nickname": 60, "target_role": 80, "experience_level": 40, "company_type": 80,
    "target_city": 80, "expected_salary": 80, "years_of_experience": 40,
    "education_level": 60, "skills": 500, "project_keywords": 500,
    "resume_text": 12000, "project_experience": 12000, "preferred_interview_type": 60,
    "preferred_difficulty": 40, "preferred_interviewer_style": 60,
    "avatar_url": 500, "portfolio_links": 1000,
}

FORM_FIELDS = {
    "college": ("学院", 160), "major": ("专业", 160),
    "professional_skills": ("职业技能与经验", 4000), "advantages": ("我的优势", 2000),
    "education": ("教育经验", 2000), "honors": ("在校荣誉/职务", 2000),
    "projects": ("项目经历", 4000), "languages": ("语言", 500), "works": ("个人作品", 2000),
    "skills": ("技能", 1000), "certificates": ("证书", 2000), "bonus": ("加分项", 1000),
}


def checked_text(body, field, limit):
    value = body.get(field)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise HTTPException(400, f"{field} 必须为 {limit} 字以内的文本。")
    if any(0xD800 <= ord(c) <= 0xDFFF or c == "\x00" for c in value):
        raise HTTPException(400, f"{field} 含无效字符。")
    return value.strip()


def profile_fields(body, existing):
    # 表单投影和旧数据可能超过个人编辑器的字数限制，作品栏也可能是说明文字。
    # 客户端回传整份资料时允许保留这些原值。
    profile = {}
    for name, limit in PROFILE_LIMITS.items():
        value = body.get(name)
        if isinstance(value, str) and value == existing.get(name):
            profile[name] = value
        else:
            profile[name] = checked_text(body, name, limit) or None
    if not profile["nickname"]:
        raise HTTPException(400, "昵称不能为空。")
    for key in ("avatar_url", "portfolio_links"):
        value = profile[key]
        if not value or value == existing.get(key):
            continue
        urls = value.split() if key == "portfolio_links" else [value]
        for url in urls:
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in {"http", "https"} and parsed.hostname and not any(c.isspace() for c in url)
            except ValueError:
                valid = False
            if not valid:
                raise HTTPException(400, f"{key} 只支持 http 或 https 链接。")
    return profile


def form_fields(body):
    return {name: checked_text(body, name, limit) for name, (_, limit) in FORM_FIELDS.items()}


def project_form(form):
    basic = "、".join(filter(None, (form["college"], form["major"])))
    parts = [f"基本信息：{basic}"] if basic else []
    for field, (label, _) in FORM_FIELDS.items():
        if field not in {"college", "major"} and form[field]:
            parts.append(f"{label}：{form[field]}")
    return {
        "resume_text": "\n\n".join(parts), "skills": form["skills"],
        "project_experience": form["projects"] or form["professional_skills"],
        "portfolio_links": form["works"], "education_level": form["education"],
    }
