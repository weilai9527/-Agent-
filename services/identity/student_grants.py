"""逐学生动作配置；未单独配置时使用学生默认自助动作。"""
import json

# 只列出学生可直接执行的动作。额度预留、班级名册、教学和复核动作留给内部服务与教职员。
STUDENT_SCOPES = frozenset("""
    profile.read profile.write profile.upload profile.analyze profile.versions.read
    catalog.read posting.read match.read match.create
    training.read training.start analytics.self.read credential.apply credential.read
    interview.read interview.create interview.training.start interview.update interview.start interview.question.open
    interview.question.current interview.turn.submit interview.turn.spoken interview.finish
    interview.agent.create interview.agent.update interview.message.create interview.question.followup
    assessment.read assessment.generate assessment.evaluate
    interview.diagnostics.read interview.diagnostics.write
    media.rtc.read media.rtc.token media.rtc.heartbeat media.rtc.start media.rtc.notify
    media.rtc.stop media.rtc.caption media.speech.synthesize media.voice.connect media.voice.disconnect
    media.video.publish media.recording.start media.recording.stop media.playback.read
""".split())

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS identity_student_grants (
       school_id VARCHAR(128) NOT NULL, actor_id VARCHAR(128) NOT NULL,
       revision BIGINT NOT NULL, scopes TEXT NOT NULL, PRIMARY KEY (school_id,actor_id),
       FOREIGN KEY (school_id,actor_id) REFERENCES identity_student_credentials(school_id,actor_id)
       ON DELETE CASCADE
    )""",
)


def current(tx, ids):
    row = tx.one("SELECT scopes,revision FROM identity_student_grants WHERE school_id=? AND actor_id=?", ids)
    if row is None:
        return 0, STUDENT_SCOPES
    # 非法配置按拒绝处理；已撤销的服务动作不能借助旧记录继续获得授权。
    try:
        stored = json.loads(row["scopes"])
        if not isinstance(stored, list) or not all(isinstance(action, str) for action in stored):
            stored = []
    except (TypeError, ValueError):
        stored = []
    return row["revision"], STUDENT_SCOPES.intersection(stored)


def response(ids, revision, scopes):
    return {"school_id": ids[0], "student_id": ids[1], "configured": revision != 0, "revision": revision,
            "available_scopes": sorted(STUDENT_SCOPES), "scopes": sorted(scopes)}
