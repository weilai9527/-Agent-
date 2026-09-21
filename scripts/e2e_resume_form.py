"""端到端验证：填写简历模块 + 管理端填写简历设置。

流程：
1. 直接向 SQLite 插入临时管理员账号
2. 管理端登录，配置学院/专业下拉（PUT /api/admin/resume-form-settings）并读取验证
3. 插入临时学生注册信息，候选人端 student-login
4. 候选人端读取下拉配置（GET /api/resume-form/settings）
5. 候选人端保存填写简历（PUT /api/resume-form）
6. 读取填写简历（GET /api/resume-form）验证姓名/学号自动回填
7. 验证 profiles.resume_text 同步生成摘要
8. 清理临时数据
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from admin_backend.src.security import hash_password  # noqa: E402

DB_PATH = PROJECT_ROOT / "backend" / "data" / "dev.sqlite"
ADMIN_BASE = "http://127.0.0.1:3002"
CANDIDATE_BASE = "http://127.0.0.1:3001"

TEMP_ADMIN_EMAIL = "e2e.resume@multi-agent.local"
TEMP_ADMIN_PASSWORD = "E2eResume#2026"
TEST_STUDENT_NO = "20240001"
TEST_NAME = "王五"


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    step("0. 清理可能残留的测试数据")
    conn.execute("DELETE FROM admin_users WHERE email = ?", (TEMP_ADMIN_EMAIL,))
    conn.execute("DELETE FROM student_registrations WHERE student_no = ?", (TEST_STUDENT_NO,))
    conn.execute("DELETE FROM users WHERE email LIKE '2024000%@student.local'")
    conn.execute("DELETE FROM resume_form_settings")
    conn.commit()

    step("1. 插入临时管理员")
    conn.execute(
        "INSERT INTO admin_users (id, email, password_hash, name, role, status) VALUES (?, ?, ?, ?, 'super_admin', 'normal')",
        (str(uuid4()), TEMP_ADMIN_EMAIL, hash_password(TEMP_ADMIN_PASSWORD), "E2E 测试管理员"),
    )
    conn.commit()
    print(f"已创建 {TEMP_ADMIN_EMAIL}")

    admin_client = httpx.Client(base_url=ADMIN_BASE, timeout=15)
    candidate_client = httpx.Client(base_url=CANDIDATE_BASE, timeout=15)

    try:
        step("2. 管理端登录")
        resp = admin_client.post(
            "/api/admin/auth/login",
            json={"email": TEMP_ADMIN_EMAIL, "password": TEMP_ADMIN_PASSWORD},
            headers={"Origin": "http://127.0.0.1:5174"},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        print("登录成功:", resp.json().get("admin", {}).get("email"))

        step("3. 配置填写简历设置（学院/专业）")
        colleges = [
            {"id": "c1", "name": "计算机学院", "majors": [{"id": "m1", "name": "软件工程"}, {"id": "m2", "name": "大数据技术"}]},
            {"id": "c2", "name": "财经学院", "majors": [{"id": "m3", "name": "会计学"}]},
        ]
        resp = admin_client.put(
            "/api/admin/resume-form-settings",
            json={"colleges": colleges},
            headers={"Origin": "http://127.0.0.1:5174"},
        )
        assert resp.status_code == 200, f"保存配置失败: {resp.status_code} {resp.text}"
        print("配置保存成功")

        step("4. 管理端读取配置验证")
        resp = admin_client.get("/api/admin/resume-form-settings", headers={"Origin": "http://127.0.0.1:5174"})
        assert resp.status_code == 200, f"读取配置失败: {resp.status_code} {resp.text}"
        saved = resp.json()["colleges"]
        print("配置:", [(c["name"], [m["name"] for m in c["majors"]]) for c in saved])
        assert len(saved) == 2 and saved[0]["majors"][0]["name"] == "软件工程"

        step("5. 插入临时学生注册信息")
        conn.execute(
            "INSERT INTO student_registrations (id, student_no, name) VALUES (?, ?, ?)",
            (str(uuid4()), TEST_STUDENT_NO, TEST_NAME),
        )
        conn.commit()

        step("6. 候选人端登录")
        resp = candidate_client.post(
            "/api/auth/student-login",
            json={"studentNo": TEST_STUDENT_NO, "name": TEST_NAME},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        print("登录成功:", resp.json().get("user", {}).get("email"))

        step("7. 候选人端读取下拉配置")
        resp = candidate_client.get("/api/resume-form/settings")
        assert resp.status_code == 200, f"读取配置失败: {resp.status_code} {resp.text}"
        colleges_data = resp.json()["colleges"]
        print("候选人端配置:", [(c["name"], [m["name"] for m in c["majors"]]) for c in colleges_data])
        assert len(colleges_data) == 2

        step("8. 保存填写简历")
        form = {
            "college": "计算机学院",
            "major": "软件工程",
            "professional_skills": "熟练掌握 Python、Java，具备 Web 全栈开发能力",
            "advantages": "学习能力强，有团队合作经验",
            "education": "计算机学院软件工程专业，GPA 3.5",
            "honors": "校级二等奖学金",
            "projects": "参与校园二手交易平台开发，负责后端接口设计",
            "languages": "英语 CET-4",
            "works": "GitHub 个人仓库",
            "skills": "Python, Java, MySQL, Vue",
            "certificates": "软件设计师",
            "bonus": "参与开源社区贡献",
        }
        resp = candidate_client.put("/api/resume-form", json=form)
        assert resp.status_code == 200, f"保存失败: {resp.status_code} {resp.text}"
        saved_form = resp.json()["form"]
        print("保存成功, 生成摘要前 120 字:", resp.json()["resume_text"][:120].replace("\n", " / "))
        assert saved_form["college"] == "计算机学院" and saved_form["major"] == "软件工程"
        assert "专业技能" not in saved_form  # 非法字段应被忽略

        step("9. 读取填写简历（姓名/学号自动回填）")
        resp = candidate_client.get("/api/resume-form")
        assert resp.status_code == 200, f"读取失败: {resp.status_code} {resp.text}"
        data = resp.json()
        print(f"姓名={data['name']} 学号={data['student_no']} 学院={data['form']['college']}")
        assert data["name"] == TEST_NAME and data["student_no"] == TEST_STUDENT_NO
        assert data["form"]["skills"] == "Python, Java, MySQL, Vue"

        step("10. 验证 profiles.resume_text 已同步")
        row = conn.execute("SELECT resume_text, skills FROM profiles WHERE user_id IN (SELECT user_id FROM student_registrations WHERE student_no = ?)", (TEST_STUDENT_NO,)).fetchone()
        assert row is not None and row["resume_text"], "profiles.resume_text 未同步"
        print("profiles.resume_text 已同步, 长度:", len(row["resume_text"]))

        step("11. 非法字段校验（超长内容应 400）")
        long_form = dict(form)
        long_form["skills"] = "x" * 2000
        resp = candidate_client.put("/api/resume-form", json=long_form)
        print(f"超长内容 -> {resp.status_code}")
        assert resp.status_code == 400

        print("\n所有端到端验证通过 ✅")
        return 0
    finally:
        step("清理临时数据")
        conn.execute("DELETE FROM admin_users WHERE email = ?", (TEMP_ADMIN_EMAIL,))
        conn.execute("DELETE FROM student_registrations WHERE student_no = ?", (TEST_STUDENT_NO,))
        conn.execute("DELETE FROM users WHERE email LIKE '2024000%@student.local'")
        conn.execute("DELETE FROM resume_form_settings")
        conn.commit()
        conn.close()
        admin_client.close()
        candidate_client.close()
        print("临时管理员、学生与配置已清理")


if __name__ == "__main__":
    sys.exit(main())
