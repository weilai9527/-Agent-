"""离线恢复 IBD 数据行到全新 SQLite 副本，不连接业务库，不替换已有目标。

调用方提供可信的空 SQLite 结构模板、IBD 备份目录、已审查的 ibd2sql 脚本及仓库外的新文件名。
只解释字面量并通过 SQLite 参数绑定写入。任何抽取、解析、约束或检查失败均不发布结果。
"""
import argparse
from contextlib import closing
from decimal import Decimal
import json
import math
import os
import shutil
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,63}\Z")
HEADER = re.compile(
    r"\s*(?:INSERT|REPLACE)\s+INTO\s+(?:`[A-Za-z_0-9]+`\.)?`([A-Za-z_0-9]+)`\s*"
    r"\(\s*(`[A-Za-z_0-9]+`(?:\s*,\s*`[A-Za-z_0-9]+`)*)\s*\)\s+VALUES\s*", re.I)
NUMBER = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][+-]?\d+)?")
ESCAPES = {"0":"\0", "b":"\b","n":"\n","r":"\r","t":"\t","Z":"\x1a", "'":"'",'"':'"', "\\":"\\"}
ROW_LIMIT = 8 * 1024 * 1024


def literal(text, pos):
    if text[pos:pos+1] == "'":
        pieces = []
        pos += 1
        while pos < len(text):
            char = text[pos]
            pos += 1
            if char == "'":
                if text[pos:pos+1] != "'":
                    return "".join(pieces),pos
                pieces.append("'")
                pos += 1
            elif char == "\\":
                escape = text[pos:pos+1]
                if escape not in ESCAPES:
                    raise ValueError("无法无损转换的 MySQL 转义。")
                pieces.append(ESCAPES[escape])
                pos += 1
            else:
                pieces.append(char)
        raise ValueError("字符串未结束。")
    for regex in (r"(?i:NULL)\b", r"0[xX][A-Fa-f0-9]+"):
        match = re.compile(regex).match(text,pos)
        if match:
            word = match[0]
            return (None if word.upper()=="NULL" else bytes.fromhex(word[2:])), match.end()
    match = NUMBER.match(text,pos)
    if not match:
        raise ValueError("仅支持 NULL、数值、十六进制字节及引号字符串。")
    # 以十进制原文绑定，交给目标声明的列亲和性解释。超出 SQLite 有符号整数范围须人工处理。
    value = match[0]
    if re.fullmatch(r"[+-]?\d+",value) and not -(2**63) <= int(value) < 2**63:
        raise ValueError("整数超出 SQLite 无损范围。")
    if not Decimal(value).is_finite() or not math.isfinite(float(value)):
        raise ValueError("数值不能表示。")
    return value, match.end()


def parse_row(line, table, known):
    match = HEADER.match(line)
    if not match or match[1] != table:
        raise ValueError("语句不是本表的完整列 INSERT/REPLACE。")
    columns = re.findall(r"`([A-Za-z_0-9]+)`", match[2])
    if len(set(columns)) != len(columns) or set(columns)-known:
        raise ValueError("导出列与可信模板不匹配。")
    tail = line[match.end():].strip()
    if not tail.startswith("("):
        raise ValueError("缺少数据行。")
    pos, values = 1, []
    for index in range(len(columns)):
        while pos<len(tail) and tail[pos].isspace(): pos += 1
        value, pos = literal(tail,pos)
        values.append(value)
        while pos<len(tail) and tail[pos].isspace(): pos += 1
        expected = ")" if index == len(columns)-1 else ","
        if tail[pos:pos+1] != expected:
            raise ValueError("列数或分隔符无效。")
        pos += 1
    if tail[pos:].strip() not in {"",";"}:
        raise ValueError("额外语句或多行 INSERT 未经支持。")
    return columns, values


def import_table(db, ibd, sql_file, known):
    table = ibd.stem
    count = 0
    with sql_file.open("rb") as stream:
        while data := stream.readline(ROW_LIMIT+1):
            if len(data) > ROW_LIMIT:
                raise ValueError(f"{table} 出现过大的数据行。")
            line = data.decode("utf8").strip()
            if not line or line.startswith(("-- ", "#")):
                continue
            try:
                cols, values = parse_row(line,table,known)
                names = ",".join('"'+c+'"' for c in cols)
                slots = ",".join("?" for _ in cols)
                db.execute(f'INSERT INTO "{table}" ({names}) VALUES ({slots})',values)
            except (ValueError, sqlite3.Error, ArithmeticError):
                # 行值、SQL 和工具错误可能含真实学生资料，不向日志输出其内容。
                raise ValueError(f"{table} 第 {count+1} 条记录解析或插入失败。") from None
            count += 1
    return count


