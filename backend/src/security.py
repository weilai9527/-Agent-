"""离线学生夹具的兼容导出。正式认证实现位于 shared.account_security。"""
from shared.account_security import (
    PASSWORD_KEY_LENGTH, create_token, hash_password, hash_student_token as hash_token, is_valid_email,
    is_valid_student_no, normalize_email, normalize_student_no, verify_password,
)


def sanitize_user(user: dict | None) -> dict | None:
    if not user:
        return None

    return {
        "id": user["id"],
        "email": user.get("email"),
        "studentNo": user.get("student_no"),
        "name": user["name"],
        "status": user["status"],
        "college": user.get("college"),
        "className": user.get("class_name"),
        "counselor": user.get("counselor"),
        "studentStatus": user.get("student_status"),
        "mustChangePassword": bool(user.get("must_change_password")),
        "createdAt": user["created_at"],
        "lastLoginAt": user["last_login_at"],
    }
