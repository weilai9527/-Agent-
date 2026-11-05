"""单校本机实例的服务信任清单。键依次为启动进程、接收服务、允许委派的人员角色。
接口变更必须审查此清单；签名授权不以扫描路由、复制用户权限或通配符自动扩张。
"""

SESSION = "identity.session.proxy identity.session.resolve"
DIRECTORY = "identity.classes.read identity.roster.read"
RECORD_SCOPE = "identity.records.scope"
MODEL = {"system": "providers.runtime.read"}
TEXT_USAGE = {"student": "usage.reserve usage.dispatch usage.settle"}
SCHOOL_VIEW = "organization.read student.read roster.import identity.permissions.self " + DIRECTORY
CAREER = (
    "catalog.admin.read catalog.write catalog.publish catalog.import catalog.review "
    "posting.admin.read posting.write posting.sync posting.import posting.delete match.admin.read "
    "jd.read jd.write jd.delete jd.approve program_jobs.read"
)
SCHOOL_INTERVIEW = "interview.records.read interview.templates.read"

GRANTS = {
    "student-gateway": {
        "identity": {"system": SESSION, "student": "identity.student.read"},
        "training": {"student": "training.read training.start"},
        "interview": {
            "student": "interview.read interview.create interview.training.start interview.update interview.start "
            "interview.question.open interview.question.current interview.turn.submit interview.turn.spoken "
            "interview.finish interview.agent.create interview.agent.update interview.message.create "
            "interview.question.followup interview.diagnostics.read interview.diagnostics.write interview.media.context"
        },
        "assessment": {"student": "assessment.read assessment.generate assessment.evaluate"},
        "media": {
            "student": "media.context.sync media.rtc.read media.rtc.token media.rtc.heartbeat media.rtc.start "
            "media.rtc.notify media.rtc.stop media.rtc.caption media.speech.synthesize media.voice.connect "
            "media.video.publish media.recording.start media.recording.stop media.playback.read"
        },
        "profile": {
            "student": "profile.read profile.write profile.upload profile.analyze profile.versions.read"
        },
        "career": {"student": "catalog.read posting.read match.read match.create"},
        "credentials": {"student": "credential.apply credential.read"},
        "analytics": {"student": "analytics.self.read"},
        "operations": {"system": "operations.audit.append"},
    },
    "admin-gateway": {
        "identity": {
            "system": SESSION,
            "teacher": SCHOOL_VIEW,
            "admin": SCHOOL_VIEW
            + " organization.manage student.import student.reset student.status audit.read permissions.manage "
            "staff.profile.write staff.password.reset registration.read registration.import registration.export "
            "registration.status registration.issue registration.reissue",
        },
        "training": {"teacher": "training.read training.assign", "admin": "training.read"},
        "interview": {"teacher": SCHOOL_INTERVIEW, "admin": SCHOOL_INTERVIEW + " interview.policy.manage"},
        "assessment": {
            "teacher": "assessment.records.read assessment.history assessment.export assessment.score assessment.review",
            "admin": "assessment.records.read assessment.export",
        },
        "profile": {
            "teacher": "profile.settings.read profile.student.read",
            "admin": "profile.settings.read profile.settings.write profile.student.read",
        },
        "career": {"teacher": CAREER, "admin": CAREER + " program_jobs.write"},
        "analytics": {
            "teacher": "analytics.teaching.read analytics.practice.assign",
            "admin": "analytics.teaching.read",
        },
        "credentials": {
            "teacher": "credential.read credential.approve credential.issue credential.revoke credential.reissue",
            "admin": "credential.read credential.issue credential.revoke credential.reissue",
        },
        "usage": {"admin": "usage.read usage.configure"},
        "operations": {
            "system": "operations.audit.append",
            "teacher": "operations.rtc.read",
            "admin": "operations.rtc.read operations.audit.read",
        },
    },
    "profile": {
        "identity": {
            "student": "organization.options.read",
            "admin": "profile.settings.read profile.settings.write identity.student.authorize",
            "teacher": "profile.settings.read identity.student.authorize",
        },
        "career": {"student": "catalog.read catalog.enrich catalog.suggest"},
        "providers": MODEL,
    },
    "career": {
        "profile": {"student": "profile.snapshot.read"},
        "identity": {"teacher": "program_jobs.read", "admin": "program_jobs.read program_jobs.write"},
        "providers": MODEL,
    },
    "training": {"identity": {"teacher": DIRECTORY, "admin": DIRECTORY}},
    "interview": {
        "identity": {"student": "identity.student.read", "teacher": RECORD_SCOPE, "admin": RECORD_SCOPE},
        "training": {"student": "training.verify"},
        "profile": {"student": "profile.snapshot.read"},
        "operations": {"student": "operations.rtc.append operations.rtc.self"},
        "providers": MODEL,
    },
    "interview-events": {
        "training": {"system": "training.complete"},
        "assessment": {"system": "assessment.project"},
        "media": {"student": "media.context.sync media.rtc.stop"},
    },
    "assessment": {
        "identity": {
            "student": "identity.student.read",
            "teacher": RECORD_SCOPE + " identity.student.authorize",
            "admin": RECORD_SCOPE + " identity.student.authorize",
        },
        "interview": {"student": "interview.read"},
        "training": {role: "training.verify" for role in ("student", "teacher", "admin")},
        "usage": TEXT_USAGE,
        "providers": MODEL,
    },
    "assessment-jobs": {
        "analytics": {"system": "analytics.completion.write"},
        "usage": TEXT_USAGE,
        "providers": MODEL,
    },
    "media": {"usage": {"student": "usage.reserve usage.settle"}, "providers": MODEL},
    "analytics": {
        "identity": {"teacher": DIRECTORY, "admin": DIRECTORY},
        "training": {"system": "training.verify", "teacher": "training.assign"},
    },
    "credentials": {
        "identity": {"teacher": "identity.student.authorize", "admin": "identity.student.authorize"},
        "training": {role: "training.verify" for role in ("student", "teacher", "admin")},
        "assessment": {
            "student": "assessment.credential-evidence",
            "teacher": "assessment.credential-evidence assessment.credential-authorize",
            "admin": "assessment.credential-evidence assessment.credential-authorize",
        },
        "provenance": {"system": "provenance.read"},
    },
    "credential-relay": {"provenance": {"system": "provenance.submit provenance.read"}},
    "credentials-verifier": {"provenance": {"system": "provenance.read"}},
    "operations": {
        "identity": {"teacher": "identity.operations.scope", "admin": "identity.operations.scope"}
    },
}
