"""从已核验学校的只读快照复制旧表单配置。已有原生版本时不覆盖。"""

import json

from . import settings_store


def copy_from_reader(reader, engine, db, school):
    from services.career.migrate import assert_school, columns

    table = "resume_form_settings"
    fields = columns(reader, engine, table)
    assert_school(reader, engine, None, school)
    if not fields:
        return None
    if not {"id", "colleges", "updated_at"}.issubset(fields):
        raise ValueError("旧简历表单配置缺少必需字段。")
    # 旧管理端读取最后一次保存的整张配置，时间相同时以主键排序确保重跑稳定。
    row = reader.one("SELECT colleges FROM resume_form_settings ORDER BY updated_at DESC,id DESC LIMIT 1")
    if not row:
        return None
    try:
        values = json.loads(row["colleges"])
        if not isinstance(values, list):
            raise ValueError()
        # 旧编辑器曾允许数字编号和同名项。保留管理员看到的顺序与内容；
        # 候选人读取时才按名称合并重复项，新编辑则必须通过完整的去重校验。
        colleges = settings_store.normalize(values, manual=False, legacy_ids=True)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("旧简历表单配置无效，请修复来源数据后重试。") from None
    settings_store.ensure_schema(db)
    imported = settings_store.replace(db, school, "legacy-import", colleges, import_only=True)
    return "imported" if imported else "already_present"
