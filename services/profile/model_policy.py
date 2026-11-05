"""按部署端授予的学校和任务选择单一模型。外部服务仅接收受限词表中的证据。"""
import asyncio
import hashlib
import json
import math
import os
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field, replace

import httpx
from fastapi import HTTPException

from shared import text_provider as models
from . import analysis as resume_analysis
from shared.provider_settings import PROVIDERS, approved_endpoint
from shared.recruitment import extract_skills
from .privacy import external_enabled


class ModelUnavailable(Exception):
    """模型暂时不可用时，调用方可使用本地规则的结果。"""


# 同步调用在独立的有界线程池内执行。超时返回后仍占用工作槽，直至网络请求真正结束。
_CAPACITY = 4
_SLOTS = threading.BoundedSemaphore(_CAPACITY)
_POOL = ThreadPoolExecutor(max_workers=_CAPACITY, thread_name_prefix="private-model")
_TASKS = {"profile": ("PROFILE_MODEL_BY_SCHOOL", "RESUME_ANALYSIS_PROVIDER_ORDER", 1400),
          "career": ("CAREER_MODEL_BY_SCHOOL", "JOB_MATCH_PROVIDER_ORDER", 1200)}


async def _request(provider, url, headers, payload):
    headers["Accept-Encoding"] = "identity"
    ca = os.environ.get("PRIVATE_MODEL_CA_FILE")
    options = {"verify": ssl.create_default_context(cafile=ca)} if ca else {}
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=provider.timeout, **options) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            if response.status_code != 200:
                return httpx.Response(response.status_code, request=response.request)
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ModelUnavailable()
            data = bytearray()
            async for block in response.aiter_bytes():
                if len(data) + len(block) > 128 * 1024:
                    raise ModelUnavailable()
                data.extend(block)
    return httpx.Response(200, request=response.request, content=bytes(data))


def _bounded_post(provider, url, headers, payload):
    return asyncio.run(asyncio.wait_for(_request(provider, url, headers, payload), provider.timeout))


@dataclass(frozen=True)
class ModelPlan:
    provider: str
    model: str
    cache_key: str
    _client: models.FollowupProvider | None = field(default=None, repr=False)

    def generate(self, messages):
        if self._client is None or not _SLOTS.acquire(blocking=False):
            raise ModelUnavailable()
        try:
            work = _POOL.submit(copy_context().run, models.call_provider_json, self._client, messages,
                                transport=_bounded_post)
        except BaseException:
            _SLOTS.release()
            raise
        work.add_done_callback(lambda _: _SLOTS.release())
        try:
            return work.result(timeout=self._client.timeout + 0.25)
        except (TimeoutError, httpx.HTTPError, OSError, ValueError, RecursionError):
            # 供应商错误可能包含凭据或原始响应，只向调用方返回统一的失败状态。
            raise ModelUnavailable() from None


def _plan(name, task):
    if name == "local":
        return ModelPlan("local", "rules-v1", f"{task}:local:v1")
    try:
        cfg = models._provider_config(name)
    except Exception:
        # 生成请求无法取得受信配置时拒绝出站。向上层返回固定错误，避免暴露控制服务地址或凭据。
        raise HTTPException(503, "模型配置服务不可用。") from None
    try:
        if not cfg or cfg.name != name or not isinstance(cfg.model, str) or not cfg.model.strip():
            raise ValueError()
        approved_endpoint(cfg.name, cfg.base_url)
        timeout = float(os.environ.get("PRIVATE_MODEL_TIMEOUT_SECONDS", "5"))
        if not math.isfinite(timeout) or not 0 < timeout <= 8:
            raise ValueError()
        if not math.isfinite(cfg.temperature) or not 0 <= cfg.temperature <= 2:
            raise ValueError()
        prefix = "RESUME_ANALYSIS" if task == "profile" else "JOB_MATCH"
        task_timeout = float(os.environ.get(f"{prefix}_TIMEOUT", str(timeout)))
        max_tokens = int(os.environ.get(f"{prefix}_MAX_TOKENS", str(_TASKS[task][2])))
        if not math.isfinite(task_timeout) or task_timeout <= 0 or max_tokens < 1:
            raise ValueError()
        cfg = replace(cfg, timeout=min(timeout, task_timeout), retries=0, max_tokens=min(max_tokens, _TASKS[task][2]))
    except (ValueError, TypeError, OSError, RuntimeError):
        raise HTTPException(503, "授权模型的配置不完整或接入地址未获许可。") from None
    # 指纹只记录影响推理的非秘密配置。轮换密钥沿用缓存，切换模型或接入地址会使缓存失效。
    fingerprint = json.dumps([task, "private-evidence-v1", cfg.name, cfg.base_url, cfg.model, cfg.temperature, cfg.max_tokens])
    return ModelPlan(cfg.name, cfg.model, hashlib.sha256(fingerprint.encode()).hexdigest(), cfg)


