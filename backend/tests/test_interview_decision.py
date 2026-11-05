import unittest

from backend.src.interview_decision import decide_turn


AGENTS = [{"id": kind, "agent_type": kind, "order_index": i, "status": "pending"}
          for i, kind in enumerate(("technical", "architecture", "hr"))]
DETAILS = "业务目标是减少下单等待。我负责支付链路改造。我采用分层缓存方案。接口延迟从800ms降到300ms。"


def history(role, answers):
    result = []
    for i, content in enumerate(answers):
        qid = f"{role}-q{i}"
        result.extend([{"id": qid, "sender_type": "agent", "message_type": "question", "agent_id": role},
                       {"id": f"{role}-{i}", "sender_type": "candidate", "reply_to_message_id": qid, "content": content}])
    return result


def decide(index, messages, content="不知道"):
    return decide_turn(interview={"target_role": "后端开发"}, agents=AGENTS, active_agent=AGENTS[index],
                       messages=messages, answer={"id": "current", "content": content})


class DecisionTests(unittest.TestCase):
    def test_technical_coverage_requires_details_and_minimum(self):
        self.assertEqual(decide(0, history("technical", [DETAILS] * 3))["action"], "ask_follow_up")
        messages = history("technical", [DETAILS] * 4)
        result = decide(0, messages)
        self.assertEqual((result["action"], result["reason"]), ("switch_agent", "evidence_sufficient"))
        self.assertEqual(result, decide(0, messages))
        self.assertEqual(result["next_agent_id"], "architecture")
        for item in result["handoff"]["confirmed"]:
            self.assertIn(item["quote"], DETAILS)
            self.assertEqual(item["answer_id"], "technical-0")
        self.assertIn("我采用分层缓存方案", result["question"])

    def test_negation_and_mentions_only_do_not_certify(self):
        result = decide(0, [], "我没看过延迟300ms这个指标，监控错误率是同事做的。方案、风险、权衡、业务。")
        self.assertEqual(result["evidence"]["metrics"]["status"], "mentioned")
        self.assertEqual(result["evidence"]["risk"]["status"], "mentioned")
        self.assertFalse(any(v["status"] == "supported" for v in result["evidence"].values()))

    def test_limit_does_not_claim_sufficient_evidence(self):
        result = decide(0, history("technical", ["不知道"] * 6))
        self.assertEqual(result["reason"], "turn_limit")
        self.assertEqual(result["handoff"]["confirmed"], [])
        self.assertNotIn("足够", result["closing"])

    def test_architecture_detailed_answers_can_finish_after_four(self):
        content = "我采用分层缓存方案。接口延迟从800ms降到300ms。选择缓存因为读取流量很高。复盘后我补充了压测场景。"
        history_items = history("architecture", [content] * 3)
        result = decide(1, history_items, content)
        self.assertEqual((result["action"], result["round_count"], result["reason"]),
                         ("switch_agent", 4, "evidence_sufficient"))
        self.assertIn("有没有需要和他人达成共识", result["question"])

    def test_earlier_roles_never_satisfy_new_goals(self):
        messages = history("technical", [DETAILS] * 5) + history("architecture", ["不知道"] * 3)
        result = decide(1, messages)
        self.assertEqual((result["action"], result["round_count"]), ("ask_follow_up", 4))
        self.assertTrue(all(item["status"] == "unseen" for item in result["evidence"].values()))
        result = decide(1, messages + history("architecture", ["不知道"] * 2))
        self.assertEqual((result["action"], result["next_agent_id"]), ("switch_agent", "hr"))
        self.assertIn("后端开发", result["question"])

    def test_qualifications_and_configured_numbers_do_not_confirm_observations(self):
        for content in ("我没有参与，采用了分层缓存方案。", "接口延迟从800ms降到300ms，我不确定。",
                        "如果后面需要，我负责支付链路改造。", "接口延迟阈值设为300ms。"):
            with self.subTest(content=content):
                evidence = decide(0, [], content)["evidence"]
                self.assertNotIn("supported", [item["status"] for item in evidence.values()])

    def test_rejected_solution_only_supports_the_reason_for_the_tradeoff(self):
        evidence = decide(0, [], "没有选择采用分层缓存方案因为库存要求强一致性。")["evidence"]
        self.assertEqual(evidence["solution"]["status"], "mentioned")
        self.assertEqual(evidence["tradeoff"]["status"], "supported")

    def test_explicit_reply_never_defaults_to_nearest_role(self):
        messages = history("architecture", [DETAILS])
        messages[-1]["reply_to_message_id"] = "missing"
        result = decide(1, messages)
        self.assertEqual(result["round_count"], 1)
        self.assertTrue(all(item["status"] == "unseen" for item in result["evidence"].values()))

    def test_handoff_uses_an_available_confirmed_quote_outside_preferred_dimensions(self):
        result = decide(0, history("technical", ["业务目标是减少下单等待。"] * 6))
        self.assertEqual(result["reason"], "turn_limit")
        self.assertIn(result["handoff"]["confirmed"][0]["quote"], result["question"])
        self.assertEqual(result["handoff"]["confirmed"][0]["answer_id"], "technical-0")

    def test_historical_roles_and_hr_limit(self):
        messages = history("hr", ["a", "b"])
        for item in messages:
            item.pop("reply_to_message_id", None)
        result = decide(2, messages)
        self.assertEqual((result["action"], result["round_count"], result["reason"]), ("finish_interview", 3, "turn_limit"))

    def test_saved_round_agent_overrides_proximity(self):
        messages = history("architecture", [DETAILS])
        messages[-1]["round_agent_id"] = "technical"
        self.assertEqual(decide(1, messages)["round_count"], 1)


