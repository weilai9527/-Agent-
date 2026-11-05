"""验证已有面试使用创建时冻结的资料，新版本不会改写其依据。"""
import os
import subprocess
import sys
from pathlib import Path


def test_freezes_profile_before_creating_the_session(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, APP_ENV="test", SERVICE_ID="interview", INTERVIEW_DB_ENGINE="sqlite", INTERVIEW_SQLITE_PATH=str(tmp_path / "interview.sqlite"),
               PROFILE_SERVICE_URL="https://profile.example.test", LEGACY_SCHOOL_ID="school")
    script = """
from unittest.mock import patch
from backend.src import env
env.load_env_file = lambda: None
from services.interview import runtime as main
from fastapi import HTTPException
user = {"id": "student", "name": "Student"}
def profile(revision):
    return {"school_id":"school","actor_id":"student","version":revision,
            "analysis":{"core_skills":[f"skill-{revision}"]}}
with patch.object(main.profile_context, "capture", side_effect=[profile(1),profile(2),HTTPException(503)]):
    first, second = [main.create_interview({"target_role":"Engineer"}, user=user)["interview"]["id"] for _ in range(2)]
    try:
        main.create_interview({"target_role":"Engineer"}, user=user)
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("An unreachable configured profile service created an incomplete session")
assert main.one("SELECT COUNT(*) AS n FROM interview_sessions")["n"] == 2
for i, iid in enumerate((first,second),1):
    assert main.resume_analysis_for_prompt(user,interview_id=iid,cached_only=True) == profile(i)["analysis"]
    assert not main.one("SELECT name FROM sqlite_master WHERE name IN ('users','profiles','interview_reports')")
    assert main.profile_context.load(iid)["profile_version"] == i
"""
    subprocess.run([sys.executable, "-c", script], cwd=root, env=env, check=True, timeout=25)
