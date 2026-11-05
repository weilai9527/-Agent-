"""使用学校公钥验证持有人下载的 teaching-credential/v1 签名文件。

运行 python -m services.credentials.verify_file proof.json --issuer SCHOOL。
校方通过独立可信渠道提供 CREDENTIALS_PUBLIC_KEYS_JSON，文件持有人不能指定公钥。
加 --status 可向部署指定的 CREDENTIALS_PUBLIC_SERVICE_URL 查询实时效力。
离线成功仅证明签名 JSON 的内容。二维码可以查询该序号的状态，不能鉴定展示的 PDF 正文。

退出码 0 表示请求的检查全部通过，1 表示文件无效或证书已撤销，
2 表示文件无法读取、信任配置不可用或无法确定在线状态。
"""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import HTTPException

from shared.service_http import service_origin
from .signing import SigningConfigurationError, verify_payload


MAX_BYTES = 32_768
SERIAL = re.compile(r"[0-9a-f]{32}")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON member")
        obj[key] = value
    return obj


def parse_json(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("File exceeds credential size limit")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def _valid_claims(claims, issuer, serial):
    fields = {"school_id", "serial", "issued_at", "generation", "title", "commitment"}
    if not isinstance(claims, dict) or claims.keys() != fields:
        return False
    if (claims["school_id"] != issuer or claims["title"] != "模拟面试训练完成证明"
            or not isinstance(claims["serial"], str) or not SERIAL.fullmatch(claims["serial"])
            or (serial is not None and claims["serial"] != serial)
            or not isinstance(claims["commitment"], str) or not re.fullmatch(r"[0-9a-f]{64}", claims["commitment"])
            or type(claims["generation"]) is not int or claims["generation"] < 1):
        return False
    try:
        return datetime.fromisoformat(claims["issued_at"]).utcoffset() is not None
    except (TypeError, ValueError, OverflowError):
        return False


def current_status(claims):
    """仅向部署配置的可信源站查询证书序号，签名文件和持有人资料不随请求上传。"""
    try:
        url = service_origin("credentials_public") + "/verify/" + claims["serial"]
        with httpx.Client(timeout=4, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url, headers={"Accept": "application/json", "Accept-Encoding": "identity",
                                                    "Cache-Control": "no-cache"}) as response:
                if (response.status_code != 200
                        or response.headers.get("content-type", "").split(";")[0].strip() != "application/json"
                        or response.headers.get("content-encoding", "identity") != "identity"):
                    return "unknown"
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=4096):
                    if len(body) + len(chunk) > MAX_BYTES:
                        return "unknown"
                    body.extend(chunk)
        state = parse_json(body)
        if (not isinstance(state, dict) or state.get("issuer") != claims["school_id"]
                or state.get("title") != claims["title"] or state.get("issued_at") != claims["issued_at"]):
            return "unknown"
        if state.get("status") == "valid" and state.get("valid") is True:
            return "valid"
        if state.get("status") == "revoked" and state.get("valid") is False:
            return "revoked"
    except (HTTPException, httpx.HTTPError, ValueError, RecursionError):
        pass
    return "unknown"


def verify_document(raw, issuer, *, serial=None, check_status=False):
    invalid = {"signature": "invalid", "status": "not_checked"}
    try:
        proof = parse_json(raw)
    except (ValueError, RecursionError):
        return invalid
    if (not isinstance(proof, dict) or proof.keys() != {"format", "payload", "kid", "signature"}
            or proof["format"] != "teaching-credential/v1" or not isinstance(proof["kid"], str)
            or not _valid_claims(proof["payload"], issuer, serial)):
        return invalid
    try:
        if not verify_payload(issuer, proof["payload"], proof["kid"], proof["signature"]):
            return invalid
    except SigningConfigurationError:
        return {"signature": "unknown", "status": "not_checked"}
    claims = proof["payload"]
    return {"signature": "verified", "issuer": claims["school_id"], "serial": claims["serial"],
            "status": current_status(claims) if check_status else "not_checked"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--issuer", required=True, help="通过独立渠道取得的学校编号")
    parser.add_argument("--serial", help="与出示的证书比对的预期序号（可选）")
    parser.add_argument("--status", action="store_true", help="从可信验真源站查询当前撤销状态")
    args = parser.parse_args()
    try:
        with args.file.open("rb") as stream:
            result = verify_document(stream.read(MAX_BYTES + 1), args.issuer, serial=args.serial, check_status=args.status)
    except OSError:
        parser.exit(2, "无法读取证书文件\n")
    print(json.dumps(result, ensure_ascii=False))
    if result["signature"] == "invalid" or result["status"] == "revoked":
        return 1
    if result["signature"] != "verified" or (args.status and result["status"] != "valid"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
