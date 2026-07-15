from __future__ import annotations

import io
import os
import re


PDF_OCR_MAX_PAGES = 12
PDF_RENDER_DPI = 200


def _normalize_extracted_text(value: str) -> str:
    # Some PDFs expose broken UTF-16 surrogate halves (for example an
    # incomplete emoji). Python can hold them in a string, but MySQL's UTF-8
    # encoder correctly refuses to persist them. Real non-BMP characters are
    # single code points here and are preserved; only invalid halves are removed.
    safe_value = re.sub(r"[\ud800-\udfff]", "", str(value)).replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in safe_value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _text_score(value: str) -> int:
    """Prefer readable text over output made mostly of extraction artifacts."""
    normalized = _normalize_extracted_text(value)
    readable = sum(char.isalnum() or "\u3400" <= char <= "\u9fff" for char in normalized)
    artifacts = normalized.count("\ufffd") + normalized.count("\x00")
    return readable - artifacts * 20


def _extract_with_pypdf(content: bytes) -> tuple[list[str], int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("password required")
        except Exception as exc:
            raise ValueError("PDF 已加密，请先解除密码保护后重新上传。") from exc

    pages: list[str] = []
    for page in reader.pages:
        candidates: list[str] = []
        try:
            candidates.append(page.extract_text() or "")
        except Exception:
            pass
        try:
            candidates.append(page.extract_text(extraction_mode="layout") or "")
        except Exception:
            pass
        pages.append(_normalize_extracted_text(max(candidates, key=_text_score, default="")))
    return pages, len(reader.pages)


def _load_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz

            return fitz
        except ImportError:
            return None


def _extract_with_pymupdf(content: bytes) -> tuple[list[str], object] | None:
    pymupdf = _load_pymupdf()
    if pymupdf is None:
        return None

    document = pymupdf.open(stream=content, filetype="pdf")
    if document.needs_pass:
        document.close()
        raise ValueError("PDF 已加密，请先解除密码保护后重新上传。")

    pages = [_normalize_extracted_text(page.get_text("text", sort=True)) for page in document]
    return pages, document


def _ocr_pdf_pages(document: object, pages: list[str]) -> tuple[list[str], str | None]:
    empty_page_indexes = [index for index, text in enumerate(pages) if _text_score(text) < 20]
    if not empty_page_indexes:
        return pages, None
    if len(pages) > PDF_OCR_MAX_PAGES:
        return pages, f"扫描版 PDF 最多支持 {PDF_OCR_MAX_PAGES} 页 OCR，请压缩页数后重试。"

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return pages, "扫描版 PDF 需要 OCR 组件（pytesseract 和 Pillow），请安装后重试。"

    configured_command = os.getenv("TESSERACT_CMD", "").strip()
    if configured_command:
        pytesseract.pytesseract.tesseract_cmd = configured_command

    try:
        for index in empty_page_indexes:
            page = document[index]
            pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            try:
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
            except pytesseract.pytesseract.TesseractError as exc:
                message = str(exc)
                if "Error opening data file" not in message and "Failed loading language" not in message:
                    raise
                text = pytesseract.image_to_string(image, lang="eng")
            pages[index] = _normalize_extracted_text(text)
    except pytesseract.pytesseract.TesseractNotFoundError:
        return pages, "检测到扫描版 PDF，但服务器未安装 Tesseract OCR；请安装并配置 TESSERACT_CMD 后重试。"
    except pytesseract.pytesseract.TesseractError as exc:
        return pages, f"PDF OCR 识别失败：{exc}"
    except Exception as exc:
        return pages, f"PDF 页面渲染或 OCR 失败：{exc}"
    return pages, None


def extract_pdf_text(content: bytes) -> tuple[str, str | None]:
    """Extract selectable text and fall back to OCR for image-only PDF pages."""
    if b"%PDF-" not in content[:1024]:
        return "", "文件内容不是有效的 PDF，请确认文件未损坏或扩展名没有被修改。"

    candidates: list[list[str]] = []
    page_count = 0
    errors: list[str] = []

    try:
        pypdf_pages, page_count = _extract_with_pypdf(content)
        candidates.append(pypdf_pages)
    except ImportError:
        errors.append("缺少 pypdf")
    except ValueError as exc:
        return "", str(exc)
    except Exception as exc:
        errors.append(f"pypdf: {exc}")

    document = None
    try:
        pymupdf_result = _extract_with_pymupdf(content)
        if pymupdf_result is not None:
            pymupdf_pages, document = pymupdf_result
            page_count = max(page_count, len(pymupdf_pages))
            candidates.append(pymupdf_pages)
    except ValueError as exc:
        return "", str(exc)
    except Exception as exc:
        errors.append(f"PyMuPDF: {exc}")

    if not candidates:
        detail = "；".join(errors) if errors else "没有可用的 PDF 解析组件"
        return "", f"PDF 解析功能不可用：{detail}。请安装后端依赖后重试。"

    pages: list[str] = []
    for index in range(page_count):
        page_candidates = [items[index] for items in candidates if index < len(items)]
        pages.append(max(page_candidates, key=_text_score, default=""))

    ocr_error = None
    if document is not None:
        pages, ocr_error = _ocr_pdf_pages(document, pages)
        document.close()

    text = _normalize_extracted_text("\n\n".join(pages))
    if _text_score(text) >= 20:
        return text, None
    if ocr_error:
        return "", ocr_error
    if document is None:
        return "", "PDF 中没有可提取的文字；扫描版 PDF 需要安装 PyMuPDF 和 Tesseract OCR。"
    return "", "扫描版 PDF 中没有识别到文字，请确认扫描画面清晰，或直接粘贴简历文本。"
