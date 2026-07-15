import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.src.resume_parser import _normalize_extracted_text, extract_pdf_text


def _selectable_text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_extract_pdf_text_reads_selectable_text():
    text, error = extract_pdf_text(_selectable_text_pdf("Jane Doe Python FastAPI PostgreSQL"))

    assert error is None
    assert "Jane Doe" in text
    assert "FastAPI" in text


def test_extract_pdf_text_rejects_non_pdf_content():
    text, error = extract_pdf_text(b"not really a pdf")

    assert text == ""
    assert "不是有效的 PDF" in error


def test_extract_pdf_text_explains_image_only_pdf_without_ocr_runtime():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)

    text, error = extract_pdf_text(output.getvalue())

    assert text == ""
    assert "扫描版 PDF" in error


def test_normalize_extracted_text_removes_broken_unicode_surrogates():
    text = _normalize_extracted_text("姓名 张三 \ud83d\nPython 😀 项目")

    assert "\ud83d" not in text
    assert "😀" in text
    assert text.encode("utf-8")
