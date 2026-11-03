"""Replayable round progression. Evidence describes interview coverage, not a score."""
import re


# A mention alone can suggest a follow-up. Promotion needs a more specific
# observation within the same clause, with the original words kept for audit.
# (display name, mention, observation, local follow-up)
DIMENSIONS = {
    "background": ("场景", r"业务|用户|目标|场景|问题", r"(为了解决|目标是|场景是|用户需要|业务要求).{4,}", "当时要为哪类用户解决什么具体问题？"),
    "responsibility": ("个人职责", r"负责|主导|亲自|我实现", r"我(?:个人|主要|独立|亲自)?(?:负责|主导|实现|承担|开发)(?:了)?[^，。]{4,}", "在这个例子中，你亲自完成了哪一部分？"),
    "solution": ("实现方案", r"设计|实现|拆分|缓存|接入|改造|方案|采用", r"(?:实现了|拆分为|改造了|接入了|采用了?|设计了|引入了).{4,}", "请具体说说你采用的做法，以及它如何解决当时的问题。"),
    "tradeoff": ("方案取舍", r"取舍|权衡|成本|选择|放弃|备选|相比", r"(?:为了.{2,}选择|考虑到.{2,}选择|没有选择.{2,}因为|相比.{2,}选择|放弃.{2,}因为|选择.{2,}因为).{2,}", "当时还考虑过哪种做法，为什么最终选择了当前方案？"),
    "metrics": ("结果验证", r"指标|耗时|延迟|成功率|错误率|提升|降低|降到|缩短|P95|QPS|毫秒", r"(?:实测|测得|测出|压测.{0,10}(?:为|是)|降低了?|提升了?|缩短了?|降[到至]|升[到至]|减少了?).{0,12}?\d{1,10}(?:\.\d{1,4})?\s*(?:%|％|ms|毫秒|秒|小时|分钟|倍|QPS|次/秒)", "你用什么结果判断这项改动有效？"),
    "risk": ("风险应对", r"风险|故障|异常|回滚|灰度|监控|报警|降级", r"(?:监控了?|回滚到|降级为|灰度到|配置了|设置了).{3,}(?:率|版本|流量|阈值|告警|延迟|报警)|(?:故障时|异常时|失败时).{3,}(?:回滚|降级|隔离)", "如果出现异常，你如何发现并控制影响范围？"),
    "reflection": ("复盘改进", r"复盘|后来|改进|沉淀|下次", r"(?:复盘后|下次会|后来我|改进了).{4,}", "复盘之后，你具体改变了哪项做法？"),
    "motivation": ("职业动机", r"选择|岗位|希望|职业|看重", r"(?:我看重|我希望|我选择).{4,}", "选择这个岗位时，你最看重的因素是什么？"),
    "collaboration": ("协作沟通", r"同事|团队|对齐|沟通|分歧|协调", r"(?:我协调|我组织|我与.{2,}对齐|我和.{2,}沟通).{2,}", "请举一个需要和他人达成共识的例子，你当时做了什么？"),
}
GOALS = {
    "technical": ("background", "responsibility", "solution", "tradeoff", "metrics", "risk"),
    "architecture": ("solution", "tradeoff", "metrics", "risk", "reflection"),
    "hr": ("motivation", "collaboration", "reflection"),
}
LIMITS = {"technical": (5, 7), "architecture": (4, 6), "hr": (3, 3)}
UNCONFIRMED = re.compile(
    r"不清楚|不知道|不太懂|不负责|不确定|不记得|不曾|记不清|说不清|无法确认"
    r"|没|尚未|并未|并非|不是|从未|未(?:曾|能|做|参与|验证|负责|记录|采用|实现|监控|使用|设计|测试)"
    r"|(?:同事|别人|他人)(?:主要|独立|实际)?(?:做|负责|实现|设计|采用)"
    r"|假设|如果|假如|可能|预计|估计|计划|打算|听说|目标(?:是|为)?(?:降|升|控制)"
    r"|(?:应该|可以|准备|考虑|不会|不打算)(?:采用|实现|设计|引入)"
)


