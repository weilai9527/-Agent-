"""在临时学校部署上验证原生浏览器网关路径。

在仓库根目录执行 python -m services.training.check_native_workbench。
验证使用隔离测试库、固定模型和本机回环服务地址。
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from scripts import smoke_microservices as smoke


def exercise(deployment, stack):
    def browser(service):
        origin = deployment.urls[service]
        return stack.enter_context(httpx.Client(base_url=origin, headers={"Origin": origin},
                                                timeout=15, trust_env=False))

    manager = browser("admin-gateway")
    teacher = browser("admin-gateway")
    colleague = browser("admin-gateway")
    call = smoke.call
    call(manager, "POST", "/api/admin/auth/login", {
        "email": smoke.MASTER, "password": deployment.master_env["ADMIN_MASTER_PASSWORD"]})
    for client, name in ((teacher, "owner"), (colleague, "coworker")):
        call(client, "POST", "/api/admin/auth/login", {
            "email": name + "@example.test", "password": smoke.TEACHER_PASSWORD})
    snapshot = call(teacher, "GET", "/api/admin/snapshot")
    assert snapshot["identityMode"] == "native"
    assert {"training.read", "analytics.teaching.read"} <= set(snapshot["admin"]["permissions"])

    students = []
    for number in ("S1011", "S1012"):
        initial = "Temporary-Only-7-Student!"
        imported = call(manager, "POST", "/api/admin/identity/students/import", {
            "students": [{"name": number, "student_no": number, "temporary_password": initial}]})
        call(manager, "POST", "/api/admin/identity/v1/classes/cls/roster/import",
             {"student_ids": [imported["students"][0]["actor_id"]]})
        client = browser("student-gateway")
        call(client, "POST", "/api/auth/login", {"student_no": number, "password": initial})
        call(client, "POST", "/api/auth/change-initial-password",
             {"password": smoke.PASSWORD, "confirm_password": smoke.PASSWORD})
        students.append(client)

    learner, peer = students
    workbench = "/api/admin/training/tasks?view=workbench"
    analytics = "/api/admin/analytics/v1/teaching/"
    task = call(teacher, "POST", "/api/admin/training/tasks", {
        "class_ids": ["cls"], "title": "Transactions", "job_role": "Engineer",
        "questions": [{"question_id": "q1", "prompt": "Explain a row lock."}], "max_attempts": 1,
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    counts = call(teacher, "GET", workbench)["summary"]
    assert (counts["assigned_task_students"], counts["completed_task_students"]) == (2, 0)
    assert not call(colleague, "GET", workbench)["items"]
    attempt = call(learner, "POST", f"/api/training/tasks/{task['task_id']}/attempts", {"request_id": "one"})
    opened = call(learner, "POST", "/api/interviews/training-attempts/" + attempt["attempt_id"], {})
    iid = opened["interview_id"]
    path = "/api/interviews/" + iid
    question = call(learner, "POST", path + "/current-question", {})["question"]
    call(learner, "POST", path + "/turns",
         {"question_id": question["id"], "submission_id": "one", "content": smoke.ANSWER})
    call(learner, "POST", path + "/finish", {})

    def scored():
        # 历史页使用同一列表，报告页按面试标识打开详情。两页都从登录身份取得学生标识。
        rows = call(learner, "GET", "/api/reports")["reports"]
        return next((r for r in rows if r["interview_id"] == iid and r["generation_status"] == "succeeded"), None)

    history = smoke.until("student's scored report in history", scored)
    rid = history["id"]
    assert iid in {r["id"] for r in call(learner, "GET", "/api/interviews")["interviews"]}
    assert call(learner, "GET", path + "/report")["report"]["id"] == rid
    assert call(learner, "GET", "/api/reports/" + rid)["report"]["interview_id"] == iid
    assert not call(peer, "GET", "/api/reports")["reports"]
    assert not call(peer, "GET", "/api/interviews")["interviews"]
    call(peer, "GET", "/api/reports/" + rid, ok=(403, 404))
    call(peer, "GET", path + "/report", ok=(403, 404))

    weak = smoke.until("completed assessment visible to its teacher",
                       lambda: call(teacher, "GET", analytics + "weaknesses")["items"])
    assert [(r["question_id"], r["interview_id"], r["original_answer"]) for r in weak] == [("q1", iid, smoke.ANSWER)]
    ref_path = "/api/admin/interviews/" + iid + "/report-reference"
    assert call(teacher, "GET", ref_path)["report_id"] == rid
    call(colleague, "GET", ref_path, ok=(403, 404))
    assert not call(colleague, "GET", analytics + "weaknesses")["items"]
    summary = call(teacher, "GET", analytics + "summary")
    assert (summary["attempts"], summary["valid_attempts"], summary["insufficient_attempts"]) == (1, 1, 0)
    assert summary["class_weaknesses"][0]["affected_students"] == 1
    counts = call(teacher, "GET", workbench)["summary"]
    assert (counts["assigned_task_students"], counts["completed_task_students"]) == (2, 1)
    print("PASS: native staff dashboard 1/2 complete, one fully scored attempt, frozen original question; "
          "native student history and detail share the report ID, peer and colleague denied", flush=True)


def main():
    # 公共冒烟测试仅给学生网关提交权限，此场景额外验证常规的面试历史读取权限。
    smoke.EDGES["student-gateway"]["interview"]["student"] += " interview.read"
    with TemporaryDirectory(prefix="native-workbench-") as folder, ExitStack() as stack:
        root = Path(folder)
        smoke.prepare_sources(root)
        deployment = smoke.Deployment(root, stack, "isolated")
        deployment.launch()
        exercise(deployment, stack)


if __name__ == "__main__":
    main()
