"""证书域和评估域共用的申请与证据标识算法。"""
import hashlib
import json


def application_id(school_id, student_id, report_id, version):
    reference = ["credential-application/v1", school_id, student_id, report_id, version]
    return hashlib.sha256(json.dumps(reference, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
