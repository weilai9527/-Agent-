from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_resume_major_options_follow_admin_campus_data(tmp_path):
    project_dir = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DB_ENGINE": "sqlite", "SQLITE_PATH": str(tmp_path / "resume-options.sqlite")})
    script = textwrap.dedent(
        """
        import backend.src.main as main

        # A candidate-only database still exposes the published catalog.
        before = main.load_resume_form_settings()
        assert any(college['name'] == '计算机学院' and college['majors'] for college in before['colleges'])

        with main.db:
            main.db.execute("CREATE TABLE campus_colleges (id TEXT PRIMARY KEY, name TEXT, status TEXT)").close()
            main.db.execute("CREATE TABLE campus_programs (id TEXT PRIMARY KEY, college_id TEXT, name TEXT, status TEXT)").close()
            main.db.execute("INSERT INTO campus_colleges VALUES ('c1', '计算机学院', 'active')").close()
            main.db.execute("INSERT INTO campus_colleges VALUES ('c2', '停用学院', 'inactive')").close()
            main.db.execute("INSERT INTO campus_programs VALUES ('p1', 'c1', '软件工程', 'active')").close()
            main.db.execute("INSERT INTO campus_programs VALUES ('p2', 'c1', '软件工程', 'active')").close()
            main.db.execute("INSERT INTO campus_programs VALUES ('p3', 'c1', '停用专业', 'inactive')").close()
            main.db.execute("INSERT INTO campus_programs VALUES ('p4', 'c2', '无效专业', 'active')").close()

        after = main.load_resume_form_settings()['colleges']
        computer = next(college for college in after if college['name'] == '计算机学院')
        names = [major['name'] for major in computer['majors']]
        assert names.count('软件工程') == 1
        assert '计算机科学与技术' not in names
        assert '停用专业' not in names
        assert not any(college['name'] == '停用学院' for college in after)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=project_dir, env=environment,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
