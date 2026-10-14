"""Fetch the operator-configured JSON feed; never accept a URL from a browser."""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from shared.recruitment import TEXT_LIMITS, upsert_job_posting_by_source

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 2000
TIMEOUT = 15


class JobSyncError(ValueError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_job_feed() -> list:
    endpoint = os.environ.get("JOB_POSTING_SYNC_ENDPOINT", "").strip()
    if not endpoint:
        raise JobSyncError("尚未配置招聘数据源，请联系系统维护人员配置后再同步。")
    try:
        parsed = urlsplit(endpoint)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment
        if not valid or parsed.port == 0:
            raise ValueError()
    except ValueError:
        raise JobSyncError("招聘数据源地址无效，需配置不含账号密码的 HTTP 或 HTTPS 地址。") from None
    token = os.environ.get("JOB_POSTING_SYNC_TOKEN", "").strip()
    if token and (parsed.scheme != "https" or "\n" in token or "\r" in token):
        raise JobSyncError("带认证令牌的数据源必须使用 HTTPS，并配置有效令牌。")
    headers = {"Accept": "application/json", "User-Agent": "InterviewAdmin-JobSync/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.monotonic()
    try:
        with build_opener(NoRedirects()).open(Request(endpoint, headers=headers), timeout=TIMEOUT) as response:
            chunks = []
            size = 0
            while True:
                chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                size += len(chunk)
                if size > MAX_BYTES:
                    raise JobSyncError("数据源响应超过 5 MB，请缩小单次同步范围。")
                if time.monotonic() - started > TIMEOUT:
                    raise JobSyncError("数据源响应超时，请稍后重试。")
                if not chunk:
                    break
                chunks.append(chunk)
    except JobSyncError:
        raise
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise JobSyncError(f"数据源返回 HTTP {status}，请检查地址和认证配置；不支持跳转地址。") from None
    except (URLError, OSError, ValueError):
        raise JobSyncError("无法读取招聘数据源，请检查网络、地址和认证配置。") from None
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise JobSyncError("数据源未返回有效的 UTF-8 JSON。") from None
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise JobSyncError('数据源格式不正确，需返回岗位数组或 {"items": [...]}。')
    if len(rows) > MAX_ROWS:
        raise JobSyncError(f"单次同步最多 {MAX_ROWS} 条岗位，请缩小数据源返回范围。")
    return rows


def import_job_feed(db, rows: list, *, created_by: str) -> dict:
    source_name = os.environ.get("JOB_POSTING_SYNC_SOURCE", "default").strip() or "default"
    if len(source_name) > 80:
        raise JobSyncError("数据源标识不能超过 80 个字符。")
    result = {"total": len(rows), "created": 0, "updated": 0, "skipped": 0, "errors": []}
    try:
        for index, row in enumerate(rows, 1):
            try:
                if not isinstance(row, dict):
                    raise ValueError("记录必须为对象。")
                external_id = row.get("source_ref", row.get("id"))
                if isinstance(external_id, bool) or not isinstance(external_id, (str, int)) or not str(external_id).strip():
                    raise ValueError("缺少有效的 id 或 source_ref 外部编号。")
                source_ref = f"{source_name}:{str(external_id).strip()}"
                if len(source_ref) > 255:
                    raise ValueError("数据源标识与外部编号合计不能超过 255 个字符。")
                if not isinstance(row.get("title"), str) or not row["title"].strip():
                    raise ValueError("缺少岗位名称 title。")
                payload = {key: value for key, value in row.items() if key in TEXT_LIMITS or key in {"headcount", "published", "status", "sort_order"}}
                # Local catalog IDs must not be assigned by an external feed.
                payload.pop("catalog_job_role_id", None)
                for key, value in payload.items():
                    if key in {"skills", "tags"} and isinstance(value, list) and all(isinstance(item, str) for item in value):
                        payload[key] = "、".join(value)
                    elif isinstance(value, (dict, list)):
                        raise ValueError(f"字段 {key} 的格式不正确。")
                    if key in TEXT_LIMITS and len(str(payload[key] or "")) > TEXT_LIMITS[key]:
                        raise ValueError(f"字段 {key} 超过长度限制。")
                if "status" in payload and payload["status"] not in {"active", "disabled"}:
                    raise ValueError("status 只能为 active 或 disabled。")
                for key in ("headcount", "sort_order"):
                    if key in payload and (isinstance(payload[key], bool) or not str(payload[key]).isdigit() or not 0 <= int(payload[key]) <= 100000):
                        raise ValueError(f"字段 {key} 必须为 0 到 100000 的整数。")
                if "published" in payload and str(payload["published"]).lower() not in {"true", "false", "0", "1"}:
                    raise ValueError("published 必须为布尔值或 0 / 1。")
                _, action = upsert_job_posting_by_source(db, payload, source="sync", source_ref=source_ref, created_by=created_by)
                result[action] += 1
            except ValueError as exc:
                result["skipped"] += 1
                if len(result["errors"]) < 20:
                    result["errors"].append(f"第 {index} 条：{exc}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result
