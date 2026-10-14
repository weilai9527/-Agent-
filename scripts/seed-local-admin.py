"""Seed only backend/data/dev.sqlite with clearly labelled fictional admin data.

Run from the project root: python scripts/seed-local-admin.py
Creates an online SQLite backup, writes one transaction, and never replaces rows.
An audit marker prevents duplicate insertion on subsequent runs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from admin_backend.src import env  # Load the same password encryption configuration as the API.
from admin_backend.src.security import encrypt_temporary_password, generate_temporary_password
from backend.src.security import hash_password, verify_password

DB_PATH = ROOT / "backend/data/dev.sqlite"
PREFIX = "local-demo-20261013-"
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def ident(kind: str, index: object) -> str:
    return f"{PREFIX}{kind}-{index}"


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def main() -> None:
    if not DB_PATH.is_file():
        raise SystemExit("Local development database does not exist; start the admin API first.")
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=rw", uri=True, timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    marker = ident("audit", "seed")
    if conn.execute("SELECT 1 FROM admin_audit_logs WHERE id=?", (marker,)).fetchone():
        print(encode({"status": "already_seeded", "database": str(DB_PATH)}))
        return
    backup_path = ROOT / "outputs/backups" / f"before-admin-demo-{NOW:%Y%m%d-%H%M%S}.sqlite"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    prior_fk_errors = set(conn.execute("PRAGMA foreign_key_check").fetchall())
    counts: dict[str, int] = {}

    def insert(table: str, **values: object) -> None:
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))
        counts[table] = counts.get(table, 0) + 1

    colleges = ["计算机学院（测试）", "经济管理学院（测试）", "智能制造学院（测试）"]
    programs = ["软件工程", "数据科学", "市场营销", "电子商务", "机械设计", "自动化"]
    roles = ["前端开发工程师", "数据分析师", "市场专员", "电商运营", "机械设计工程师", "自动化工程师"]
    people = ["林晓宇", "陈思远", "王雨桐", "李明轩", "张若涵", "刘子墨", "赵欣怡", "周浩然",
              "吴佳宁", "徐嘉瑞", "孙语晴", "胡文博", "朱梓萱", "高逸辰", "何沐阳", "郭诗涵",
              "马俊熙", "罗欣悦", "梁星宇", "宋可馨", "郑泽楷", "谢安然", "韩景行", "唐书瑶"]
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for c, name in enumerate(colleges):
            insert("campus_colleges", id=ident("college", c), code=f"TEST-{c+1:02}", name=name)
        for p, name in enumerate(programs):
            insert("campus_programs", id=ident("program", p), college_id=ident("college", p//2),
                   name=name, direction="管理流程测试", coordinator=f"测试辅导员{p+1}")
            insert("campus_classes", id=ident("class", p), program_id=ident("program", p),
                   name=f"{name}2301班（测试）", graduation_year=2027,
                   advisor=f"测试辅导员{p+1}", invite_code=f"TEST2026{p+1:02}")
        for i in range(48):
            p = i % 6
            uid = ident("student", i)
            number = f"202399{i+1:04}"
            name = f"测试·{people[i%24]}" + ("乙" if i >= 24 else "")
            created = NOW - timedelta(days=35-i%12)
            common = dict(student_no=number, name=name, college=colleges[p//2],
                          gender="男" if i%2 == 0 else "女", class_name=f"{programs[p]}2301班（测试）",
                          counselor=f"测试辅导员{p+1}", created_at=stamp(created), updated_at=stamp(NOW))
            if i < 36:
                pending = i >= 28
                password = generate_temporary_password()
                password_hash = hash_password(password)
                assert verify_password(password, password_hash)
                insert("users", id=uid, email=f"{number}@student.local", password_hash=password_hash,
                       must_change_password=int(pending),
                       temp_password_encrypted=encrypt_temporary_password(password) if pending else None,
                       temp_password_created_at=stamp(created) if pending else None,
                       activated_at=None if pending else stamp(created+timedelta(days=1)),
                       last_login_at=None if pending else stamp(NOW-timedelta(days=i%7)),
                       status="disabled" if 24 <= i < 28 else "normal", student_status="在读", **common)
                insert("profiles", id=ident("profile", i), user_id=uid, nickname=name,
                       target_role=roles[p], experience_level="应届生", education_level="本科",
                       target_city=["上海", "杭州", "南京"][p%3],
                       skills=f"{programs[p]}基础、数据分析、沟通协作",
                       resume_text=f"【虚构测试简历】{programs[p]}学生，参与校园实践项目，负责需求梳理与成果展示。" if i<24 else None,
                       project_experience="【测试】校园服务改进项目，负责调研、方案设计与验收。" if i<24 else None)
                insert("student_enrollments", id=ident("enrollment", i), user_id=uid,
                       class_id=ident("class", p) if i<30 else None, student_no=number,
                       focus_flag=int(i%5 == 0), note="虚构测试数据；用于验证管理流程。")
            if i >= 42:
                common["counselor"] = ""
                if i%2:
                    common["gender"] = ""
            insert("student_registrations", id=ident("registration", i),
                   user_id=uid if i<36 else None, imported_by="本地测试数据脚本", **common)
            if i >= 24:
                continue
            interview_id = ident("interview", i)
            state = "completed" if i<18 else ("running" if i<21 else "draft")
            start = NOW-timedelta(days=1+i%14, hours=i%4)
            end = start+timedelta(minutes=24)
            if state == "running":
                start = NOW-timedelta(minutes=8)
            insert("interview_sessions", id=interview_id, user_id=uid, target_role=roles[p],
                   experience_level="应届生", interview_type="综合面试", difficulty="中等",
                   interviewer_style="专业严谨", focus_areas="项目经历、岗位基础、沟通表达",
                   company_context="【虚构测试场景】校园招聘模拟", status=state,
                   created_at=stamp(start), started_at=stamp(start) if state!="draft" else None,
                   completed_at=stamp(end) if state=="completed" else None,
                   updated_at=stamp(end if state=="completed" else NOW))
            score = [56, 63, 68, 72, 77, 81, 85, 90, 94][i%9]
            feedback, timeline = [], []
            dims = dict(technical_depth=score, expression_clarity=min(100,score+3),
                        business_understanding=max(0,score-2))
            for a, (agent_type, agent_name) in enumerate([
                ("technical", "专业面试官"), ("architecture", "方案面试官"), ("hr", "HR面试官")
            ]):
                aid = ident("agent", f"{i}-{a}")
                insert("interview_agents", id=aid, interview_id=interview_id, agent_name=agent_name,
                       agent_type=agent_type, agent_role=agent_name, order_index=a,
                       strategy="【测试】围绕具体经历提问并复盘。",
                       status="completed" if state=="completed" else ("active" if state=="running" and a==0 else "pending"))
                if state=="draft" or (state=="running" and a>0):
                    continue
                question = ["请介绍一次与你应聘岗位相关的项目经历。", "方案遇到资源限制时，你如何取舍？", "请举例说明你如何解决团队分歧。 "][a]
                answer = ["【测试回答】我在校园服务项目中负责需求调研，访谈20名同学，整理高频问题并完成方案验证。",
                          "【测试回答】先明确关键目标，将方案拆为基础功能和后续改进，并通过小范围试运行验证效果。",
                          "【测试回答】我汇总各方意见，通过任务分工和每周同步会议确认进度，最终按时完成成果展示。"][a]
                for turn, (sender, kind, content) in enumerate([("agent", "question", question), ("candidate", "answer", answer)]):
                    mid = ident("message", f"{i}-{a}-{turn}")
                    insert("interview_messages", id=mid, interview_id=interview_id, agent_id=aid,
                           sender_type=sender, message_type=kind, content=content, order_index=a*2+turn,
                           created_at=stamp(start+timedelta(minutes=a*6+turn)))
                insert("interview_evaluations", id=ident("evaluation", f"{i}-{a}"), interview_id=interview_id,
                       message_id=mid, agent_id=aid, score=score, strengths="【测试】回答结构清楚。",
                       issues="【测试】缺少量化效果和方案比较。", suggestions="补充个人贡献和可验证的成果。",
                       dimension_scores=encode(dims), provider="demo", model="fictional-fixture-v1", fallback=0,
                       generated_at=stamp(start+timedelta(minutes=a*6+2)))
                feedback.append(dict(agent_id=aid, agent_name=agent_name, agent_type=agent_type,
                                     score=score, comment="【虚构评价】需要进一步补充量化成果与方案取舍。"))
                timeline.append(dict(message_id=mid, question=question, answer=answer, score=score,
                                     agent_name=agent_name, strengths="回答结构清楚", issues="量化不足",
                                     suggestions="补充成果证据"))
            if state=="completed":
                review = ["pending", "approved", "rejected"][i%3]
                insert("interview_reports", id=ident("report", i), user_id=uid, interview_id=interview_id,
                       total_score=score, grade="A" if score>=90 else "B" if score>=80 else "C" if score>=70 else "D",
                       pass_recommendation="pass" if score>=80 else "hold" if score>=70 else "reject",
                       ability_radar=encode(dims), agent_feedback=encode(feedback), timeline_review=encode(timeline),
                       summary=f"【虚构测试报告】{roles[p]}模拟面试，示例分数{score}，仅供管理流程测试。",
                       suggestions="1. 补充量化结果。\n2. 练习方案取舍。\n3. 根据岗位要求准备具体案例。",
                       provider="demo", model="fictional-fixture-v1", fallback=0, generated_at=stamp(end),
                       review_status=review, reviewed_by="测试复核员" if review!="pending" else None,
                       reviewed_at=stamp(end+timedelta(hours=1)) if review!="pending" else None,
                       created_at=stamp(end), updated_at=stamp(end))
        insert("admin_audit_logs", id=marker, actor_email="local-demo@testing.invalid", action="local_demo.seed",
               target_type="database", summary="新增虚构测试数据：48条名单、36个账号、24场面试、18份报告。")
        new_fk_errors = set(conn.execute("PRAGMA foreign_key_check").fetchall())-prior_fk_errors
        if new_fk_errors:
            raise RuntimeError(f"Foreign key errors: {new_fk_errors}")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
    summary = {"status": "seeded", "database": str(DB_PATH), "backup": str(backup_path), "inserted": counts}
    manifest = backup_path.with_suffix(".json")
    manifest.write_text(encode(summary), encoding="utf-8")
    conn.close()
    print(encode(summary))


if __name__ == "__main__":
    main()
