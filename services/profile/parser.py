"""在本机限量解析上传的简历，二进制文档在独立子进程中处理。"""

import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile


MAX_FILE = 10 * 1024 * 1024
MAX_TEXT = 12000
MAX_PIXELS = 20_000_000
_PARSE_SLOTS = threading.BoundedSemaphore(2)


def docx_text(data):
    # 仅解析 Word 正文，不加载外部关系、宏、图片或嵌入对象。
    with ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 1024 or sum(i.file_size for i in entries) > 40 * 1024 * 1024:
            raise ValueError
        part = archive.getinfo("word/document.xml")
        if part.file_size > 5 * 1024 * 1024:
            raise ValueError
        xml = archive.read(part)
    # 在 XML 解析器中拒绝 DTD，覆盖不同编码下的实体声明。
    class DocumentBuilder(ElementTree.TreeBuilder):
        def doctype(self, name, public_id, system_id):
            raise ValueError("DOCTYPE is not allowed")
    root = ElementTree.fromstring(xml, parser=ElementTree.XMLParser(target=DocumentBuilder()))
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    if root.tag != namespace + "document":
        raise ValueError
    return "\n".join("".join(n.text or "" for n in p.iter(namespace + "t"))
                     for p in root.iter(namespace + "p"))


def pdf_text(data):
    if b"%PDF-" not in data[:1024]:
        raise ValueError
    from pypdf import PdfReader
    from services.profile.pdf_text import PDF_RENDER_DPI, extract_pdf_text

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or not 0 < len(reader.pages) <= 64:
        raise ValueError
    # 按固定分辨率进行 OCR 前检查页面尺寸，限制栅格化后的像素数。
    for page in reader.pages:
        box = page.mediabox
        width, height = (float(edge) * page.user_unit * PDF_RENDER_DPI / 72
                         for edge in (box.width, box.height))
        if not (0 < width <= 20000 and 0 < height <= 20000 and width * height <= MAX_PIXELS):
            raise ValueError
    text, error = extract_pdf_text(data)
    if error:
        raise ValueError
    return text


def image_text(data):
    import pytesseract
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {"JPEG", "PNG"} or image.width * image.height > MAX_PIXELS:
            raise ValueError
        try:
            return pytesseract.image_to_string(image, lang="chi_sim+eng", timeout=12)
        except pytesseract.TesseractError as exc:
            if "Error opening data file" not in str(exc) and "Failed loading language" not in str(exc):
                raise
            return pytesseract.image_to_string(image, lang="eng", timeout=12)


def trim(text):
    if "\x00" in text:
        raise ValueError
    text = text.strip()
    if not text:
        raise ValueError
    return text[:MAX_TEXT], len(text)


def worker(extension):
    # Linux 的 CPU 和地址空间限制也由 OCR 子进程继承。
    if sys.platform.startswith("linux"):
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    data = sys.stdin.buffer.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError
    parser = {"pdf": pdf_text, "docx": docx_text, "png": image_text, "jpeg": image_text, "jpg": image_text}
    print(json.dumps(trim(parser[extension](data))))


def extract(filename, data):
    from fastapi import HTTPException

    if len(data) > MAX_FILE:
        raise HTTPException(413, "文件过大，请上传 10MB 以内的简历文件。")
    name = re.split(r"[\\/]", filename)[-1].strip()
    if not name or len(name) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise HTTPException(422, "无效的文件名。")
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in {"txt", "md", "json", "pdf", "docx", "png", "jpeg", "jpg"}:
        raise HTTPException(422, "不支持的文件格式。")
    try:
        if ext in {"txt", "md", "json"}:
            text, count = trim(data.decode("utf-8-sig"))
        else:
            if not _PARSE_SLOTS.acquire(blocking=False):
                raise HTTPException(429, "解析队列繁忙，请稍后重试。")
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-m", "services.profile.parser", ext],
                    # 服务可能由 --app-dir 从其它工作目录启动；子进程仍从已加载的服务包定位。
                    cwd=Path(__file__).resolve().parents[2],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    start_new_session=os.name == "posix",
                    env={**{k: os.environ[k] for k in (
                        "PATH", "LANG", "LC_ALL", "TMPDIR", "TEMP", "SYSTEMROOT",
                        "TESSDATA_PREFIX", "TESSERACT_CMD"
                    ) if k in os.environ}, "OPENBLAS_NUM_THREADS": "1"},
                )
                try:
                    output, _ = proc.communicate(data, timeout=30)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.communicate()
                    raise ValueError from None
                if proc.returncode:
                    raise ValueError
                text, count = json.loads(output)
            finally:
                _PARSE_SLOTS.release()
    except (ValueError, OSError):
        raise HTTPException(422, "文件为空、损坏、超过解析限制或本地解析组件不可用。") from None
    return name, text, count


if __name__ == "__main__":
    worker(sys.argv[1])
