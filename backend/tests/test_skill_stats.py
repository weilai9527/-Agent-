from shared.offline_fixture import enable_offline_fixture
enable_offline_fixture()
from backend.offline import main


def test_build_user_dimension_stats_aggregates_all_report_dimensions(monkeypatch):
    reports = [
        {
            "interview_id": "interview-1",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-01 10:00:00",
            "total_score": 66,
            "ability_radar": '{"technical_depth": 60, "expression_clarity": 72}',
        },
        {
            "interview_id": "interview-2",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-08 10:00:00",
            "total_score": 74,
            "ability_radar": '{"technical_depth": 70, "expression_clarity": 78}',
        },
        {
            "interview_id": "interview-queued",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-09 10:00:00",
            "total_score": 99,
            "generation_status": "queued",
            "has_candidate_answer": 1,
            "ability_radar": '{"technical_depth": 99, "role_fit": 99}',
        },
        {
            "interview_id": "interview-zero",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-10 10:00:00",
            "total_score": 0,
            "generation_status": "succeeded",
            "has_candidate_answer": 1,
            "ability_radar": '{"role_fit": 0}',
        },
    ]
    monkeypatch.setattr(main, "list_full_reports_by_user_id", lambda _user_id: reports)

    dimensions = main.build_user_dimension_stats("user-1")
    by_key = {item["key"]: item for item in dimensions}

    assert len(dimensions) == 8
    assert by_key["technical_depth"]["average_score"] == 65
    assert by_key["technical_depth"]["latest_score"] == 70
    assert by_key["technical_depth"]["change"] == 10
    assert by_key["technical_depth"]["trend"] == "up"
    assert by_key["technical_depth"]["evidence_count"] == 2
    assert [item["score"] for item in by_key["technical_depth"]["history"]] == [60, 70]
    assert by_key["role_fit"]["average_score"] == 0
    assert by_key["role_fit"]["latest_score"] == 0
    assert by_key["role_fit"]["evidence_count"] == 1


def test_skill_report_filter_excludes_unfinished_and_missing_evidence():
    assert main.is_scored_skill_report({"generation_status": "succeeded", "has_candidate_answer": 1, "total_score": 0})
    assert not main.is_scored_skill_report({"generation_status": "degraded", "has_candidate_answer": 1, "total_score": 60})
    covered = {"generation_status": "degraded", "total_score": 60, "answer_count": 2, "scored_answer_count": 2}
    assert main.is_scored_skill_report(covered)
    assert not main.is_scored_skill_report({**covered, "scored_answer_count": 1})
    assert not main.is_scored_skill_report({"generation_status": "queued", "has_candidate_answer": 1, "total_score": 0})
    assert not main.is_scored_skill_report({"generation_status": "failed", "has_candidate_answer": 1, "total_score": 80})
    assert not main.is_scored_skill_report({"generation_status": "succeeded", "has_candidate_answer": 0, "total_score": 80})


def test_trends_only_compare_latest_role_difficulty_and_scoring_version():
    target = {
        "target_role": "算法", "difficulty": "标准", "prompt_version": "report-v5",
        "generation_status": "succeeded", "total_score": 78,
        "answer_count": 2, "scored_answer_count": 2,
    }
    reports = [
        {**target, "id": "first"}, {**target, "prompt_version": "report-v4"},
        {**target, "target_role": "安全"}, {**target, "difficulty": "挑战"},
        {**target, "id": "latest"}, {**target, "scored_answer_count": 1},
    ]
    assert [report["id"] for report in main.comparable_skill_reports(reports)] == ["first", "latest"]
