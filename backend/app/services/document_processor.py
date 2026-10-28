"""Validates an uploaded file and routes it to the right parser."""
import io
import logging
import zipfile
from pathlib import Path

from app.core.exceptions import CorruptedDocumentError, EmptyDocumentError, FileTooLargeError, UnsupportedFileError
from app.services.docx_parser import extract_docx
from app.services.pdf_parser import extract_pdf
from app.utils.files import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES
from app.utils.text import clean_text

logger = logging.getLogger(__name__)


def validate_upload(filename: str, content_type: str | None, data: bytes, max_bytes: int) -> str:
    """Validate extension, MIME type, size and file signature. Returns the file type ('pdf'|'docx')."""
    ext = Path(filename or "").suffix.lower()
    file_type = ALLOWED_EXTENSIONS.get(ext)
    if not file_type:
        raise UnsupportedFileError()
    if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_MIME_TYPES[file_type]:
        raise UnsupportedFileError(f"File content type '{content_type}' does not match a {file_type.upper()} file.")
    if len(data) == 0:
        raise EmptyDocumentError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise FileTooLargeError(f"File is too large. Maximum size is {max_bytes // (1024 * 1024)} MB.")

    # Check magic bytes: the extension and MIME type are both client-controlled.
    if file_type == "pdf":
        if not data.lstrip()[:5] == b"%PDF-":
            raise CorruptedDocumentError("The file is not a valid PDF.")
    else:
        if not data.startswith(b"PK"):
            raise CorruptedDocumentError("The file is not a valid DOCX.")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" not in zf.namelist():
                    raise CorruptedDocumentError("The file is not a valid DOCX.")
        except zipfile.BadZipFile as exc:
            raise CorruptedDocumentError("The file is not a valid DOCX.") from exc
    return file_type


def process_document(data: bytes, file_type: str) -> dict:
    """Extract and clean text while preserving parser metadata such as PDF hyperlinks."""
    result = extract_pdf(data) if file_type == "pdf" else extract_docx(data)
    result["text"] = clean_text(result["text"])
    if len(result["text"].split()) < 5:
        raise EmptyDocumentError("The document has too little text to analyse.")
    return result
