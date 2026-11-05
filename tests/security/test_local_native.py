"""验证本机操作工具按进程隔离学校、签名能力、SQL、代码库与运行目录。"""

import json
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from deploy.local_native import PROCESSES, environment, initialize, state_path, trust_for
from shared.service_security import require_service, service_headers


def test_secrets_live_only_with_their_owner(tmp_path, monkeypatch):
    state = tmp_path / "native"
    initialize(state, "audit-college")
    manifest = json.loads((state / "instance.json").read_text())
    monkeypatch.setenv("PROVENANCE_SUBMIT_TOKEN", "不应继承")
    monkeypatch.setenv("EMERGENCY_SNAPSHOT", "不应继承")
    monkeypatch.setenv("SQLITE_PATH", "不应继承")
    cfg = {name: environment(name, state, manifest) for name in PROCESSES}
    assert all(
        "PROVENANCE_SUBMIT_TOKEN" not in env and "EMERGENCY_SNAPSHOT" not in env and "SQLITE_PATH" not in env
        for env in cfg.values()
    )
    for name, env in cfg.items():
        assert ("CREDENTIALS_SIGNING_KEYS_JSON" in env) == (name == "credentials")
    assert not any(k.endswith("_SQLITE_PATH") for k in cfg["admin-gateway"])
    assert not any(k.endswith("_SQLITE_PATH") for k in cfg["student-gateway"])
    assert cfg["credentials"]["SERVICE_SIGNING_KEY"] != cfg["credential-relay"]["SERVICE_SIGNING_KEY"]
    assert (
        cfg["credentials-verifier"]["CREDENTIALS_SQLITE_PATH"]
        == cfg["credentials"]["CREDENTIALS_SQLITE_PATH"]
    )
    assert "PRIVATE KEY" not in json.dumps(manifest)
    with pytest.raises(ValueError):
        initialize(state, "other-school")
    with pytest.raises(ValueError):
        state_path(Path.cwd() / "credential-test")
    with pytest.raises(ValueError):
        initialize(tmp_path / "platform", "platform")


def test_read_key_cannot_impersonate_the_chain_relay(tmp_path, monkeypatch):
    state = tmp_path / "native"
    initialize(state, "school")
    manifest = json.loads((state / "instance.json").read_text())
    app = FastAPI()
    for action in ("provenance.read", "provenance.submit"):

        def endpoint():
            return {"ok": True}

        app.add_api_route(
            "/" + action, endpoint, dependencies=[Depends(require_service("provenance", action))]
        )

    def request(name, scope, school="school"):
        env = environment(name, state, manifest)
        with monkeypatch.context() as p:
            for key, value in env.items():
                p.setenv(key, value)
            headers = service_headers(
                "provenance",
                actor_id="credentials-relay",
                actor_type="system",
                school_id=school,
                scopes=[scope],
            )
        return TestClient(app).get("/" + scope, headers=headers).status_code

    monkeypatch.setenv("SERVICE_ID", "provenance")
    monkeypatch.setenv("SERVICE_TRUST_POLICY", json.dumps(trust_for("provenance", manifest)))
    assert request("credentials", "provenance.read") == 200
    assert request("credentials", "provenance.submit") == 403
    assert request("credential-relay", "provenance.submit") == 200
    assert request("credential-relay", "provenance.submit", "other") == 403
