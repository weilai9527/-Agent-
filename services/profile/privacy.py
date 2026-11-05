"""旧版简历处理仅使用运维为本任务明确指定的模型供应商。"""
import os

from fastapi import HTTPException


def external_enabled(order_variable):
    # 通用路由会沿用面试追问的供应商排序；私有简历必须单独授权。
    name = os.environ.get(order_variable, "").strip().lower()
    if not name or name == "local":
        return False
    if name not in {"openai", "qwen", "kimi", "deepseek", "custom"}:
        raise HTTPException(503, "处理私人简历时须明确指定单一供应商或 local。")
    return True
