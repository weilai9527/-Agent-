"""签发事务提交后，由独立进程将待投递事件发送给存证服务。

用 `python -m services.credentials.relay` 启动。提交成功只表示存证服务已接收事件。
只有现场查询到与该事件匹配的最终确认回执，才能向验真者展示链上确认。
"""

import logging
import os
import re
import time

import httpx
from fastapi import HTTPException
from jwt.exceptions import PyJWTError

from shared.service_http import service_origin
from shared.service_security import service_headers


_ERRORS = (HTTPException, httpx.HTTPError, httpx.InvalidURL, KeyError, TypeError, ValueError, PyJWTError)
_NETWORK = re.compile(r"fixture|eip155:[1-9][0-9]{0,77}")
_HASH = re.compile(r"0x[0-9a-f]{64}")


def _actor_id(submit):
    service = os.environ.get("SERVICE_ID")
    if service == "credentials":
        return "credentials-relay"
    if service == "credentials-verifier" and not submit:
        return "credentials-verifier"
    raise ValueError("服务身份未获本次存证操作授权")


def _exchange(event, submit):
    event_id, digest = event["event_id"], event["digest"]
    # 请求路径只能包含服务生成的随机事件编号。
    if not re.fullmatch(r"[0-9a-f]{32}", event_id) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid local provenance event")
    url = service_origin("provenance") + "/internal/anchors"
    scope = "provenance.submit" if submit else "provenance.read"
    headers = service_headers("provenance", actor_id=_actor_id(submit), school_id=event["school_id"],
                              actor_type="system", scopes=[scope])
    options = {"json": {"event_id": event_id, "digest": digest}} if submit else {}
    response = httpx.request("POST" if submit else "GET", url if submit else f"{url}/{event_id}",
                             headers=headers, timeout=3.0, trust_env=False,
                             follow_redirects=False, **options)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or (body.get("event_id"), body.get("digest")) != (event_id, digest):
        raise ValueError("Unbound provenance receipt")
    status = body.get("status")
    if status not in ("pending", "submitted", "confirmed", "failed"):
        raise ValueError("Unknown provenance state")
    result = {"status": status}
    network = body.get("network")
    if network is not None:
        if not isinstance(network, str) or not _NETWORK.fullmatch(network):
            raise ValueError("Unknown provenance network")
        result.update(network=network, fixture=(network == "fixture"))
    if status == "confirmed":
        tx_hash, block = body.get("tx_hash"), body.get("block_number")
        if (not network or not isinstance(tx_hash, str) or not _HASH.fullmatch(tx_hash)
                or type(block) is not int or block < 0):
            raise ValueError("Incomplete finality receipt")
        result.update(tx_hash=tx_hash, block_number=block)
    return result


def anchor_status(event):
    """生成公开的存证状态，隐藏原始错误、事件编号和摘要。"""
    if not event:
        return {"status": "unconfirmed"}
    if event.get("delivered") == 0:
        return {"status": "pending"}
    try:
        return _exchange(event, submit=False)
    except _ERRORS:
        return {"status": "unconfirmed"}


def deliver_one(db, now=None):
    """领取一个到期事件并在事务外发送；没有待投递事件时返回 False。"""
    _actor_id(submit=True)
    now = int(time.time()) if now is None else now
    with db.transaction(write=True) as tx:
        lock = " FOR UPDATE" if db.engine == "mysql" else ""
        row = tx.one("""SELECT * FROM credential_outbox WHERE delivered=0 AND next_try<=?
                        ORDER BY next_try,event_id LIMIT 1""" + lock, (now,))
        if row is None:
            return False
        attempt = row["tries"] + 1
        # 先保存租约再发送。进程崩溃后，下一次投递沿用同一学校、事件编号和摘要。
        tx.execute("UPDATE credential_outbox SET tries=?,next_try=? WHERE event_id=?",
                   (attempt, now + 30, row["event_id"]))
    try:
        _exchange(row, submit=True)
        delivered, due = 1, 0
    except _ERRORS as exc:
        # 上游错误可能含敏感地址，只记录异常类别和内部事件编号。
        logging.warning("Provenance delivery %s failed (%s)", row["event_id"], type(exc).__name__)
        delivered, due = 0, now + min(300, 2 ** min(attempt, 9))
    with db.transaction(write=True) as tx:
        # 过期租约的延迟响应不能覆盖新一轮投递的结果。
        tx.execute("""UPDATE credential_outbox SET delivered=?, next_try=?
                      WHERE event_id=? AND tries=? AND delivered=0""",
                   (delivered, due, row["event_id"], attempt))
    return True


def main():
    from .storage import database, initialize

    _actor_id(submit=True)
    if os.environ.get("CREDENTIALS_SIGNING_KEYS_JSON") or os.environ.get("PROVENANCE_SUBMIT_TOKEN"):
        raise ValueError("投递进程不能配置学校签发私钥或链账户令牌")
    db = database()
    initialize(db)
    while True:
        if not deliver_one(db):
            time.sleep(1)


if __name__ == "__main__":
    main()