ANSWER_CONTEXT_POLICY = (
    "先区分已做、设想和未实践。候选人说“我会先”或在回答假设题时，只问设想中的下一步判断，"
    "不要索取当时的 QPS、中间件、上线结果。明确没做过或不会时，立即换到当前角色的另一道基础情境题；"
    "连续答不上就换考点，勿反复要求举经历。局部没做过只限定那一部分，可以追问明确做过的事实。"
)
HYPOTHETICAL = re.compile(r"假设|假如|如果|设想|我(?:们)?会(?:先|选择|考虑|设计|采用|用|把|做)|我认为.{0,30}应该|计划|打算")
NO_PRACTICE = re.compile(r"没(?:有)?(?:做|学|实践|参与|接触|用|试|研究|经验)|未(?:实践|接触|参与|学)|正在准备|不会|不知道|不清楚|不懂|不了解|不熟悉|答不上|想不起来")
UNTRIED = re.compile(r"(?:没(?:有)?|尚未|还未)(?:做|学|实践|参与|接触|试)|正在准备")
PAST_EVENT = re.compile(r"曾经|之前|当时|实际(?:上|做)|上线后|实测|我(?:们)?[^，。]{0,8}(?:实现了|部署了|采用了|负责过|做过|开发了)")
PERSONAL_FACT = re.compile(r"(?:我(?:们)?(?:曾经|曾|实际|当时|亲自|已经|主要|独立)?(?:负责|主导|实现|开发|采用|接入|设计|部署|写了|做过|完成)|实测|上线后)")
# Keep loose clauses together when a trailing qualification could retract
# the previous claim ("延迟降到300ms，我不确定").
CLAIM_BREAK = re.compile(r"[。！？!?；;\n]|(?:但是|但|不过|实际上)|[，,](?=(?:我(?:们)?|实际|当时)?(?:还|并|暂时)?(?:没(?:有)?(?:做|学|参与|用|测)|未(?:做|测|参与)))")
BASIC_QUESTIONS = {
    "architecture": (
        "从你熟悉的一个应用说起，用户点开详情页时，数据会经过哪些地方？",
        "如果保存订单时网络断开，你希望页面怎样告诉用户订单状态？",
        "如果两个人同时编辑同一条记录，你希望系统怎么处理？",
        "如果只能备份一种数据，你会优先保留什么？",
        "如果搜索功能暂时不可用，哪些功能还可以继续提供？",
    ),
    "technical": (
        "如果一个函数返回了意外的值，你会先检查哪一个输入？",
        "如果用户提交了空表单，你会在哪一步发现它？",
        "如果要验证一个排序函数，你会先给它哪组输入？",
        "如果同一个请求发了两遍，你希望程序怎样处理？",
        "如果要把一段代码交给同事，你会先解释哪一部分？",
        "如果程序只在某台机器上报错，你想先比较哪项信息？",
    ),
    "hr": ("如果同时收到两个任务，你会先和谁确认优先级？", "加入新团队时，你最想先了解什么？"),
}


def _hypothetical_question(question):
    return bool(HYPOTHETICAL.search(question) or re.search(r"你(?:会|希望|想先)", question)
                or any(question in choices for choices in BASIC_QUESTIONS.values()))


def contextual_followup(kind, answer, question, asked):
    """Return one safe, replayable question when a generic probe would assume experience."""
    parts = CLAIM_BREAK.split(answer)
    fact = next((c.strip(" ，,") for c in parts if PERSONAL_FACT.search(c)
                 and not (UNCONFIRMED.search(c) or HYPOTHETICAL.search(c))), "")
    if _hypothetical_question(question) and not PAST_EVENT.search(fact):
        fact = ""
    hypothetical = HYPOTHETICAL.search(answer)
    if fact and not (NO_PRACTICE.search(answer) or hypothetical or UNCONFIRMED.search(answer)):
        return None, None
    if fact:
        probe = f"你提到“{fact[:64]}”，这部分你最熟悉的一个细节是什么？"
        if probe not in asked:
            return "partial_experience", probe
    # A tentative proposal is still discussable even when the speaker doesn't
    # know implementation details. An explicit boundary alone calls for a pivot.
    elif not UNTRIED.search(answer) and (hypothetical or (_hypothetical_question(question) and not NO_PRACTICE.search(answer))):
        if kind == "architecture" and re.search(r"流量|并发", answer):
            proposed = "假设流量突然增加，你想先观察哪个现象来判断哪里开始吃紧？"
        else:
            proposed = "就这个设想来说，你会先检查哪个条件，来判断它是否可行？"
        if proposed not in asked:
            return "hypothetical", proposed
    elif not NO_PRACTICE.search(answer):
        return None, None
    choices = BASIC_QUESTIONS.get(kind, BASIC_QUESTIONS["technical"])
    return "change_topic", next((q for q in choices if q not in asked), "这个方向里，你最熟悉、愿意具体聊的是哪个问题？")


def _role_answers(messages, agent_id):
    """Older sessions may have no persisted round or reply ID."""
    question_owners = {}
    latest_question = {}
    for message in messages:
        if message.get("sender_type") == "agent" and message.get("message_type") in {"question", "follow_up"}:
            question_owners[message["id"]] = message
            latest_question = message
        if (message.get("sender_type") == "candidate"
                and message.get("message_type") in {None, "answer", "transcript"}
                and (message.get("content") or "").strip()):
            reply_id = message.get("reply_to_message_id")
            question = question_owners.get(reply_id, {}) if reply_id else latest_question
            owner = message.get("round_agent_id") or question.get("agent_id")
            if owner == agent_id:
                prompt = question.get("content") if question.get("agent_id") == owner else ""
                yield {**message, "question": prompt or ""}


