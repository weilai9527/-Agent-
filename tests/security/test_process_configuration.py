import pytest

from deploy.run_service import check_config


@pytest.mark.parametrize("name,actor,key", [
    ("credentials-verifier", "credentials-verifier", "CREDENTIALS_SIGNING_KEYS_JSON"),
    ("credential-relay", "credentials", "CREDENTIALS_SIGNING_KEYS_JSON"),
    ("provenance", "provenance", "PROVENANCE_SUBMIT_TOKEN"),
    ("credentials", "credentials", "PROVENANCE_SUBMIT_TOKEN"),
])
def test_launcher_refuses_overprivileged_process(name, actor, key):
    with pytest.raises(ValueError) as denied:
        check_config(name, actor, {"SERVICE_ID": actor, key: "private-value"})
    assert key in str(denied.value) and "private-value" not in str(denied.value)


def test_launcher_cannot_fall_back_to_source_or_hand_out_root_db_credentials():
    env = {"SERVICE_ID": "assessment", "LEGACY_SCHOOL_ID": "school", "ASSESSMENT_STORAGE_MODE": "isolated",
           "DB_ENGINE": "sqlite", "SQLITE_PATH": "/old/source.sqlite"}
    with pytest.raises(ValueError, match="ASSESSMENT_DB_ENGINE"):
        check_config("assessment-jobs", "assessment", env)
    env.update(ASSESSMENT_DB_ENGINE="sqlite", ASSESSMENT_SQLITE_PATH="/test/assessment.sqlite")
    check_config("assessment-jobs", "assessment", env)
    env.update(ASSESSMENT_DB_ENGINE="mysql", ASSESSMENT_MYSQL_HOST="localhost",
               ASSESSMENT_MYSQL_DATABASE="assessment", ASSESSMENT_MYSQL_USER="root", ASSESSMENT_MYSQL_PASSWORD="test")
    with pytest.raises(ValueError, match="dedicated"):
        check_config("assessment-jobs", "assessment", env)


@pytest.mark.parametrize("name", ["admin-gateway", "student-gateway"])
def test_production_gateway_defaults_to_native_and_rejects_legacy_database(name):
    env = {"SERVICE_ID": name, "APP_ENV": "production"}
    check_config(name, name, env)
    with pytest.raises(ValueError, match="IDENTITY_SESSION_MODE"):
        check_config(name, name, {**env, "IDENTITY_SESSION_MODE": "legacy"})
    env.update(IDENTITY_SESSION_MODE="native", ASSESSMENT_MYSQL_PASSWORD="secret")
    with pytest.raises(ValueError, match="Native gateways"):
        check_config(name, name, env)
    del env["ASSESSMENT_MYSQL_PASSWORD"]
    check_config(name, name, env)


def test_production_assessment_requires_usage_owner_before_first_job():
    env = {"SERVICE_ID": "assessment", "APP_ENV": "production", "LEGACY_SCHOOL_ID": "school",
           "ASSESSMENT_STORAGE_MODE": "isolated", "ASSESSMENT_DB_ENGINE": "sqlite",
           "ASSESSMENT_SQLITE_PATH": "/test/assessment.sqlite"}
    with pytest.raises(ValueError, match="USAGE_SERVICE_URL"):
        check_config("assessment-jobs", "assessment", env)
    env["USAGE_SERVICE_URL"] = "https://usage.example.test"
    check_config("assessment-jobs", "assessment", env)


@pytest.mark.parametrize("setting", ["PROVIDERS_DB_ENGINE", "PROVIDERS_SQLITE_PATH", "PROVIDERS_MYSQL_PASSWORD"])
def test_model_consumers_cannot_receive_the_control_plane_database(setting):
    env = {"APP_ENV": "production", "SERVICE_ID": "media", setting: "sensitive"}
    with pytest.raises(ValueError, match="model control database"):
        check_config("media", "media", env)
