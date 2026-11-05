"""面试场次和问答回合接口，在访问持久化记录前验证服务身份。"""
import os

from fastapi import Depends, FastAPI, HTTPException, Request

from starlette.concurrency import run_in_threadpool

from services.assessment.storage_mode import isolated

from shared.runtime_mode import require_native_runtime

# 在初始化专库前拦截受限配置，直接 ASGI 启动也遵守同一部署边界。
require_native_runtime()

if isolated() and os.environ.get("SERVICE_ID") != "interview":
    raise RuntimeError("Isolated interview API requires SERVICE_ID=interview")

from . import runtime
from shared.service_http import request_json, resource_segment
from . import policy_admin, training_rounds
from .student_reference import resolve_student
from shared.service_security import require_service
from services.school_records import school_record_router

app = FastAPI(title="Interview service")
app.include_router(school_record_router("interview"))
app.include_router(policy_admin.router)
from .template_usage import router as templates_router
app.include_router(templates_router)


def authenticate_student(scope):
    async def bind_student(request: Request, actor=Depends(require_service("interview", scope))):
        request.state.interview_student = await resolve_student(actor)
        request.state.interview_actor = actor
    return bind_student


def current_student(request: Request):
    return request.state.interview_student


# 各路由先检查调用方获准代办的动作，再解析学生身份。
# 处理请求时用同一学生标识核验面试归属。
app.dependency_overrides[runtime.require_auth] = current_student
app.add_api_route("/api/interviewer-policy", runtime.get_interviewer_policy, methods=["GET"],
                  dependencies=[Depends(authenticate_student("interview.read"))])


@app.get("/internal/interviews/{interview_id}/media-context",
         dependencies=[Depends(authenticate_student("interview.media.context"))])
def media_context(interview_id: str, request: Request):
    from services.media.gateway import make_snapshot

    user = request.state.interview_student
    actor = request.state.interview_actor
    # 在同一把会话锁下读取本回合的数据。发布快照期间，面试可能结束或切换角色。
    # 媒体服务收到新快照后会拒绝晚到的旧快照。
    with runtime.locked_session(interview_id, user["id"]) as session:
        if not session or session["id"] != interview_id:
            raise HTTPException(404, "Interview not found")
        interview = runtime.find_interview_by_user_id(interview_id, user["id"])
        agents = runtime.list_agents_by_interview_id(interview_id)
        messages = runtime.list_messages_by_interview_id(interview_id)
        frozen = runtime.profile_context.load(interview_id)
    context = make_snapshot(interview, agents, messages, user_name=user["name"],
                            analysis=frozen["analysis"] if frozen else None)
    return {"interview_id": interview_id, "student_id": user["id"], "school_id": actor["school_id"],
            "context": context}


def route(method, path, endpoint, scope, *, status_code=200):
    app.add_api_route("/api/interviews" + path, endpoint, methods=[method], status_code=status_code,
                      dependencies=[Depends(authenticate_student(scope))])


route("GET", "", runtime.list_interviews, "interview.read")
route("POST", "", runtime.create_interview, "interview.create", status_code=201)
route("GET", "/{interview_id}", runtime.get_interview, "interview.read")
route("PATCH", "/{interview_id}", runtime.update_interview, "interview.update")
route("POST", "/{interview_id}/start", runtime.start_interview, "interview.start")
route("POST", "/{interview_id}/opening-question", runtime.create_opening_question, "interview.question.open")
route("POST", "/{interview_id}/current-question", runtime.current_question, "interview.question.current")
route("POST", "/{interview_id}/turns", runtime.submit_turn, "interview.turn.submit")
route("POST", "/{interview_id}/turns/{submission_id}/spoken-question", runtime.save_spoken_question, "interview.turn.spoken")
route("POST", "/{interview_id}/finish", runtime.finish_interview, "interview.finish")
route("GET", "/{interview_id}/agents", runtime.list_agents, "interview.read")
route("POST", "/{interview_id}/agents", runtime.create_agent, "interview.agent.create", status_code=201)
route("PATCH", "/{interview_id}/agents/{agent_id}", runtime.update_agent, "interview.agent.update")
from services.operations.interview_bridge import mount as mount_rtc_diagnostics
mount_rtc_diagnostics(app, authenticate_student, runtime.find_interview_by_user_id)
route("GET", "/{interview_id}/messages", runtime.list_messages, "interview.read")
route("POST", "/{interview_id}/messages", runtime.create_message, "interview.message.create", status_code=201)
route("POST", "/{interview_id}/follow-up", runtime.generate_follow_up, "interview.question.followup")

@app.post("/api/interviews/training-attempts/{attempt_id}",
          dependencies=[Depends(authenticate_student("interview.training.start"))])
async def training_interview(attempt_id: str, request: Request):
    actor = request.state.interview_actor
    record = await request_json("training", "GET", "/attempts/" + resource_segment(attempt_id),
                                actor=actor, scope="training.verify")
    interview_id = await run_in_threadpool(training_rounds.materialize, attempt_id, record,
                                           actor["actor_id"], actor["school_id"],
                                           native_verified=request.state.interview_student.get("_native") is True)
    interview = await run_in_threadpool(runtime.find_interview_by_user_id, interview_id, actor["actor_id"])
    return {"attempt_id": attempt_id, "interview_id": interview_id, "interview": interview}
