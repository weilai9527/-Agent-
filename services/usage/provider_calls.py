"""为持久评分和报告任务的每一次 HTTP 尝试接入计量。

日志保存任务归属、派发凭据、结果和结算状态。若结果已保存，可直接重放。
计量接口接收请求摘要及供应商元数据，凭据和提示正文留在发送端。
"""
import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx


class PendingProviderCall(RuntimeError):
    """暂停重试及切换供应商，等待日志核对。"""


class ProviderAttemptFailed(RuntimeError):
    """可安全持久化的单次派发结果类别。"""

    def __init__(self, outcome, status=None):
        super().__init__(f"Provider request {outcome}" + (f" (HTTP {status})" if status is not None else ""))
        self.outcome = outcome
        self.status = status

    @property
    def retryable(self):
        return self.outcome == "unsent" or (self.outcome == "rejected" and self.status == 429)


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    model: str
    attempt: int
    request_hash: str
    timeout: float


_wrapper = ContextVar("provider_call_wrapper", default=None)
_request_id = ContextVar("model_request_id", default=None)


@contextmanager
def model_request_id(slot):
    """仅在发送该请求期间向传输层提供日志中的关联编号。"""
    if not isinstance(slot, str) or not re.fullmatch(r"[a-f0-9]{64}", slot):
        raise PendingProviderCall("Invalid model request identifier")
    token = _request_id.set(slot)
    try:
        yield
    finally:
        _request_id.reset(token)


def current_model_request_id():
    return _request_id.get() if _wrapper.get() is not None else None


@contextmanager
def provider_call_context(wrapper):
    token = _wrapper.set(wrapper)
    try:
        yield
    finally:
        _wrapper.reset(token)


# 收到明确的生成前拒绝才可按零结算；代理 5xx、408、冲突或重定向都不足以证明未执行。
_REJECTED = {400, 401, 402, 403, 404, 405, 406, 407, 411, 413, 414, 415, 422, 429, 431}


def provider_attempt(provider, url, payload, attempt, post, parse):
    wrapper = _wrapper.get()
    if wrapper is None:
        return parse(post())

    digest = hashlib.sha256(json.dumps([url, payload], sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    meta = ProviderAttempt(provider.name, provider.model, attempt, digest, provider.timeout)
    dispatched = False

    def send():
        nonlocal dispatched
        if dispatched:
            raise PendingProviderCall("Duplicate provider dispatch")
        dispatched = True
        try:
            response = post()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout,
                httpx.UnsupportedProtocol, httpx.InvalidURL):
            raise ProviderAttemptFailed("unsent") from None
        except Exception:
            # 部分写入、丢失回包和未预期的客户端错误都可能发生在供应商已经开始处理之后。
            raise ProviderAttemptFailed("unknown") from None

        status = response.status_code
        if not 200 <= status < 300:
            raise ProviderAttemptFailed("rejected" if status in _REJECTED else "unknown", status)
        try:
            return parse(response)
        except (ValueError, TypeError, IndexError, KeyError):
            # 2xx 表示供应商已接受请求，即使返回内容无法作为模型结果使用。
            raise ProviderAttemptFailed("invalid", status) from None

    try:
        return wrapper(meta, send)
    except ProviderAttemptFailed as exc:
        if exc.outcome in {"unsent", "rejected", "invalid"}:
            raise
        raise PendingProviderCall("Provider dispatch requires reconciliation") from None
    except RuntimeError:
        # 日志要求暂缓的异常继承 RuntimeError，会直接穿过 HTTP 重试和供应商切换逻辑。
        raise
    except Exception:
        # 账本等外围环节的异常应进入待核对状态，避免把它当作模型响应无效而再次付费请求。
        raise PendingProviderCall("Provider journal requires reconciliation") from None
