"""在一次性 MySQL 实例验证分域 DDL、新账号锁定、已有凭据保留和错误授权拒绝。"""
import argparse
from contextlib import closing
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

import pymysql


ROOT = Path(__file__).resolve().parents[1]


def check(binary, folder):
    datadir = folder / "data"
    datadir.mkdir()
    socket = folder / "mysqld.sock"
    common = [str(binary),"--no-defaults",f"--basedir={binary.parent.parent}",f"--datadir={datadir}"]
    subprocess.run([*common,"--initialize-insecure"],check=True,capture_output=True,timeout=90)
    # 只允许私有目录下的 Unix 套接字，没有 TCP 监听，也不读取用户安装的 my.cnf。
    process = subprocess.Popen([*common,"--skip-networking","--mysqlx=OFF","--skip-log-bin",f"--socket={socket}",
                                f"--pid-file={folder/'mysqld.pid'}",f"--log-error={folder/'server.log'}"])
    try:
        opts = dict(unix_socket=str(socket),user="root",autocommit=True)
        until = time.monotonic()+45
        while True:
            try:
                conn = pymysql.connect(**opts)
                break
            except pymysql.OperationalError:
                if process.poll() is not None or time.monotonic() >= until:
                    raise RuntimeError("一次性 MySQL 未就绪。") from None
                time.sleep(.15)
        text = subprocess.check_output(["node",str(ROOT/"scripts/native-mysql-plan.js"),"--prefix","plancase"],text=True)
        sql = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
        def apply(*, simulate_ignore_errors=False):
            with closing(pymysql.connect(**opts)) as dba, dba.cursor() as cursor:
                for statement in sql.split(";"):
                    if statement.strip():
                        try:
                            cursor.execute(statement)
                        except pymysql.MySQLError as exc:
                            if not simulate_ignore_errors or exc.args[0] != 3819:
                                raise
        with conn, conn.cursor() as cursor:
            apply()
            cursor.execute("SELECT COUNT(*),SUM(account_locked='Y'),SUM(ssl_type='ANY') FROM mysql.user WHERE User LIKE 'plancase%'")
            assert tuple(map(int,cursor.fetchone())) == (14,14,14)
            cursor.execute("SELECT TABLE_SCHEMA,PRIVILEGE_TYPE FROM INFORMATION_SCHEMA.SCHEMA_PRIVILEGES WHERE GRANTEE=%s",
                           ("'plancaseverifier'@'localhost'",))
            assert cursor.fetchall() == (("plancasecredentials","SELECT"),)
            cursor.execute("ALTER USER 'plancaseidentity'@'localhost' IDENTIFIED BY %s ACCOUNT UNLOCK", (secrets.token_urlsafe(32),))
            cursor.execute("SELECT authentication_string, account_locked FROM mysql.user WHERE User='plancaseidentity'")
            previous = cursor.fetchone()
            cursor.execute("CREATE TABLE plancaseidentity.synthetic_marker (id INT)")
            apply()
            cursor.execute("SELECT authentication_string, account_locked FROM mysql.user WHERE User='plancaseidentity'")
            assert cursor.fetchone() == previous
            cursor.execute("GRANT DELETE ON plancasecredentials.* TO 'plancaseverifier'@'localhost'")
            try:
                apply()
            except pymysql.MySQLError as exc:
                assert exc.args[0] == 3819, "应由权限预检的 CHECK 约束拒绝。"
            else:
                raise AssertionError("只读验真账号具有写权限时 DDL 未被拒绝。")
            cursor.execute("DROP USER 'plancasemedia'@'localhost'")
            apply(simulate_ignore_errors=True)
            cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE User='plancasemedia'")
            assert cursor.fetchone() == (0,), "即便忽略前置错误，后续 DDL 也不得创建或授权"
            print("通过：13 个域及单独验真账号、精确 TLS 授权、重复执行不改口令，验真越权拒绝。")
    finally:
        process.terminate()
        try: process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--mysqld",type=Path,required=True,help="本地 MySQL 8 mysqld 可执行文件。")
    args = cli.parse_args()
    with tempfile.TemporaryDirectory(prefix="mysql-plan-",dir="/tmp") as directory:
        check(args.mysqld.resolve(strict=True), Path(directory))
