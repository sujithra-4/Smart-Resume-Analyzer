import pytest

from app.core.exceptions import CorruptedDocumentError, EmptyDocumentError, FileTooLargeError, UnsupportedFileError
from app.services.docx_parser import extract_docx
from app.services.document_processor import process_document, validate_upload
from app.services.pdf_parser import extract_pdf
from tests.helpers import make_blank_pdf_bytes, make_docx_bytes, make_link_pdf_bytes, make_pdf_bytes, read_sample

RESUME = read_sample("resume_priya_raman.txt")


def test_pdf_extraction_returns_text_pages_and_type():
    r = extract_pdf(make_pdf_bytes(RESUME))
    assert r["file_type"] == "pdf" and r["page_count"] == 1
    assert "priya.raman@example.com" in r["text"]
    assert "FastAPI" in r["text"]


def test_pdf_multi_page_count():
    long_text = "\n".join(f"Line {i} of a long fictional resume" for i in range(120))
    assert extract_pdf(make_pdf_bytes(long_text))["page_count"] >= 2


def test_pdf_hyperlink_annotations_keep_labels_and_targets(processor):
    doc = extract_pdf(make_link_pdf_bytes())
    assert {link["url"] for link in doc["links"]} >= {
        "https://www.linkedin.com/in/test-person", "https://github.com/test-person"
    }
    profile = processor.parse(doc["text"], doc["page_count"], doc["links"])
    assert profile["personal_information"]["linkedin"] == "https://www.linkedin.com/in/test-person"
    assert profile["personal_information"]["github"] == "https://github.com/test-person"
    assert profile["personal_information"]["links"]["portfolio"] == "https://example.dev/test-person"


def test_pdf_without_text_is_rejected_as_empty():
    with pytest.raises(EmptyDocumentError):
        extract_pdf(make_blank_pdf_bytes())


def test_corrupted_pdf_is_rejected():
    with pytest.raises(CorruptedDocumentError):
        extract_pdf(b"%PDF-1.4 this is not really a pdf")


def test_docx_extraction_paragraphs():
    r = extract_docx(make_docx_bytes(RESUME))
    assert r["file_type"] == "docx" and r["page_count"] >= 1
    assert "Software Engineering Intern" in r["text"]


def test_docx_with_table_content():
    import io
    from docx import Document
    d = Document()
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "Skills"
    t.rows[0].cells[1].text = "Python, SQL"
    buf = io.BytesIO()
    d.save(buf)
    assert "Python, SQL" in extract_docx(buf.getvalue())["text"]


def test_empty_docx_is_rejected():
    with pytest.raises(EmptyDocumentError):
        extract_docx(make_docx_bytes(""))


def test_corrupted_docx_is_rejected():
    with pytest.raises(CorruptedDocumentError):
        extract_docx(b"PK\x03\x04 not a docx")


def test_process_document_cleans_bullets():
    doc = process_document(make_pdf_bytes("Summary\n• Built APIs with Python and FastAPI for students"), "pdf")
    assert "- Built APIs" in doc["text"]


@pytest.mark.parametrize("name,ctype,data,exc", [
    ("resume.txt", "text/plain", b"hello world", UnsupportedFileError),
    ("resume.exe", "application/octet-stream", b"MZ", UnsupportedFileError),
    ("resume.pdf", "image/png", b"%PDF-1.4", UnsupportedFileError),
    ("resume.pdf", "application/pdf", b"", EmptyDocumentError),
    ("resume.pdf", "application/pdf", b"not a pdf at all", CorruptedDocumentError),
    ("resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"plain text",
     CorruptedDocumentError),
    ("resume.pdf", "application/pdf", b"%PDF-" + b"0" * 2_000_000, FileTooLargeError),
])
def test_validate_upload_rejections(name, ctype, data, exc):
    with pytest.raises(exc):
        validate_upload(name, ctype, data, max_bytes=1_000_000)


def test_validate_upload_accepts_real_files():
    assert validate_upload("a.pdf", "application/pdf", make_pdf_bytes(RESUME), 1_000_000) == "pdf"
    assert validate_upload("a.DOCX", None, make_docx_bytes(RESUME), 1_000_000) == "docx"


def test_filename_sanitising():
    from app.utils.files import sanitize_filename
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("C:\\Users\\x\\my resume<script>.pdf") == "my resume_script.pdf"
