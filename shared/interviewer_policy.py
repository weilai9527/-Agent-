"""Shared interview policy, validated selections and immutable session snapshots."""
from copy import deepcopy
import json

OPTIONS = {
    "style": {
        "友好引导": "语气耐心友好；回答困难时给出简短提示，引导候选人自己说明，不代答。",
        "专业严谨": "语气专业客观，要求事实和证据；简短反馈，不夸大肯定或否定。",
        "正常克制": "保持自然、克制的交流节奏，简短反馈后继续提问。",
        "犀利追问": "直接指出回答中的模糊处或矛盾，用具体问题追问证据与边界，保持尊重。",
        "压力面试": "通过有依据的质疑和时间内的取舍制造适度挑战，不贬低、不羞辱候选人。",
        "沉默压迫感": "表达克制，减少鼓励性铺垫；给候选人思考空间，不刻意长时间沉默。",
    },
    "focus": {
        "项目深挖": "优先围绕真实项目，核对个人职责、实现细节、决策依据与结果。",
        "系统设计": "优先考察需求拆解、模块边界、方案取舍、容量和稳定性。",
        "八股基础": "优先核对岗位基础概念和原理，并用小型实际场景验证理解。",
        "行为面试": "优先通过具体经历了解行动、协作、冲突处理和结果。",
        "压力面试": "优先提出约束、反例和突发变化，观察应对和取舍能力。",
        "沟通表达": "优先观察表达结构、关键信息传递和澄清问题的能力。",
    },
    "depth": {
        "点到为止": "同一主题通常追问一次，确认关键事实后换到下一个相关主题。",
        "适度深入": "同一主题通常追问两到三层，按背景、行动、结果逐步深入。",
        "连续深挖": "围绕同一主题逐层追问实现、取舍、证据和风险；没有新信息或候选人明确不会时停止深挖。",
    },
}
DEFAULT_POLICY = {
    "studentCanChoose": True,
    "allowed": {key: list(values) for key, values in OPTIONS.items()},
    "defaults": {"style": "专业严谨", "focus": "项目深挖", "depth": "适度深入"},
    "roles": {
        "technical": {"focus": "核心技术基础、项目实现和个人职责", "strategy": "先确认岗位技术栈，再结合候选人的真实项目追问实现细节和结果证据。"},
        "architecture": {"focus": "系统设计、方案取舍、性能和稳定性", "strategy": "从业务场景切入，逐步核对模块边界、数据流、容量及故障处理。"},
        "hr": {"focus": "职业动机、沟通协作和岗位匹配", "strategy": "用具体经历了解候选人的行动、沟通方式、职业选择与复盘。"},
    },
}


def ensure_interviewer_policy_schema(db, engine):
    text_type = "MEDIUMTEXT" if engine == "mysql" else "TEXT"
    suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci" if engine == "mysql" else ""
    db.execute(f"CREATE TABLE IF NOT EXISTS interviewer_policy (id VARCHAR(40) PRIMARY KEY, config {text_type} NOT NULL){suffix}")
    db.execute(f"CREATE TABLE IF NOT EXISTS interview_strategy_snapshots (interview_id CHAR(36) PRIMARY KEY, config {text_type} NOT NULL, FOREIGN KEY (interview_id) REFERENCES interview_sessions(id) ON DELETE CASCADE){suffix}")
    db.commit()


