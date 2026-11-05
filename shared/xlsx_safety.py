"""在 openpyxl 解析前检查压缩包、XML 大小以及稀疏工作表的行列边界。"""
import io
import re
from zipfile import BadZipFile, ZipFile
from xml.parsers import expat

from fastapi import HTTPException
from openpyxl.utils.cell import column_index_from_string


def check_reference(ref):
    for cell in ref.split(":"):
        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,5})", cell)
        if not match or column_index_from_string(match[1]) > 64 or int(match[2]) > 5000:
            raise ValueError("Worksheet dimensions exceed import limits")


def check_xml(stream):
    # 使用 Expat 回调在展开实体前拒绝 DTD，并流式核对声明范围和实际单元格坐标。
    parser = expat.ParserCreate(namespace_separator="}")
    row_count = cell_count = 0

    def reject_doctype(*args):
        raise ValueError("DTD not permitted")

    def element(tag, attrs):
        nonlocal row_count, cell_count
        local = tag.rsplit("}", 1)[-1]
        if local == "dimension" and "ref" in attrs:
            check_reference(attrs["ref"])
        elif local == "row":
            row_count += 1
            cell_count = 0
            if row_count > 5000 or not 1 <= int(attrs.get("r", row_count)) <= 5000:
                raise ValueError("Row exceeds import limits")
        elif local == "c":
            cell_count += 1
            if cell_count > 64:
                raise ValueError("Column exceeds import limits")
            if "r" in attrs:
                check_reference(attrs["r"])


    parser.StartDoctypeDeclHandler = reject_doctype
    parser.StartElementHandler = element
    parser.ParseFile(stream)


def check_workbook(data):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 200 or sum(m.file_size for m in members) > 16 * 1024 * 1024:
                raise ValueError("Expanded workbook exceeds import limits")
            seen = set()
            for member in members:
                name = member.filename.lower()
                if name in seen:
                    raise ValueError("Duplicate ZIP member")
                seen.add(name)
                if member.is_dir():
                    continue
                # 只导入表格 OOXML，避免构造关系引用将二进制附件伪装成工作表。
                if not name.endswith((".xml", ".rels")):
                    raise ValueError("Unsupported workbook attachment")
                with archive.open(member) as stream:
                    check_xml(stream)
    except (BadZipFile, ValueError, KeyError, OSError, RuntimeError, expat.ExpatError):
        raise HTTPException(400, "Excel 文件无效或超出导入限制。") from None
    return data