if __name__ == "__main__":
    unittest.main()


def test_architecture_live_transcript_replay_text_and_rtc(monkeypatch):
    from backend.src.interview_decision import ANSWER_CONTEXT_POLICY
    from backend.src.kimi_followup import _build_messages, generate_kimi_followup
    from shared.offline_fixture import enable_offline_fixture
    enable_offline_fixture()
    from backend.offline.main import build_rtc_ai_agent_prompt

    agent = {**AGENTS[1], "agent_name": "架构面试官", "status": "active"}
    messages = []
    question = "如果规模扩大，你会先检查哪部分设计？"
    replies = [
        "我会先设计高并发部分虽然我现在还不知道怎么设计但是我认为规模亏大了之后最应该做的事先做好流量规划在大规模的流量进来的时候活下来",
        "这边我们还没做我也还没有学习这部分是我们正在准备的地方",
        "这个我也不会",
    ]
    seen = []
    monkeypatch.setattr("backend.src.kimi_followup._provider_order", lambda: [])
    for i, content in enumerate(replies):
        messages.append({"id": f"q{i}", "sender_type": "agent", "agent_id": agent["id"],
                         "message_type": "question", "content": question})
        answer = {"id": f"a{i}", "sender_type": "candidate", "reply_to_message_id": f"q{i}", "content": content}
        result = decide_turn(interview={}, agents=AGENTS, active_agent=agent, messages=messages, answer=answer)
        assert result["action"] == "ask_follow_up"
        assert result["followup_mode"] == ("hypothetical" if i == 0 else "change_topic")
        assert not any(e["status"] == "supported" for e in result["evidence"].values())
        question = result["question"]
        for decision in (result, None):  # 同时覆盖按轮次管理的面试和旧格式文本。
            text = generate_kimi_followup(interview={}, active_agent=agent, messages=messages,
                                          last_answer=content, turn_decision=decision)
            assert text["question"] == question
        seen.append(question)
        messages.append(answer)
    assert len(set(seen)) == 3
    assert "假设流量" in seen[0] and "数据会经过" in seen[1] and "网络断开" in seen[2]
    assert ANSWER_CONTEXT_POLICY in build_rtc_ai_agent_prompt({}, [agent], messages, None)
    assert ANSWER_CONTEXT_POLICY in _build_messages(interview={}, active_agent=agent, messages=messages,
                                                    last_answer=replies[-1])[0]["content"]


def test_real_implementation_with_local_negation_is_available_for_followup():
    for answer in ("我采用了分层缓存方案，但我没有做过压测。", "我采用了分层缓存方案，没有做过压测。",
                   "我没有做过压测，不过我采用了分层缓存方案。"):
        result = decide(1, [], answer)
        assert result["evidence"]["solution"]["status"] == "supported"
        assert result["followup_mode"] == "partial_experience"
        assert "我采用了分层缓存方案" in result["question"] and "压测" not in result["question"]


def test_tentative_solution_inherits_the_hypothetical_question():
    messages = history("architecture", ["我采用分层缓存方案"])
    messages[0]["content"] = "假设访问量突然增大，你会怎么设计？"
    result = decide(1, messages)
    assert result["evidence"]["solution"]["status"] == "mentioned"
