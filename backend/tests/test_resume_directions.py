from backend.src.kimi_followup import (
    _normalize_resume_analysis,
    build_local_direction_recommendations,
    build_local_resume_analysis,
    resume_analysis_source_text,
)


def test_local_resume_analysis_recommends_multiple_evidence_based_directions():
    analysis = build_local_resume_analysis(
        {
            "education_level": "信息安全技术应用专业",
            "skills": "Linux、Python、网络安全、日志分析",
            "project_keywords": "安全防护、数据库",
            "project_experience": "旧资料：负责 Vue 前端页面开发。",
            "resume_text": "信息安全专业，负责校园网络安全防护项目，使用 Linux、Python 分析日志并维护数据库。",
        }
    )

    directions = analysis["recommended_directions"]
    assert len(directions) == 3
    assert directions[0]["name"] == "信息安全运维工程师"
    assert directions[0]["reasons"]
    assert directions[0]["gaps"]
    assert directions[0]["evidence"]
    assert directions[0]["name"] != "AI 应用开发工程师"


def test_current_resume_is_authoritative_and_old_profile_fields_are_ignored():
    source = resume_analysis_source_text(
        {
            "target_role": "后端开发工程师",
            "skills": "Java、Spring",
            "project_experience": "旧简历：后端接口和数据库开发",
            "resume_text": "当前简历：React、TypeScript、Vue 前端组件开发",
        }
    )

    assert source == "当前简历：React、TypeScript、Vue 前端组件开发"
    assert "旧简历" not in source
    assert "后端开发工程师" not in source


def test_generic_ai_word_does_not_force_ai_direction():
    analysis = build_local_resume_analysis(
        {
            "skills": "HTML、CSS、JavaScript、Vue",
            "project_experience": "负责前端页面和组件开发，学习中使用过 AI 辅助工具。",
        }
    )

    assert analysis["recommended_directions"][0]["name"] == "前端开发工程师"


def test_direction_scores_distinguish_core_and_generic_evidence():
    directions = build_local_direction_recommendations(
        {},
        "负责运维、Docker、部署，也参与前端 HTML、CSS 和后端 Python 接口开发",
    )

    scores = {item["name"]: item["score"] for item in directions}
    assert scores["云计算与运维工程师"] > scores["后端开发工程师"]
    assert scores["后端开发工程师"] > scores["前端开发工程师"]


def test_provider_directions_are_normalized_and_score_is_bounded():
    normalized = _normalize_resume_analysis(
        {
            "candidate_summary": "测试候选人",
            "recommended_directions": [
                {
                    "name": "自定义岗位",
                    "score": 130,
                    "reasons": "项目、技能",
                    "gaps": ["补充实践"],
                    "evidence": ["作品"],
                }
            ],
        }
    )

    assert normalized["recommended_directions"] == [
        {
            "name": "自定义岗位",
            "score": 100,
            "reasons": ["项目", "技能"],
            "gaps": ["补充实践"],
            "evidence": ["作品"],
        }
    ]


def test_provider_summary_is_structured_safely_and_directions_are_sorted():
    normalized = _normalize_resume_analysis(
        {
            "candidate_summary": {
                "name": "不应展示的姓名",
                "phone": "18520707661",
                "email": "private@example.com",
                "major": "信息安全技术应用",
                "career_goal": "希望从事安全工程工作",
                "personal_overview": "具备网络安全项目实践",
            },
            "recommended_directions": [
                {"name": "后端开发工程师", "score": 75},
                {"name": "安全防御工程师", "score": 80},
            ],
        }
    )

    assert normalized["candidate_summary"] == "具备网络安全项目实践；信息安全技术应用；希望从事安全工程工作"
    assert "18520707661" not in normalized["candidate_summary"]
    assert "private@example.com" not in normalized["candidate_summary"]
    assert [item["name"] for item in normalized["recommended_directions"]] == ["安全防御工程师", "后端开发工程师"]
