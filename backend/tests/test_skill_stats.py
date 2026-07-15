from backend.src import main


def test_build_user_dimension_stats_aggregates_all_report_dimensions(monkeypatch):
    reports = [
        {
            "interview_id": "interview-1",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-01 10:00:00",
            "ability_radar": '{"technical_depth": 60, "expression_clarity": 72}',
        },
        {
            "interview_id": "interview-2",
            "target_role": "全栈开发工程师",
            "updated_at": "2026-07-08 10:00:00",
            "ability_radar": '{"technical_depth": 70, "expression_clarity": 78}',
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
    assert by_key["role_fit"]["evidence_count"] == 0