def _evidence(answers, goals):
    evidence = {key: {"status": "unseen"} for key in goals}
    for answer in answers:
        for sentence in CLAIM_BREAK.split(answer["content"]):
            # A qualification either side of a comma can govern the whole claim.
            prospective = HYPOTHETICAL.search(sentence) or (
                _hypothetical_question(answer.get("question", "")) and not PAST_EVENT.search(sentence)
            )
            prospective = prospective or NO_PRACTICE.search(sentence)
            uncertain = prospective or UNCONFIRMED.search(sentence)
            # Reject the discarded implementation, but retain an explicit reason
            # for discarding it as evidence of a trade-off.
            tradeoff_uncertain = prospective or UNCONFIRMED.search(sentence.replace("没有选择", ""))
            for raw_clause in re.split(r"[，,]", sentence):
                clause = raw_clause.strip()
                for key in goals:
                    _, mention, observation, _ = DIMENSIONS[key]
                    if evidence[key]["status"] == "supported" or not re.search(mention, clause, re.I):
                        continue
                    match = re.search(observation, clause, re.I)
                    supported = bool(match) and not (tradeoff_uncertain if key == "tradeoff" else uncertain)
                    start = max(0, match.start() - 24) if supported else 0
                    evidence[key] = {"status": "supported" if supported else "mentioned",
                                     "answer_id": answer["id"], "quote": clause[start:start + 120]}
    return evidence


def _handoff(next_agent, evidence, interview):
    confirmed = [{"dimension": key, **item} for key, item in evidence.items() if item["status"] == "supported"]
    remaining = [key for key, item in evidence.items() if item["status"] != "supported"]
    kind = next_agent.get("agent_type")
    # Prefer an engineering detail for architecture and an individual action
    # for HR. Only quote the candidate, never fill in a missing project fact.
    priorities = ("solution", "metrics", "risk") if kind == "architecture" else ("collaboration", "responsibility", "reflection", "solution")
    quote = next((evidence[key]["quote"] for key in priorities if key in evidence and evidence[key]["status"] == "supported"),
                 confirmed[0]["quote"] if confirmed else "")
    if kind == "architecture":
        question = f"你刚才提到“{quote}”。如果规模扩大，最先需要重新设计哪一部分？" if quote else "选一个你熟悉的系统，如果使用规模扩大，你会优先检查哪处设计？"
    elif kind == "hr":
        question = f"你刚才提到“{quote}”。这项工作中有没有需要和他人达成共识的地方？" if quote else f"你在选择{interview.get('target_role') or '目标岗位'}相关机会时，最看重哪些因素？"
    else:
        question = "请选一段与目标岗位相关的经历，说说你亲自做了什么。"
    return {"confirmed": confirmed, "open_dimensions": remaining, "next_goal": next_agent.get("agent_role") or kind}, question


def decide_turn(*, interview, agents, active_agent, messages, answer):
    kind = active_agent.get("agent_type")
    kind = kind if kind in GOALS else "technical"
    history = [item for item in messages if item["id"] != answer["id"]]
    current = {**answer, "sender_type": "candidate"}
    if not current.get("round_agent_id") and not current.get("reply_to_message_id"):
        current["round_agent_id"] = active_agent["id"]
    answers = list(_role_answers([*history, current], active_agent["id"]))
    evidence = _evidence(answers, GOALS[kind])
    minimum, maximum = LIMITS[kind]
    count = len(answers)
    supported = sum(item["status"] == "supported" for item in evidence.values())
    decision = {"version": 1, "round_count": count, "evidence": evidence, "handoff": None,
                "next_agent_id": None, "closing": None}
    enough = kind != "hr" and count >= minimum and supported >= 4
    if not enough and count < maximum:
        asked = {m.get("content") for m in messages if m.get("sender_type") == "agent" and m.get("agent_id") == active_agent["id"]}
        # Clarify a mention first, then seek an uncovered goal. Skip questions
        # already used when another suitable prompt is available.
        ranked = sorted(GOALS[kind], key=lambda key: {"mentioned": 0, "unseen": 1, "supported": 2}[evidence[key]["status"]])
        question = next((DIMENSIONS[key][3] for key in ranked if DIMENSIONS[key][3] not in asked),
                        "还有哪些事实能补充说明你在这段经历中的判断？")
        mode, scoped_question = contextual_followup(kind, current["content"], answers[-1]["question"] if answers else "", asked)
        question = scoped_question or question
        return {**decision, "followup_mode": mode, "action": "ask_follow_up", "reason": "minimum_turns" if count < minimum else "needs_evidence", "question": question}

    next_agent = next((item for item in sorted(agents, key=lambda item: item["order_index"])
                       if item["order_index"] > active_agent["order_index"] and item["status"] != "completed"), None)
    reason = "evidence_sufficient" if enough else "turn_limit"
    closing = "本轮已经收集到足够的具体回答。" if enough else "本轮已达到预设回答次数，先聊到这里。"
    if not next_agent:
        return {**decision, "action": "finish_interview", "reason": reason, "closing": closing, "question": None}
    handoff, question = _handoff(next_agent, evidence, interview)
    return {**decision, "action": "switch_agent", "reason": reason, "closing": closing,
            "next_agent_id": next_agent["id"], "handoff": handoff, "question": question}
