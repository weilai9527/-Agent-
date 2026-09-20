"""端到端验证：用户注册模块 + 候选人三字段登录。

流程：
1. 直接向 SQLite 插入临时管理员账号（scrypt 哈希与后端一致）
2. 管理端登录获取会话 Cookie
3. 构造测试 CSV 并调用导入接口
4. 查询注册列表
5. 候选人端 student-login 登录（正确/错误信息各一次）
6. 验证激活状态回填
7. 清理临时管理员与测试数据
"""
from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from admin_backend.src.security import hash_password  # noqa: E402

import sqlite3  # noqa: E402

DB_PATH = PROJECT_ROOT / "backend" / "data" / "dev.sqlite"
ADMIN_BASE = "http://127.0.0.1:3002"
CANDIDATE_BASE = "http://127.0.0.1:3001"

TEMP_ADMIN_EMAIL = "e2e.tester@multi-agent.local"
TEMP_ADMIN_PASSWORD = "E2eTester#2026"

TEST_ROWS = [
    ("20230001", "张三"),
    ("20230002", "李四"),
    ("20230003", ""),  # 缺姓名，应被跳过
]


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    step("0. 清理可能残留的测试数据")
    conn.execute("DELETE FROM admin_users WHERE email = ?", (TEMP_ADMIN_EMAIL,))
    conn.execute("DELETE FROM student_registrations WHERE student_no LIKE '2023000%'")
    conn.execute("DELETE FROM users WHERE email LIKE '2023000%@student.local'")
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
        resp = admin_client.post("/api/admin/auth/login", json={"email": TEMP_ADMIN_EMAIL, "password": TEMP_ADMIN_PASSWORD})
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        print("登录成功:", resp.json().get("admin", {}).get("email"))

        step("3. 导入 CSV")
        csv_lines = ["学号,姓名"] + [",".join(row) for row in TEST_ROWS]
        csv_content = "\n".join(csv_lines).encode("utf-8-sig")
        resp = admin_client.post(
            "/api/admin/student-registrations/import",
            files={"file": ("students.csv", csv_content, "text/csv")},
            headers={"Origin": "http://127.0.0.1:5174"},
        )
        assert resp.status_code == 200, f"导入失败: {resp.status_code} {resp.text}"
        result = resp.json()
        print(f"导入结果: 新增 {result['imported']}, 更新 {result['updated']}, 跳过 {len(result['skipped'])}")
        assert result["imported"] == 2 and len(result["skipped"]) == 1, "导入计数不符预期"

        step("4. 查询注册列表")
        resp = admin_client.get("/api/admin/student-registrations")
        assert resp.status_code == 200, f"查询失败: {resp.status_code} {resp.text}"
        registrations = resp.json()["registrations"]
        print(f"列表共 {len(registrations)} 条")
        for item in registrations:
            print(f"  - {item['studentNo']} {item['name']} activated={item['activated']}")
        assert len(registrations) == 2

        step("5. 候选人端错误信息登录（应 401）")
        resp = candidate_client.post(
            "/api/auth/student-login",
            json={"studentNo": "20230001", "name": "张四"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        print(f"姓名不匹配 -> {resp.status_code}")
        assert resp.status_code == 401

        step("6. 候选人端正确信息登录（应 200 并激活）")
        resp = candidate_client.post(
            "/api/auth/student-login",
            json={"studentNo": "20230001", "name": "张三"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        user = resp.json().get("user", {})
        print(f"登录成功: {user.get('email')} nickname={user.get('nickname')}")

        step("7. 验证激活状态回填")
        resp = admin_client.get("/api/admin/student-registrations")
        registrations = resp.json()["registrations"]
        activated = {item["studentNo"]: item["activated"] for item in registrations}
        print("激活状态:", activated)
        assert activated.get("20230001") is True and activated.get("20230002") is False

        step("8. 测试重复导入（应更新而非新增）")
        resp = admin_client.post(
            "/api/admin/student-registrations/import",
            files={"file": ("students.csv", csv_content, "text/csv")},
            headers={"Origin": "http://127.0.0.1:5174"},
        )
        result = resp.json()
        print(f"重复导入: 新增 {result['imported']}, 更新 {result['updated']}, 跳过 {len(result['skipped'])}")
        assert result["imported"] == 0 and result["updated"] == 2

        step("9. 测试删除接口")
        target = next(item for item in registrations if item["studentNo"] == "20230002")
        resp = admin_client.delete(
            f"/api/admin/student-registrations/{target['id']}",
            headers={"Origin": "http://127.0.0.1:5174"},
        )
        assert resp.status_code == 200, f"删除失败: {resp.status_code} {resp.text}"
        resp = admin_client.get("/api/admin/student-registrations")
        remaining = resp.json()["registrations"]
        print(f"删除后剩 {len(remaining)} 条")
        assert len(remaining) == 1

        print("\n所有端到端验证通过 ✅")
        return 0
    finally:
        step("清理临时数据")
        conn.execute("DELETE FROM admin_users WHERE email = ?", (TEMP_ADMIN_EMAIL,))
        conn.execute("DELETE FROM student_registrations WHERE student_no LIKE '2023000%'")
        conn.execute("DELETE FROM users WHERE email LIKE '2023000%@student.local'")
        conn.commit()
        conn.close()
        admin_client.close()
        candidate_client.close()
        print("临时管理员与测试注册数据已清理")


if __name__ == "__main__":
    sys.exit(main())
