"""招聘岗位表格的历史列名、别名与导入导出格式。"""
import io
import re
from typing import Any

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from shared.career_catalog import _all, list_versions
from shared.recruitment import upsert_job_posting_by_source


JOB_POSTING_EXPORT_COLUMNS = [
    ("title", "岗位名称"),
    ("company", "公司"),
    ("job_category", "岗位类别"),
    ("city", "工作地点"),
    ("graduation_year", "届次"),
    ("employment_type", "招聘类型"),
    ("salary", "薪资范围"),
    ("education_requirement", "学历要求"),
    ("experience_requirement", "经验要求"),
    ("headcount", "招聘人数"),
    ("deadline", "截止时间"),
    ("skills", "技能要求"),
    ("tags", "标签"),
    ("description", "岗位描述"),
    ("requirements", "任职要求"),
    ("catalog_job_name", "关联标准岗位"),
    ("status", "状态"),
    ("source_ref", "外部编号"),
]

JOB_POSTING_IMPORT_ALIASES = {
    "岗位名称": "title", "岗位": "title", "招聘岗位": "title", "职位名称": "title", "职位": "title",
    "公司": "company", "公司名称": "company", "企业名称": "company", "招聘公司": "company",
    "岗位类别": "job_category", "职位类别": "job_category", "岗位方向": "job_category",
    "类别": "job_category", "岗位分类": "job_category", "职业类别": "job_category", "职位分类": "job_category",
    "工作地点": "city", "城市": "city", "地点": "city", "工作城市": "city", "所在城市": "city", "地区": "city",
    "届次": "graduation_year", "毕业届次": "graduation_year", "招聘届次": "graduation_year",
    "招聘类型": "employment_type", "用工类型": "employment_type", "职位类型": "employment_type",
    "薪资": "salary", "薪资范围": "salary", "月薪": "salary", "待遇": "salary",
    "学历要求": "education_requirement", "学历": "education_requirement",
    "经验要求": "experience_requirement", "工作经验": "experience_requirement",
    "招聘人数": "headcount", "人数": "headcount",
    "截止时间": "deadline", "截止日期": "deadline", "招聘截止": "deadline", "有效期": "deadline",
    "技能要求": "skills", "技能": "skills", "技术栈": "skills",
    "标签": "tags",
    "岗位描述": "description", "岗位职责": "description", "职位描述": "description", "工作内容": "description",
    "任职要求": "requirements", "岗位要求": "requirements", "任职资格": "requirements",
    "关联标准岗位": "catalog_job_name", "标准岗位": "catalog_job_name",
    "状态": "status",
    "外部编号": "source_ref", "编号": "source_ref", "岗位编号": "source_ref",
}


def _normalize_import_label(label: str) -> str:
    """去掉表头中的空白与不可见字符，避免 Excel 里看不见的字符导致列识别失败。"""
    return re.sub(r"[\s\u200b\u200c\u200d\ufeff\u00a0]+", "", str(label or ""))


def published_job_roles(db) -> dict[str, dict]:
    versions = list_versions(db, include_drafts=False)
    if not versions:
        return {}
    version_id = versions[0]["id"]
    rows = _all(db,
        "SELECT id, code, name FROM catalog_job_roles WHERE version_id = ? AND enabled = 1",
        (version_id,),
    )
    return {str(row["name"]).strip(): {"id": row["id"], "code": row["code"], "name": row["name"]} for row in rows}


