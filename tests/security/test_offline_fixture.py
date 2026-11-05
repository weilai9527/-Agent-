"""离线夹具只能访问固定的合成数据库，测试标志、网络请求和文件替换都不能启用旧写服务。"""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from shared.offline_fixture import OfflineClientOnly


def test_fixture_pins_file_and_refuses_unsafe_paths(tmp_path):
    script = r"""
        import os, sqlite3
        from pathlib import Path
        from shared.offline_fixture import enable_offline_fixture, connect_offline_sqlite
        private = Path(os.environ["TEST_DIR"])
        actual = private / "isolated.sqlite"
        # 伪造临时根不得使工作区或主目录变成可写夹具。
        os.environ.update(TMPDIR=str(Path.home()), SQLITE_PATH=str(Path.home() / "never-open-offline.sqlite"))
        try: enable_offline_fixture()
        except RuntimeError: pass
        else: raise AssertionError("TMPDIR 越权")
        assert not Path(os.environ["SQLITE_PATH"]).exists()
        original = private / "other.sqlite"
        original.write_bytes(b"")
        os.link(original, actual)
        os.environ["SQLITE_PATH"] = str(actual)
        try: enable_offline_fixture()
        except RuntimeError: pass
        else: raise AssertionError("夹具接受硬链接")
        actual.unlink()
        enable_offline_fixture()
        with connect_offline_sqlite(actual) as db:
            db.execute("CREATE TABLE fixture(id INTEGER PRIMARY KEY)")
        before = actual.read_bytes()
        os.replace(original, actual)
        try: connect_offline_sqlite(actual)
        except RuntimeError: pass
        else: raise AssertionError("授权后更换了目标")
        assert actual.read_bytes() == b"" and before
    """
    env = {k: os.environ[k] for k in ("PATH","PYTHONPATH","SYSTEMROOT") if k in os.environ}
    env.update(APP_ENV="test", DB_ENGINE="sqlite", TEST_DIR=str(tmp_path))
    cmd = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], env=env, cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, timeout=25)
    assert cmd.returncode == 0, cmd.stderr


@pytest.mark.parametrize("kind", ["lifespan", "http", "websocket"])
def test_real_asgi_server_cannot_execute_archived_handlers(kind):
    async def run():
        messages = []
        async def retired(*args):
            raise AssertionError("网络 ASGI 请求进入了旧生命周期或写入处理器")
        async def send(message):
            messages.append(message)
        async def receive():
            return {"type": "lifespan.startup"}
        # 代理可改写 peer 文本，不能改变网络服务器实现的 ASGI 范围。
        await OfflineClientOnly(retired)({"type":kind, "asgi":{"version":"3.0"}, "client":("testclient",1)},
                                         receive, send)
        return messages
    result = asyncio.run(run())[0]
    assert result["type"] == {"http":"http.response.start","websocket":"websocket.close",
                              "lifespan":"lifespan.startup.failed"}[kind]
