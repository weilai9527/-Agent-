import json

import pytest

from shared.offline_fixture import enable_offline_fixture
enable_offline_fixture()
from backend.offline.main import build_report_markdown, build_scored_report


def message(id_, kind, order, **fields):
    sender = "agent" if kind in {"question", "follow_up"} else "candidate"
    return {"id": id_, "message_type": kind, "sender_type": sender, "content": id_,
            "order_index": order, **fields}


def evaluation(message_id, dimensions, **fields):
    return {"message_id": message_id, "score": 70, "provider": "qwen", "model": "qwen-plus",
            "fallback": 0, "generation_status": "succeeded",
            "dimension_scores": json.dumps(dimensions), **fields}


def test_followups_share_weight_and_explicit_answer_links_survive_a_new_question():
    messages = [
        message("q1", "question", 0, agent_id="a"),
        message("a1", "answer", 1),
        message("f1", "follow_up", 2, agent_id="a"),
        message("q2", "question", 3, agent_id="b"),
        message("late", "transcript", 4, reply_to_message_id="f1"),
        message("a2", "answer", 5),
        message("waiting", "answer", 6),
        message("empty", "answer", 7, content=" "),
    ]
    evaluations = [
        evaluation("a1", {"technical_depth": 60, "role_fit": 80}),
        evaluation("late", {"technical_depth": 100}),
        evaluation("a2", {"technical_depth": 0}, score=0),
        evaluation("waiting", {"technical_depth": 99}, fallback=1),
        evaluation("q2", {"technical_depth": 99}),
    ]
    agents = [{"id": key, "agent_type": "technical", "agent_name": key} for key in ["a", "b", "c"]]
    report = build_scored_report({"target_role": "工程师"}, agents, messages, evaluations)
    assert report["ability_radar"] == {"technical_depth": 40, "role_fit": 80}
    assert report["total_score"] == 60
    assert report["grade"] == "D"
    assert report["pass_recommendation"] == "borderline"
    assert (report["scored_answer_count"], report["answer_count"]) == (3, 4)
    assert [item["score"] for item in report["agent_feedback"]] == [80, 0, None]
    assert [item["question_group_id"] for item in report["timeline_review"]] == ["q1", "q1", "q2", "q2"]
    assert [item["score"] for item in report["timeline_review"]][-2:] == [0, None]
    markdown = build_report_markdown(report, "学生")
    assert "**得分：** 0/100" in markdown
    assert "**得分：** 未评分" in markdown
    assert "有效评分覆盖：3/4" in markdown


@pytest.mark.parametrize("fields", [
    {"fallback": 1}, {"fallback": None}, {"generation_status": "pending_retry"},
    {"generation_status": "failed"}, {"generation_status": "degraded"},
    {"provider": None}, {"model": "rules-v1"}, {"score": None},
    {"dimension_scores": '{"technical_depth":null,"role_fit":true,"other":90}'},
])
def test_unverified_rows_do_not_contribute_or_appear_as_scored_feedback(fields):
    report = build_scored_report({"target_role": "工程师"}, [], [message("a", "answer", 1)],
                                  [evaluation("a", {"role_fit": 75}, strengths="未证实的优点", **fields)])
    assert report["generation_status"] == report["pass_recommendation"] == "insufficient_evidence"
    assert report["scored_answer_count"] == 0 and report["answer_count"] == 1
    assert report["ability_radar"] == {}
    assert report["timeline_review"][0]["score"] is None
    assert report["timeline_review"][0]["strengths"] == ""


def test_timeline_exposes_retry_status_and_current_evidence_for_new_provider():
    from backend.src.ai_evaluation import EVALUATION_PROMPT_VERSION

    answers = [message(key, "answer", i) for i, key in enumerate(["quoted", "bad quote", "missing", "degraded"])]
    scores = [
        evaluation("quoted", {"role_fit": 70}, provider="future-ai", prompt_version=EVALUATION_PROMPT_VERSION,
                   dimension_evidence='{"role_fit":"quoted"}'),
        evaluation("bad quote", {"role_fit": 70}, prompt_version=EVALUATION_PROMPT_VERSION,
                   dimension_evidence='{"role_fit":"not in answer"}'),
        evaluation("degraded", {}, generation_status="degraded", fallback=1),
    ]
    timeline = build_scored_report({"target_role": "工程师"}, [], answers, scores)["timeline_review"]
    assert [item["generation_status"] for item in timeline] == ["succeeded", "pending_retry", "pending_retry", "degraded"]
    assert timeline[0]["dimension_evidence"] == {"role_fit": "quoted"}
    assert [item["score"] for item in timeline] == [70, None, None, None]
