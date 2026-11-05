"""职业目录上传文件的扩展名和体积验证；通用 OOXML 安全规则与学校名单共用。"""
from fastapi import HTTPException
from shared.xlsx_safety import check_workbook


def read_workbook(upload, byte_limit):
    if not (upload.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "请上传 .xlsx 工作簿。")
    data = upload.file.read(byte_limit + 1)
    if len(data) > byte_limit:
        raise HTTPException(413, "工作簿超过大小限制。")
    check_workbook(data)
    return data