def select_model(school_id, task):
    key = _TASKS[task][0]
    raw = os.environ.get(key)
    if raw is None:
        return _plan("local", task)
    try:
        grants = json.loads(raw)
        if not isinstance(grants, dict) or any(
                not school or "*" in school or not isinstance(value, str) or value not in PROVIDERS | {"local"}
                for school, value in grants.items()):
            raise ValueError()
    except (ValueError, RecursionError):
        raise HTTPException(503, f"{key} 的学校授权配置无效。") from None
    return _plan(grants.get(school_id, "local"), task)


def legacy_model(task):
    school = os.environ.get("LEGACY_SCHOOL_ID")
    grant, order, _ = _TASKS[task]
    if grant in os.environ:
        return select_model(school, task)
    if not external_enabled(order):
        return _plan("local", task)
    if not school or "*" in school or any(c.isspace() or ord(c) < 32 for c in school):
        raise HTTPException(503, "须先将旧库绑定到一所学校才能启用外部简历处理。")
    return _plan(os.environ[order].strip().lower(), task)


def _profile_messages(profile):
    # 仅从受控词表提取证据；删除电话、邮箱等格式化字段不足以消除自由文本中的姓名和学号。
    source = resume_analysis.resume_analysis_source_text(profile)[:16000]
    directions = resume_analysis.build_local_direction_recommendations({}, source)
    evidence = {"skills": extract_skills(source), "directions": [
        {"name": item["name"], "evidence": item["evidence"]} for item in directions if item["evidence"]
    ]}
    if not evidence["skills"] and not evidence["directions"]:
        return None

    # 区分技能清单和项目中的活动证据。技能与动词都取自固定词表。
    actions = ("实现", "开发", "部署", "测试", "监控", "优化", "维护", "设计", "分析", "验证")
    projects = []
    for line in source.splitlines()[:128]:
        observed = [action for action in actions if action in line]
        if not observed:
            continue
        skills = extract_skills(line)
        if skills:
            projects.append({"skills": skills, "activities": observed})
        if len(projects) == 5:
            break
    evidence["project_evidence"] = projects
    return [
        {"role": "system", "content": "你是中文技术面试简历分析助手。仅分析这些技能和方向证据，"
         "输出含 candidate_summary, core_skills, projects, risk_points, recommended_directions 的 JSON 对象。"
         "只陈述证据支持的结论。对 project_evidence 中的每组证据按顺序给出核实职责和结果的"
         "追问，放在 projects 的 role、highlights、possible_questions 字段，不推测项目名称或成效。"
         "没有项目证据时 projects 使用空数组。"},
        {"role": "user", "content": "请按适配程度给出就业方向，每项包含 name、score(1-100)、reasons、gaps、evidence。"
         "证据有限时指出需要核实的内容。\n" + json.dumps(evidence, ensure_ascii=False)},
    ]


def analyze_profile(plan, profile):
    if plan.provider != "local":
        messages = _profile_messages(profile)
        if messages:
            try:
                reply = plan.generate(messages)
                if isinstance(reply, dict) and isinstance(reply.get("candidate_summary"), (str, dict)) and reply["candidate_summary"]:
                    analysis = resume_analysis._normalize_resume_analysis(reply)
                    if analysis["recommended_directions"]:
                        if not analysis["projects"]:
                            analysis["projects"] = resume_analysis.build_local_resume_analysis(profile)["projects"]
                        return {"analysis": analysis, "provider": plan.provider, "model": plan.model, "fallback": False}
            except (ModelUnavailable, ValueError, OverflowError, RecursionError):
                pass
    return {"analysis": resume_analysis.build_local_resume_analysis(profile), "provider": "local", "model": "rules-v1",
            "fallback": plan.provider != "local"}
