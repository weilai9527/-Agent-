"""在学校暂停写入期间，将历史报告和证据加入迁移队列，账号留在源库。"""
import re
from datetime import datetime

from fastapi import HTTPException

from services.interview.assessment_events import digest, fetch_rows
from shared.credential_reference import application_id


HISTORY = {
    "interview_evaluations": "id interview_id message_id agent_id score strengths issues suggestions dimension_scores dimension_evidence provider model prompt_version generation_status generation_error fallback generated_at review_status reviewed_by reviewed_at created_at updated_at",
    "interview_reports": "id user_id interview_id total_score scored_answer_count answer_count grade pass_recommendation ability_radar agent_feedback timeline_review summary suggestions provider model prompt_version generation_status generation_error fallback generated_at review_status reviewed_by reviewed_at created_at updated_at",
    "assessment_resume_snapshots": "interview_id analysis_json",
    "assessment_evidence_heads": "interview_id digest revision",
    "assessment_report_versions": "report_id version evidence_version source actor_id reason snapshot created_at",
    "assessment_report_reviews": "id report_id version sequence_no status actor_id note created_at",
}


PERMITS = "assessment_issuance_permits"
PERMIT_COLUMNS = ("report_id", "application_id", "generation", "serial", "version", "digest",
                  "proof_digest", "authorized_by", "school_id", "authorized_at")


def _table_exists(legacy, table):
    if legacy.DB_ENGINE == "mysql":
        query = "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?"
    else:
        query = "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?"
    return legacy.one(query, (table,)) is not None


def load_history(legacy, interview):
    report = legacy.one("SELECT id FROM interview_reports WHERE interview_id=?", (interview,))
    result = {}
    for table, columns in HISTORY.items():
        by_report = table in {"assessment_report_versions", "assessment_report_reviews"}
        owner = "report_id" if by_report else "interview_id"
        key = report["id"] if by_report and report else interview
        ordering = {"assessment_report_versions": "version", "assessment_report_reviews": "version,sequence_no",
                    "interview_evaluations": "id"}.get(table, owner)
        result[table] = (fetch_rows(legacy.db, f"SELECT {','.join(columns.split())} FROM {table} WHERE {owner}=? ORDER BY {ordering}",
                                    (key,)) if not by_report or report else [])
    # 如果源库早于签发许可功能，或当前报告没有许可，保留原清单的字节内容，
    # 使其仍能匹配已经持久化的导入摘要。
    if report and _table_exists(legacy, PERMITS):
        permits = fetch_rows(legacy.db, f"SELECT {','.join(PERMIT_COLUMNS)} FROM {PERMITS} "
                             "WHERE report_id=? ORDER BY application_id,generation", (report["id"],))
        if permits:
            result[PERMITS] = permits
    return result


def restore_permits(legacy, interview, student, report, school, permits):
    if not isinstance(permits, list):
        raise HTTPException(422, "Invalid issuance permit manifest")
    generations = {}
    serials = set()
    for row in permits:
        if (not isinstance(row, dict) or set(row) != set(PERMIT_COLUMNS)
                or row["report_id"] != report or row["school_id"] != school
                or type(row["generation"]) is not int or not 1 <= row["generation"] <= 2147483647
                or type(row["version"]) is not int or row["version"] < 1
                or row["application_id"] != application_id(school, student, report, row["version"])
                or not isinstance(row["authorized_by"], str) or not row["authorized_by"].strip()
                or not isinstance(row["serial"], str) or not re.fullmatch(r"[a-f0-9]{32}", row["serial"])
                or not isinstance(row["proof_digest"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["proof_digest"])):
            raise HTTPException(409, "Invalid issuance permit binding")
        previous_generation = generations.get(row["application_id"], 0)
        if row["generation"] != previous_generation + 1 or row["serial"] in serials:
            raise HTTPException(409, "Out-of-sequence or duplicate issuance permit")
        generations[row["application_id"]] = row["generation"]
        serials.add(row["serial"])
        # 签发许可提交时已绑定当时的不可变报告版本。若与最新版本比较，
        # 改分后就会丢弃原有的有效许可。
        revision = legacy.one("""SELECT evidence_version,source,actor_id,reason,snapshot
                                 FROM assessment_report_versions WHERE report_id=? AND version=?""",
                              (report, row["version"]))
        if revision is None or row["digest"] != digest({
            **revision, "report_id": report, "student_id": student, "school_id": school,
            "interview_id": interview, "version": row["version"],
        }):
            raise HTTPException(409, "Issuance permit does not match its historical evidence")
        existing = legacy.one(f"SELECT {','.join(PERMIT_COLUMNS)} FROM {PERMITS} "
                              "WHERE serial=? OR (report_id=? AND application_id=? AND generation=?)",
                              (row["serial"], report, row["application_id"], row["generation"]))
        if existing:
            if isinstance(existing["authorized_at"], datetime):
                existing["authorized_at"] = existing["authorized_at"].isoformat(sep=" ")
            if existing != row:
                raise HTTPException(409, "Conflicting historical issuance permit")
            continue
        legacy.db.execute(f"INSERT INTO {PERMITS} ({','.join(PERMIT_COLUMNS)}) "
                          f"VALUES ({','.join('?' for _ in PERMIT_COLUMNS)})",
                          tuple(row[key] for key in PERMIT_COLUMNS)).close()


def restore_history(legacy, interview, student, report, school, history):
    if not isinstance(history, dict) or set(history) - {PERMITS} != set(HISTORY):
        raise HTTPException(422, "Invalid historical manifest")
    for table, columns in HISTORY.items():
        for row in history[table]:
            if (not isinstance(row, dict) or set(row) != set(columns.split())
                    or row.get("report_id", report) != report or row.get("interview_id", interview) != interview
                    or row.get("user_id", student) != student
                    or (table == "interview_reports" and row["id"] != report)):
                raise HTTPException(409, "Conflicting historical record")
            if table == "interview_evaluations":
                if not legacy.find_message_by_interview_id(row["message_id"], interview):
                    raise HTTPException(409, "Historical evaluation has no owned answer")
                if row["agent_id"] and not legacy.find_agent_by_interview_id(row["agent_id"], interview):
                    raise HTTPException(409, "Historical evaluation has no owned agent")
            legacy.db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
                              tuple(row.values())).close()
    restore_permits(legacy, interview, student, report, school, history.get(PERMITS, []))


if __name__ == "__main__":
    # 保留旧迁移命令的入口，但必须显式提供只读快照和对应的面试专库。
    from services.interview.migration import main
    main()
