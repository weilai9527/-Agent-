"""面试、面试官及消息写入前的字段校验。"""
from __future__ import annotations

from services.interview.queries import error
from typing import Any


INTERVIEW_STATUSES = {"draft", "running", "completed"}


AGENT_STATUSES = {"pending", "active", "completed"}


MESSAGE_SENDER_TYPES = {"agent", "candidate", "system"}


MESSAGE_TYPES = {"question", "answer", "follow_up", "system", "transcript"}


MESSAGE_SOURCES = {"text", "aliyun_rtc"}


INTERVIEW_TEXT_FIELDS = [
    ("target_role", "目标岗位", 80),
    ("experience_level", "经验等级", 40),
    ("interview_type", "面试类型", 60),
    ("company_context", "公司场景", 120),
    ("focus_areas", "重点方向", 500),
    ("resume_context", "简历与项目简介", 12000),
    ("difficulty", "难度", 40),
    ("interviewer_style", "面试官风格", 60),
]


AGENT_TEXT_FIELDS = [
    ("agent_name", "Agent 名称", 80),
    ("agent_type", "Agent 类型", 40),
    ("agent_role", "Agent 角色", 500),
    ("strategy", "面试策略", 1000),
]


def read_text_field(body: dict, field: str, label: str, max_length: int, required: bool = False) -> tuple[Any, str | None]:
    value = str(body.get(field) or "").strip()
    if required and not value:
        return None, f"{label}不能为空。"
    if not value:
        return None, None
    if len(value) > max_length:
        return None, f"{label}不能超过 {max_length} 个字符。"
    return value, None


def parse_interview_input(body: dict, partial: bool = False) -> dict:
    interview: dict[str, Any] = {}
    for field, label, max_length in INTERVIEW_TEXT_FIELDS:
        if partial and field not in body:
            continue
        value, message = read_text_field(body, field, label, max_length, field == "target_role")
        if message:
            raise error(400, message)
        interview[field] = value
    if partial and not interview:
        raise error(400, "请至少提供一个要更新的字段。")
    return interview


def parse_order_index(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 99 else None


def parse_agent_input(body: dict, partial: bool = False) -> dict:
    agent: dict[str, Any] = {}
    for field, label, max_length in AGENT_TEXT_FIELDS:
        if partial and field not in body:
            continue
        value, message = read_text_field(body, field, label, max_length, field != "strategy")
        if message:
            raise error(400, message)
        agent[field] = value

    if "order_index" in body:
        order_index = parse_order_index(body.get("order_index"))
        if order_index is None:
            raise error(400, "Agent 顺序必须是 0 到 99 之间的整数。")
        agent["order_index"] = order_index

    if "status" in body:
        status = str(body.get("status") or "").strip()
        if status not in AGENT_STATUSES:
            raise error(400, "Agent 状态不正确。")
        agent["status"] = status

    if partial and not agent:
        raise error(400, "请至少提供一个要更新的字段。")
    return agent


def parse_message_input(body: dict) -> dict:
    sender_type = str(body.get("sender_type") or "").strip()
    message_type = str(body.get("message_type") or "").strip()
    content, message = read_text_field(body, "content", "消息内容", 12000, True)
    if sender_type not in MESSAGE_SENDER_TYPES:
        raise error(400, "消息发送方类型不正确。")
    if message_type not in MESSAGE_TYPES:
        raise error(400, "消息类型不正确。")
    if message:
        raise error(400, message)
    transcript_text, message = read_text_field(body, "transcript_text", "语音转写结果", 12000)
    if message:
        raise error(400, message)
    source = str(body.get("source") or "text").strip().lower()
    if source not in MESSAGE_SOURCES:
        raise error(400, "消息来源不正确。")
    source_ref, message = read_text_field(body, "source_ref", "消息来源标识", 128)
    if message:
        raise error(400, message)
    if source == "aliyun_rtc" and not source_ref:
        raise error(400, "RTC 字幕必须提供稳定的 turn_id。")

    agent_id = str(body.get("agent_id") or "").strip() or None
    if sender_type == "agent" and not agent_id:
        raise error(400, "Agent 消息必须关联 agent_id。")
    if sender_type != "agent" and agent_id:
        raise error(400, "只有 Agent 消息可以关联 agent_id。")
    if sender_type == "candidate" and message_type not in {"answer", "transcript"}:
        raise error(400, "候选人消息只能是 answer 或 transcript。")
    if sender_type == "system" and message_type != "system":
        raise error(400, "系统消息类型必须是 system。")
    if sender_type == "agent" and message_type not in {"question", "follow_up", "system"}:
        raise error(400, "Agent 消息只能是 question、follow_up 或 system。")

    return {
        "agent_id": agent_id,
        "sender_type": sender_type,
        "message_type": message_type,
        "content": content,
        "transcript_text": transcript_text,
        "source": source,
        "source_ref": source_ref,
    }