def restore(schema, backup_dir, extractor, output, expected_counts=None):
    schema, backup_dir, extractor = (p.resolve(strict=True) for p in (schema,backup_dir,extractor))
    output = output.absolute()
    if (output.is_symlink() or output.exists() or output.resolve().is_relative_to(ROOT)
            or output.suffix not in {".db",".sqlite",".sqlite3"} or not output.parent.is_dir()):
        raise ValueError("目标必须是仓库外尚不存在的 SQLite 文件，且父目录已存在。")
    if not (schema.is_file() and backup_dir.is_dir() and extractor.is_file()):
        raise ValueError("需要只读结构模板、备份目录和受信任的抽取器文件。")
    tables = sorted(backup_dir.glob("*.ibd"))
    if not tables or any(not IDENTIFIER.fullmatch(p.stem) or p.is_symlink() or not p.is_file() for p in tables):
        raise ValueError("没有有效 IBD 文件，或表名/文件类型不安全。")
    if expected_counts is not None and (not isinstance(expected_counts, dict)
            or set(expected_counts) != {p.stem for p in tables}
            or any(type(n) is not int or n < 0 for n in expected_counts.values())):
        raise ValueError("核对清单必须为每个 IBD 表指定非负整数行数。")
    with tempfile.TemporaryDirectory(prefix=".school-offline-", dir=output.parent) as temp:
        work = Path(temp)
        stage = work/"restore.sqlite"
        stage.touch(mode=0o600)
        with closing(sqlite3.connect(stage)) as db:
            with closing(sqlite3.connect(schema.as_uri()+"?mode=ro", uri=True)) as source:
                source.backup(db)
            db.execute("PRAGMA trusted_schema=OFF")
            objects = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
            if any(kind not in {"index","table"} or (kind=="table" and (not IDENTIFIER.fullmatch(name)
                         or not (sql or "").upper().lstrip().startswith("CREATE TABLE "))) for kind,name,sql in objects):
                raise ValueError("结构模板不能包含视图、触发器、虚表或非标准表名。")
            names = {name for kind,name,_ in objects if kind=="table"}
            if any(db.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone() for name in names):
                raise ValueError("结构模板必须为空；不得将运营数据库作为导入目标。")
            if set(p.stem for p in tables)-names:
                raise ValueError("备份含有模板以外的表。")
            db.execute("PRAGMA foreign_keys=OFF")
            total = 0
            with db:
                db.execute("BEGIN IMMEDIATE")
                for ibd in tables:
                    sql_file = work/"rows.sql"
                    sql_file.touch(mode=0o600)
                    input_copy = work / ibd.name
                    shutil.copyfile(ibd, input_copy)
                    # 转换器只取得临时输入副本，即使在同目录生成索引、统计或辅助文件也不影响备份源。
                    # 只运行显式指定并已审核的本地工具，不传入学校 DSN、模型密钥或部署环境。
                    with sql_file.open("wb") as out:
                        run = subprocess.run([sys.executable, str(extractor), str(input_copy), "--sql", "--complete-insert", "--replace"],
                                             cwd=work, env={k:os.environ[k] for k in ("PATH","SYSTEMROOT","LANG") if k in os.environ},
                                             stdout=out, stderr=subprocess.DEVNULL, timeout=600)
                    if run.returncode != 0:
                        raise ValueError(f"{ibd.stem} 抽取失败，未发布结果。")
                    known = {r[1] for r in db.execute(f'PRAGMA table_info("{ibd.stem}")')}
                    amount = import_table(db,ibd,sql_file,known)
                    if expected_counts is not None and amount != expected_counts[ibd.stem]:
                        raise ValueError(f"{ibd.stem} 行数与核对清单不符。")
                    if not amount and expected_counts is None:
                        raise ValueError(f"{ibd.stem} 未产生数据行；确认为空表后请提供 --row-counts。")
                    total += amount
                    input_copy.unlink()
                    sql_file.unlink()
                if db.execute("PRAGMA foreign_key_check").fetchone() or db.execute("PRAGMA integrity_check").fetchone()!=("ok",):
                    raise ValueError("恢复结果未通过外键或完整性校验。")
        # 同盘硬链接为原子“仅在不存在时发布”；若另一操作员同时占用目标，则保留其文件。
        os.link(stage, output)
    return total


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("schema","backup-dir","extractor","output"):
        cli.add_argument("--"+key, required=True, type=Path)
    cli.add_argument("--row-counts", type=Path, help="只读行数核对 JSON，按表名记录行数。")
    args = cli.parse_args()
    try:
        expected = json.loads(args.row_counts.read_text(encoding="utf8")) if args.row_counts else None
        count = restore(args.schema,args.backup_dir,args.extractor,args.output,expected)
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as err:
        cli.exit(1, f"离线恢复失败：{err}\n")
    print(f"完整性校验通过，新文件已发布。共导入 {count} 行。")


if __name__ == "__main__":
    main()