def validate_policy(value):
    if not isinstance(value, dict) or not isinstance(value.get("studentCanChoose"), bool):
        raise ValueError("请选择是否允许学生调整策略。")
    result = {"studentCanChoose": value["studentCanChoose"], "allowed": {}, "defaults": {}, "roles": {}}
    for key, options in OPTIONS.items():
        allowed = value.get("allowed", {}).get(key) if isinstance(value.get("allowed"), dict) else None
        default = value.get("defaults", {}).get(key) if isinstance(value.get("defaults"), dict) else None
        if not isinstance(allowed, list) or not allowed or any(not isinstance(item, str) or item not in options for item in allowed) or len(set(allowed)) != len(allowed):
            raise ValueError("每类策略至少保留一个有效选项，且不能重复。")
        if default not in allowed:
            raise ValueError("默认策略必须在学生可选范围内。")
        result["allowed"][key] = allowed
        result["defaults"][key] = default
    roles = value.get("roles")
    if not isinstance(roles, dict):
        raise ValueError("请填写各轮面试官的职责与提问策略。")
    for role in DEFAULT_POLICY["roles"]:
        result["roles"][role] = {}
        for field, limit in (("focus", 180), ("strategy", 240)):
            text = roles.get(role, {}).get(field) if isinstance(roles.get(role), dict) else None
            if not isinstance(text, str) or not text.strip() or len(text.strip()) > limit or "\0" in text:
                raise ValueError(f"面试官侧重点需为 1–180 字，提问策略需为 1–240 字。")
            result["roles"][role][field] = text.strip()
    return result


def load_policy(db):
    row = db.execute("SELECT config FROM interviewer_policy WHERE id = ?", ("default",)).fetchone()
    return validate_policy(json.loads(row["config"])) if row else deepcopy(DEFAULT_POLICY)


def save_policy(db, value):
    policy = validate_policy(value)
    # REPLACE is supported by both SQLite and MySQL and changes only this row.
    db.execute("REPLACE INTO interviewer_policy (id, config) VALUES (?, ?)", ("default", json.dumps(policy, ensure_ascii=False)))
    db.commit()
    return policy


def select_strategy(policy, selection=None):
    if selection is not None and (not isinstance(selection, dict) or set(selection) - set(OPTIONS)):
        raise ValueError("面试官策略格式不正确，请重新选择。")
    selection = selection or {}
    chosen = dict(policy["defaults"])
    for key in OPTIONS:
        value = selection.get(key, chosen[key])
        if not isinstance(value, str) or value not in policy["allowed"][key]:
            raise ValueError("可选策略已更新，请刷新页面后重新选择。")
        if not policy["studentCanChoose"] and value != chosen[key]:
            raise ValueError("本场面试由管理员统一设置策略，请刷新页面后重试。")
        chosen[key] = value
    return {"version": 1, "selection": chosen, "roles": deepcopy(policy["roles"])}


def load_snapshot(db, interview_id):
    row = db.execute("SELECT config FROM interview_strategy_snapshots WHERE interview_id = ?", (interview_id,)).fetchone()
    return json.loads(row["config"]) if row else None


def strategy_prompt(interview, agent):
    snapshot = interview.get("interviewer_strategy")
    if not snapshot:
        return "\n".join((f"面试官风格：{interview.get('interviewer_style') or '专业严谨'}", f"练习重点：{interview.get('focus_areas') or '项目经历'}", f"角色职责：{agent.get('agent_role') or ''}", f"提问策略：{agent.get('strategy') or ''}"))
    selected = snapshot["selection"]
    role = snapshot["roles"].get(agent.get("agent_type"), {})
    return "\n".join([
        "本场固定面试官策略（每次重连和换轮次都遵循）：",
        f"交流风格：{selected['style']}。{OPTIONS['style'][selected['style']]}",
        f"练习重点：{selected['focus']}。{OPTIONS['focus'][selected['focus']]}",
        f"追问深度：{selected['depth']}。{OPTIONS['depth'][selected['depth']]}",
        f"当前角色侧重点：{role.get('focus') or agent.get('agent_role') or '围绕目标岗位提问'}",
        f"当前角色提问策略：{role.get('strategy') or agent.get('strategy') or '结合真实回答逐步追问'}",
        "在当前角色职责范围内应用练习重点，不跨轮次；学生风格选择仅改变交流方式，不改变评分标准。每次只问一个问题，不替候选人回答。",
    ])
