"""用合成验真结果测试公开页面，覆盖隐私响应头、披露字段和错误页面。"""
import base64
import hashlib
import re
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.credentials.public import create_public_app
from services.credentials.signing import SigningConfigurationError


SERIAL = "3" * 32
URL = "/verify/" + SERIAL
RESULT = {"valid": True, "status": "valid", "title": "模拟面试训练完成证明",
          "issuer": "fixture school", "issued_at": "2026-01-02T03:04:05+00:00",
          "anchor": {"status": "pending"}}


def assert_headers(response):
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "noindex" in response.headers["X-Robots-Tag"]
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "Accept" in response.headers["Vary"]


@pytest.mark.parametrize("accept", ["*/*", "application/json", "text/html;q=0",
                                    "text/html;q=0.1, application/json;q=0.9"])
def test_json_is_default_and_respects_quality(accept):
    lookup = Mock(return_value=RESULT)
    with TestClient(create_public_app(lookup)) as client:
        response = client.get(URL, headers={"Accept": accept})
    lookup.assert_called_once_with(SERIAL)
    assert_headers(response)
    assert response.json() == RESULT


def test_html_escapes_claims_and_labels_fixture():
    result = dict(RESULT, issuer='<img src="/private" onerror="alert(1)">', anchor={
        "status": "confirmed", "fixture": True, "network": "fixture",
        "block_number": 1, "tx_hash": "0x" + "f" * 64,
    })
    with TestClient(create_public_app(lambda serial: result)) as client:
        response = client.get(URL, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    page = response.text
    assert_headers(response)
    assert response.headers["Content-Type"].startswith("text/html")
    for text in ("模拟面试训练完成证明", "本地测试链（fixture）", "已确认", "当前有效", "2026-01-02",
                 "&lt;img"):
        assert text in page
    assert "<img" not in page and SERIAL not in page
    stylesheet = re.search(r"<style>(.*?)</style>", page, flags=re.S)[1]
    token = base64.b64encode(hashlib.sha256(stylesheet.encode()).digest()).decode()
    assert f"'sha256-{token}'" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize(("result", "expected", "hidden"), [
    (dict(RESULT, valid=False, status="revoked"), "已撤销", "当前有效"),
    (dict(RESULT, valid=False, status="invalid_signature"), "签名验证失败", "fixture school"),
    (dict(RESULT, anchor={"status": "submitted"}), "等待确认", "已确认"),
    (dict(RESULT, anchor={"status": "unconfirmed"}), "尚未确认", "已确认"),
    (dict(RESULT, anchor={"status": "failed"}), "存证失败", "已确认"),
])
def test_distinct_statuses(result, expected, hidden):
    with TestClient(create_public_app(lambda serial: result)) as client:
        page = client.get(URL, headers={"Accept": "text/html"}).text
    assert expected in page and hidden not in page


@pytest.mark.parametrize(("error", "code"), [
    (HTTPException(404, "private tenant id"), 404),
    (SigningConfigurationError("private key info"), 503),
    (RuntimeError("private sql info"), 503),
])
def test_html_failures_are_sanitized_and_uncacheable(error, code):
    with TestClient(create_public_app(Mock(side_effect=error)), raise_server_exceptions=False) as client:
        response = client.get(URL, headers={"Accept": "text/html"})
    assert response.status_code == code
    assert_headers(response)
    assert "private" not in response.text


def test_only_read_route_exists_and_startup_needs_no_database():
    lookup = Mock(side_effect=AssertionError("No DB call expected"))
    app = create_public_app(lookup)
    assert [(r.path, r.methods) for r in app.routes] == [("/verify/{serial}", {"GET"})]
    with TestClient(app) as client:
        for path in ("/", "/docs", "/openapi.json", "/applications", URL + "/"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert_headers(response)
        assert client.post(URL).status_code == 405
    lookup.assert_not_called()


def test_json_disclosure_excludes_private_fields_at_both_levels():
    result = dict(RESULT, student_id="private-student", anchor=dict(RESULT["anchor"], digest="private-digest"))
    with TestClient(create_public_app(lambda serial: result)) as client:
        assert client.get(URL).json() == RESULT
        result.update(valid=False, status="invalid_signature")
        assert client.get(URL).json() == {"status": "invalid_signature", "valid": False}
