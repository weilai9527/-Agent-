"""学校登记工作簿。读写均为内存操作，不将学籍材料落到临时文件。"""
import base64
import binascii
import csv
from contextlib import closing
from io import BytesIO, StringIO

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell

from shared.xlsx_safety import check_workbook

# 对应网关 1 MiB JSON 正文限制，预留文件名和 JSON 编码开销。
MAX_FILE = 720 * 1024
HEADERS = {"学号": "student_no", "姓名": "name", "学院": "college", "班级": "class_name",
           "班级编号": "class_id", "性别": "gender", "辅导员": "counselor",
           "账号状态": "source_status", "学生状态": "student_status"}


def read_rows(filename, encoded):
    return read_table(filename, encoded, HEADERS, required={"student_no", "name"})


def read_table(filename, encoded, headers, required, *, all_sheets=False, header_normalizer=str.strip):
    """解析登记或组织工作簿。整批验证表头、行数、单元格类型和包体大小后才允许写库。"""
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix not in {"csv", "xlsx"}:
        raise HTTPException(422, "请上传 .xlsx 或 .csv 文件。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "文件编码无效。") from None
    if len(raw) > MAX_FILE:
        raise HTTPException(413, "文件超过 720 KiB，请分批上传。")
    result = []
    count = 0

    def consume(rows, excel):
        nonlocal count
        first = next(rows, None)
        if first is None and all_sheets:
            return
        names = [str(c.value or "") for c in (first or ())] if excel else list(first or ())
        keys = [headers.get(header_normalizer(name)) for name in names]
        known = [k for k in keys if k]
        if not known or len(keys) > 64 or len(known) != len(set(known)) or not required.issubset(known):
            raise HTTPException(422, "缺少必填表头、列数过多或存在重复列。")
        for line, row in enumerate(rows, 2):
            count += 1
            if count > 4999 or len(row) > 64:
                raise HTTPException(413, "单批最多 4999 行、64 列，请拆分后导入。")
            values = {}
            for key, cell in zip(keys, row):
                if not key:
                    continue
                value = cell.value if excel else cell
                if value is None:
                    continue
                if excel and cell.data_type in {"e", "f"}:
                    raise HTTPException(422, f"第 {line} 行含公式或错误值，请转换为文本。")
                if excel and key == "student_no" and cell.data_type == "n":
                    # 仅恢复能确定的前导零格式，Excel 已经丢失精度的学号不能写入真实账户。
                    if type(value) is not int or value < 0 or value >= 10**15:
                        raise HTTPException(422, f"第 {line} 行学号须使用文本。")
                    fmt = str(cell.number_format)
                    if fmt and len(fmt) <= 40 and set(fmt) == {"0"}:
                        value = str(value).zfill(len(fmt))
                    elif fmt != "General":
                        raise HTTPException(422, f"第 {line} 行学号显示格式不明确，请改用文本。")
                values[key] = str(value).strip()
            if any(values.values()):
                result.append(values)
    try:
        if suffix == "csv":
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            consume(iter(csv.reader(StringIO(text))), False)
        else:
            check_workbook(raw)
            with closing(load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)) as book:
                for sheet in (book.worksheets if all_sheets else [book.active]):
                    consume(sheet.iter_rows(), True)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "无法解析名单文件，请检查编码和表头。") from None
    return result


def export_rows(rows):
    headers = {**HEADERS, "开通状态": "state", "账号可用性": "login_status"}
    book = Workbook(write_only=True)
    sheet = book.create_sheet("学校登记名单")
    sheet.append(list(headers))
    for row in rows:
        # 逐行输出，不反复扫描整张表；以等号开头的姓名与班级同样强制按文本保存。
        cells = [WriteOnlyCell(sheet, value=row.get(key) or "") for key in headers.values()]
        for cell in cells:
            cell.data_type = "s"
        sheet.append(cells)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return {"filename": "学校登记名单.xlsx", "content": base64.b64encode(stream.getvalue()).decode("ascii")}
