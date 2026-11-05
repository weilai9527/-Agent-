"""从没有旧后端源码的临时部署启动身份服务，并用两种历史摘要完成登录。"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import textwrap


def test_identity_without_either_old_backend(tmp_path):
    root = Path(__file__).resolve().parents[2]
    for source in ("shared", "services/identity"):
        for p in (root / source).glob("*.py"):
            if p.name.startswith("test_"):
                continue
            dest = tmp_path / p.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)

    package_paths = [p for p in sys.path if p and Path(p).is_absolute() and not Path(p).resolve().is_relative_to(root)]
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR", "LANG") if k in os.environ}
    env.update(PYTHONPATH=os.pathsep.join([str(tmp_path), *package_paths]), APP_ENV="test", SERVICE_ID="identity",
               IDENTITY_DB_ENGINE="sqlite", IDENTITY_SQLITE_PATH=str(tmp_path / "accounts.sqlite"), LEGACY_SCHOOL_ID="school")
    code = """
        import base64, hashlib
        from importlib.util import find_spec
        from fastapi.testclient import TestClient
        assert find_spec('backend') is None and find_spec('admin_backend') is None
        from services.identity.app import app
        from shared.account_security import hash_student_token, hash_staff_token
        def encode(raw): return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        pw = "Independent-native-password-231"
        salt = "existing-encoded-salt"
        def previous(size):
            return "scrypt$"+salt+"$"+encode(hashlib.scrypt(pw.encode(), salt=salt.encode(), n=16384,r=8,p=1,dklen=size))
        assert hash_student_token("test")==encode(hashlib.sha256(b"test").digest())
        assert hash_staff_token("test")==hashlib.sha256(b"test").hexdigest()
        with TestClient(app) as client:
            with app.state.store.transaction(write=True) as tx:
                tx.execute("INSERT INTO identity_staff VALUES ('school','m','m@school.test',?,'校管','admin','normal','[]',1)",
                           (previous(32),))
                tx.execute("INSERT INTO identity_student_credentials VALUES ('school','s','S001','学生',?,'normal',0)", (previous(64),))
            assert client.post('/sessions/staff/login',json={'school_id':'school','email':'m@school.test','password':pw}).status_code == 200
            assert client.post('/sessions/student/login',json={'school_id':'school','student_no':'S001','password':pw}).status_code == 200
            assert client.get('/sessions/staff/me').json()['actor_id'] == 'm'
            assert client.get('/sessions/student/me').json()['user']['id'] == 's'
    """
    run = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=50)
    assert run.returncode == 0, run.stderr
