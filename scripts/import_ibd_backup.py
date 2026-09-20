# -*- coding: utf-8 -*-
"""将本地数据库备份（MySQL .ibd 文件）中的数据导入 SQLite。

流程：对每张表的 .ibd 调用 ibd2sql 提取 INSERT 语句，
转换为 SQLite 兼容语法后写入 backend/data/dev.sqlite。
"""
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT = Path(r"f:\zzsyxm\-Agent-")
PY = PROJECT / ".venv" / "Scripts" / "python.exe"
IBD2SQL = Path(r"C:\Users\nyar\AppData\Local\Temp\ibd2sql\ibd2sql-main\main.py")
BACKUP_DIR = PROJECT / "本地数据库备份" / "multi_agent_interview"
DB_PATH = PROJECT / "backend" / "data" / "dev.sqlite"


def extract_inserts(ibd_path: Path) -> str:
    result = subprocess.run(
        [str(PY), str(IBD2SQL), str(ibd_path), "--sql", "--complete-insert", "--replace"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout


# MySQL 转义序列 -> SQLite 字面量（单次从左到右扫描，保证 \\ 优先于 \n 被正确解析）
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "", "'": "''", "\\": "\\"}


def _unescape(stmt: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), stmt)


def to_sqlite_insert(line: str, table: str) -> str | None:
    line = line.strip()
    if not line.startswith("REPLACE INTO"):
        return None
    # REPLACE INTO `db`.`table` (`col`, ...) VALUES (...); -> REPLACE INTO "table" (`col`, ...) VALUES (...)
    line = re.sub(
        rf"^REPLACE INTO `[^`]+`.`{re.escape(table)}`",
        f'REPLACE INTO "{table}"',
        line,
    )
    return _unescape(line)


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    # 清空应用 seed 的 catalog 数据，让备份数据完整接管（避免 version_id 冲突产生孤儿行）
    catalog_tables = sorted(t for t in existing if t.startswith("catalog_"))
    for table in catalog_tables:
        conn.execute(f'DELETE FROM "{table}"')
    conn.commit()
    print(f"已清空 seed catalog 表: {len(catalog_tables)} 张\n")
    total_inserted = 0
    for ibd in sorted(BACKUP_DIR.glob("*.ibd")):
        table = ibd.stem
        if table not in existing:
            print(f"SKIP  {table}（目标库无此表）")
            continue
        output = extract_inserts(ibd)
        before = conn.total_changes
        errors = 0
        for raw in output.splitlines():
            stmt = to_sqlite_insert(raw, table)
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except sqlite3.Error as exc:
                errors += 1
                if errors <= 2:
                    print(f"  ERR {table}: {exc}")
        conn.commit()
        inserted = conn.total_changes - before
        total_inserted += inserted
        print(f"OK    {table}: 插入 {inserted} 行" + (f"，{errors} 行失败" if errors else ""))

    conn.close()
    print(f"\n完成，共插入 {total_inserted} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
