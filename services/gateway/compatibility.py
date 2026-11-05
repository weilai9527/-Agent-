"""兼容现有浏览器路径；所有列出的动作均由对应原生业务服务处理。"""


def compatibility_routes(staff):
    if staff:
        base = "/api/admin/reports/{report_id}"
        return {"assessment": [
            ("GET", "/api/admin/interviews/{interview_id}/report-reference", "assessment.history", True),
            ("GET", base + "/history", "assessment.history", True),
            ("GET", base + "/export", "assessment.export", False),
            ("PATCH", base + "/score", "assessment.score", True),
            ("PATCH", base + "/review", "assessment.review", True),
        ]}
    base = "/api/interviews/{interview_id}"
    return {
        "interview": [
            ("POST", "/api/interviews/training-attempts/{attempt_id}", "interview.training.start", True),
            ("GET", "/api/interviews", "interview.read", False),
            ("POST", "/api/interviews", "interview.create", False),
            ("GET", base, "interview.read", False),
            ("PATCH", base, "interview.update", False),
            ("POST", base + "/start", "interview.start", False),
            ("POST", base + "/opening-question", "interview.question.open", False),
            ("POST", base + "/current-question", "interview.question.current", False),
            ("POST", base + "/turns", "interview.turn.submit", False),
            ("POST", base + "/turns/{submission_id}/spoken-question", "interview.turn.spoken", False),
            ("POST", base + "/finish", "interview.finish", False),
            ("GET", base + "/agents", "interview.read", False),
            ("POST", base + "/agents", "interview.agent.create", False),
            ("PATCH", base + "/agents/{agent_id}", "interview.agent.update", False),
            ("GET", base + "/messages", "interview.read", False),
            ("POST", base + "/messages", "interview.message.create", False),
            ("POST", base + "/follow-up", "interview.question.followup", False),
        ],
        "assessment": [
            ("GET", "/api/stats/me", "assessment.read", False),
            ("GET", "/api/stats/me/dimensions", "assessment.read", False),
            ("GET", base + "/evaluations", "assessment.read", False),
            ("POST", base + "/evaluations", "assessment.evaluate", False),
            ("GET", base + "/report", "assessment.read", False),
            ("GET", base + "/report/download", "assessment.read", False),
            ("POST", base + "/report", "assessment.generate", False),
            ("GET", "/api/reports", "assessment.read", False),
            ("GET", "/api/reports/{report_id}", "assessment.read", False),
        ],
    }