def build_job_posting_workbook(rows: list[dict], *, template: bool = False) -> io.BytesIO:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "招聘信息库"
    headers = [label for _field, label in JOB_POSTING_EXPORT_COLUMNS]
    worksheet.append(headers)
    header_fill = PatternFill("solid", fgColor="17324D")
    for cell in worksheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_index, row in enumerate(rows, start=2):
        worksheet.append([
            (row.get("status") == "active" and "启用") or ("停用" if row.get("status") == "disabled" else (row.get("status") or ""))
            if field == "status"
            else (row.get(field) if row.get(field) is not None else "")
            for field, _label in JOB_POSTING_EXPORT_COLUMNS
        ])

        for cell in worksheet[row_index]:
            if cell.data_type == "f":
                cell.data_type = "s"

    widths = [24, 20, 16, 14, 10, 12, 14, 12, 12, 10, 14, 26, 18, 40, 40, 18, 10, 16]
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[chr(64 + index)].width = width
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    if template:
        notes = workbook.create_sheet("填写说明")
        notes.append(["字段", "是否必填", "说明"])
        for cell in notes[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
        for field, label in JOB_POSTING_EXPORT_COLUMNS:
            required = "是" if field == "title" else "否"
            hint = {
                "title": "招聘岗位名称，必填。",
                "skills": "多个技能用中文逗号、或顿号分隔。",
                "description": "岗位职责/工作内容，可多行。",
                "requirements": "任职要求，建议每行一条，便于逐条对比。",
                "catalog_job_name": "可选，填写岗位知识库中已发布的标准岗位名称即可自动关联。",
                "status": "填“启用”或“停用”，默认启用。",
                "source_ref": "外部唯一编号；相同编号再次导入会更新原记录，留空则按“岗位名称+公司”去重。",
            }.get(field, "")
            if hint:
                notes.append([label, required, hint])
        notes.column_dimensions["A"].width = 18
        notes.column_dimensions["B"].width = 10
        notes.column_dimensions["C"].width = 80

    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def evaluate_job_posting_import(db, content: bytes) -> dict[str, Any]:
    try:
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise HTTPException(400, "无法解析 Excel 文件。") from exc

    worksheet = workbook.worksheets[0] if workbook.worksheets else None
    if worksheet is None:
        raise HTTPException(400, "Excel 中没有可读取的工作表。")

    rows = worksheet.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration:
        raise HTTPException(400, "Excel 内容为空。")

    field_by_index: dict[int, str] = {}
    for index, cell in enumerate(header_row or []):
        label = str(cell or "").strip()
        field = JOB_POSTING_IMPORT_ALIASES.get(label) or JOB_POSTING_IMPORT_ALIASES.get(_normalize_import_label(label))
        if field:
            field_by_index[index] = field
    if "title" not in field_by_index.values():
        raise HTTPException(400, "Excel 缺少“岗位名称”列，请参考导入模板。")

    job_roles = published_job_roles(db)
    result = {"total": 0, "created": 0, "updated": 0, "skipped": 0, "errors": []}
    for row_number, raw_row in enumerate(rows, start=2):
        if raw_row is None:
            continue
        payload: dict[str, Any] = {}
        for index, field in field_by_index.items():
            if index >= len(raw_row):
                continue
            value = raw_row[index]
            if value is None:
                continue
            payload[field] = value if field == "headcount" else str(value).strip()
        if not str(payload.get("title") or "").strip():
            result["skipped"] += 1
            continue

        result["total"] += 1
        catalog_name = str(payload.pop("catalog_job_name", "") or "").strip()
        if catalog_name:
            matched = job_roles.get(catalog_name)
            if matched:
                payload["catalog_job_role_id"] = matched["id"]
                payload["catalog_job_name"] = matched["name"]
            else:
                payload["catalog_job_role_id"] = None
                payload["catalog_job_name"] = catalog_name

        status_label = str(payload.get("status") or "").strip()
        if status_label:
            payload["status"] = "active" if status_label in {"启用", "正常", "active", "有效"} else "disabled"

        source_ref = str(payload.get("source_ref") or "").strip()
        if not source_ref:
            source_ref = f"{payload.get('title')}|{payload.get('company') or ''}"
        payload["source_ref"] = source_ref

        try:
            _posting, action = upsert_job_posting_by_source(
                db,
                payload,
                source="excel",
                source_ref=source_ref,
            )
            result["created" if action == "created" else "updated"] += 1
        except ValueError as exc:
            result["skipped"] += 1
            if len(result["errors"]) < 20:
                result["errors"].append(f"第 {row_number} 行：{exc}")
    return result
