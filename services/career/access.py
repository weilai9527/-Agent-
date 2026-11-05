"""先校验调用服务、学校与动作权限，再读取租户数据或私有对象。"""
from fastapi import Depends, HTTPException
from shared.service_security import require_service
from .store import school_store


def actor(scope, roles=("admin", "teacher")):
    def check(identity=Depends(require_service("career", scope))):
        if identity["actor_type"] not in roles:
            raise HTTPException(403, "Actor cannot perform this career action")
        school_store(identity["school_id"])
        return identity
    return Depends(check)


def found(value):
    if value is None or value is False:
        raise HTTPException(404, "记录不存在。")
    return value
