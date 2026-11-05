"""在学生网关挂载原生会话、档案和招聘接口。数据和权限均以所属服务为准。"""
from fastapi import HTTPException

from services.career.candidate import router as career_router
from services.career.limits import BodyLimit as CareerBodyLimit
from services.identity.candidate_adapter import mount_candidate_auth
from services.identity.gateway import session_mode
from services.profile.candidate import router as profile_router
from services.profile.limits import BodyLimit as ProfileBodyLimit


def _legacy_unavailable(*_):
    # 共用路由为离线夹具保留了登录、院系选项和姓名回写回调。原生权限由身份服务核验，
    # 院系选项由档案服务合并；触及任一旧回调时终止请求，不用空目录伪装故障。
    raise HTTPException(503, "原生学生入口不能访问应急账户数据。")


def mount_native_account(app):
    if session_mode() != "native":
        raise RuntimeError("学生网关需要原生身份会话。")
    app.add_middleware(ProfileBodyLimit, profile_only=True)
    app.add_middleware(CareerBodyLimit, browser_student_only=True)
    mount_candidate_auth(app)
    app.include_router(profile_router(auth=_legacy_unavailable, form_settings=_legacy_unavailable, update_name=_legacy_unavailable))
    app.include_router(career_router(_legacy_unavailable))
