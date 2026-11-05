"""仅刷新目录负责的字段，私有简历证据留在网关内。"""
import hashlib

from fastapi import HTTPException

from shared.career_catalog import CATALOG_MATCH_FIELDS
from shared.service_http import request_json


async def enrich_response(result, actor, record=False):
    row = result.get("resume_analysis")
    analysis = row.get("analysis") if row else None
    directions = analysis.get("recommended_directions") if isinstance(analysis, dict) else None
    if not directions:
        return result
    if not isinstance(directions, list) or len(directions) > 20 or any(
        not isinstance(d, dict) or not isinstance(d.get("name"), str)
        or not 0 < len(d["name"].strip()) <= 160 for d in directions
    ):
        raise HTTPException(502, "简历分析方向数据无效。")
    names = [d["name"].strip() for d in directions]
    body = {"names": names, "record": record}
    # 响应超时后重试仍使用同一事件编号，目录服务按学校和学生对事件去重。
    if record:
        digest = row.get("source_hash")
        if not isinstance(digest, str) or not digest:
            raise HTTPException(502, "简历分析缺少来源标识。")
        body["event_id"] = hashlib.sha256(("catalog-directions-v1\n" + digest).encode()).hexdigest()
    path = "/v1/catalog/suggestions" if record else "/v1/catalog/directions"
    scope = "catalog.suggest" if record else "catalog.enrich"
    response = await request_json("career", "POST", path, actor=actor, scope=scope, body=body)
    matches = response.get("directions") if isinstance(response, dict) else None
    if not isinstance(matches, list) or len(matches) != len(names) or any(
        not isinstance(match, dict) or match.get("name") != name for match, name in zip(matches, names)
    ):
        raise HTTPException(502, "职业目录返回的方向无效。")
    fields = CATALOG_MATCH_FIELDS | {"suggestion_id", "suggestion_status"}
    merged = [
        {**{k: v for k, v in original.items() if k not in fields},
         **{k: v for k, v in match.items() if k in fields}}
        for original, match in zip(directions, matches)
    ]
    return {**result, "resume_analysis": {**row, "analysis": {**analysis, "recommended_directions": merged}}}
