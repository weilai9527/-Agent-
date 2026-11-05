"""旧数据工具只能发布新副本；建库入口只生成原生多库授权，不能接触部署秘密。"""
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts import import_ibd_backup as offline


ROOT = Path(__file__).resolve().parents[2]


def files(tmp_path):
    schema, backup = tmp_path/"template.sqlite", tmp_path/"ibd"
    with sqlite3.connect(schema) as db:
        db.executescript("""CREATE TABLE staff(id INTEGER PRIMARY KEY, name TEXT, payload BLOB);
                         CREATE TABLE scores(id INTEGER PRIMARY KEY, teacher INTEGER REFERENCES staff(id));""")
    backup.mkdir()
    extractor = tmp_path/"synthetic_extractor.py"
    # 测试抽取器将合成行写入标准输出，并故意破坏其接收到的副本，以验证原备份不受影响。
    extractor.write_text("import sys\nfrom pathlib import Path\np=Path(sys.argv[1]);print(p.read_text());p.write_text('已处理')\n")
    raw = "REPLACE INTO `old`.`staff` (`id`,`name`,`payload`) VALUES (1,'学\\'生;\\0甲',0x01ff);"
    (backup/"staff.ibd").write_text(raw)
    (backup/"scores.ibd").write_text("REPLACE INTO `old`.`scores` (`id`,`teacher`) VALUES (2,1);")
    return schema,backup,extractor,tmp_path/"recovered.sqlite"


def test_recovery_only_creates_new_reviewed_copy(tmp_path):
    source,backup,tool,out=files(tmp_path)
    before=source.read_bytes()
    raw=(backup/"staff.ibd").read_bytes()
    assert offline.restore(source,backup,tool,out,{"staff":1,"scores":1})==2
    assert (backup/"staff.ibd").read_bytes()==raw and source.read_bytes()==before
    with sqlite3.connect(out.as_uri()+"?mode=ro",uri=True) as db:
        assert db.execute("SELECT * FROM staff").fetchone()==(1,"学'生;\x00甲",b"\x01\xff")
        assert db.execute("PRAGMA foreign_key_check").fetchall()==[]
    existing = out.read_bytes()
    with pytest.raises(ValueError, match="尚不存在"):
        offline.restore(source,backup,tool,out)
    assert out.read_bytes()==existing


@pytest.mark.parametrize("problem", ["语句", "列", "外键", "计数", "抽取器", "旧目标", "非空模板", "触发器", "空输出"])
def test_incomplete_restore_never_publishes(tmp_path,problem):
    schema,backup,extractor,out=files(tmp_path)
    counts=None
    if problem=="语句":
        (backup/"staff.ibd").write_text("REPLACE INTO `staff`(`id`) VALUES (1); ATTACH 'other.sqlite' AS extra;")
    elif problem=="列":
        (backup/"staff.ibd").write_text("REPLACE INTO `staff`(`unknown`) VALUES (1);")
    elif problem=="外键":
        (backup/"scores.ibd").write_text("REPLACE INTO `scores`(`id`,`teacher`) VALUES(1,99);")
    elif problem=="计数":
        counts={"staff":2,"scores":1}
    elif problem=="空输出":
        (backup/"scores.ibd").write_text("")
    elif problem=="抽取器":
        extractor.write_text("raise SystemExit(5)")
    elif problem=="旧目标":
        out=ROOT/"backend"/"data"/"test-never-published.sqlite"
    else:
        with sqlite3.connect(schema) as db:
            if problem=="非空模板": db.execute("INSERT INTO staff(id) VALUES(1)")
            else: db.execute("CREATE TRIGGER hidden AFTER INSERT ON staff BEGIN DELETE FROM staff; END")
    with pytest.raises(ValueError):
        offline.restore(schema,backup,extractor,out,counts)
    assert not out.exists()
    assert not list(tmp_path.glob(".school-offline-*"))


def test_default_entrypoints_cannot_provision_old_database(tmp_path):
    env_file=tmp_path/".env"
    env_file.write_text("MYSQL_PASSWORD=Synthetic-Secret")
    seed=subprocess.run([sys.executable,str(ROOT/"scripts/seed-local-admin.py")],cwd=tmp_path,capture_output=True,text=True)
    assert seed.returncode!=0 and not (tmp_path/"backend").exists()
    tool=ROOT/"scripts/native-mysql-plan.js"
    plan=subprocess.check_output(["node",str(tool)],cwd=tmp_path,text=True)
    assert plan.count("CREATE DATABASE IF NOT EXISTS")==13 and plan.count("CREATE USER IF NOT EXISTS")==14
    assert "GRANT SELECT ON `schoolappcredentials`.* TO ''schoolappverifier''@''localhost''" in plan
    assert "Synthetic-Secret" not in plan and "multi_agent_interview" not in plan and "IDENTIFIED BY" not in plan
    for args in (["--prefix","old_%"],["--client-host","%"],["--password","secret"]):
        rejected=subprocess.run(["node",str(tool),*args],cwd=tmp_path,capture_output=True)
        assert rejected.returncode!=0 and not rejected.stdout
    assert env_file.read_text()=="MYSQL_PASSWORD=Synthetic-Secret"
