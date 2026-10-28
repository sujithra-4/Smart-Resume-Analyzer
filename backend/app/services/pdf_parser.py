"""PDF text extraction with PyMuPDF."""
import logging
from urllib.parse import urlparse

import pymupdf

from app.core.exceptions import CorruptedDocumentError, EmptyDocumentError, format_safe_traceback

logger = logging.getLogger(__name__)


def _pdf_links(page) -> list[dict[str, str]]:
    """Extract URI annotations and the visible text overlapping each annotation."""
    links: list[dict[str, str]] = []
    for link in page.get_links():
        target = link.get("uri")
        if not target or urlparse(target).scheme not in {"http", "https"}:
            continue
        words = page.get_text("words", sort=True)
        label = " ".join(word[4] for word in words if pymupdf.Rect(word[:4]).intersects(link["from"])).strip()
        links.append({"label": label, "url": target})
    return links


def extract_pdf(data: bytes) -> dict:
    """Return {"text", "page_count", "file_type"} or raise a clean AppError."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several error types for invalid input
        logger.warning("PDF could not be opened:\n%s", format_safe_traceback(exc))
        raise CorruptedDocumentError("The PDF could not be read. It may be corrupted.") from exc

    try:
        if doc.needs_pass:
            raise CorruptedDocumentError("The PDF is password protected and cannot be processed.")
        pages, links = [], []
        for page in doc:
            # sort=True returns text blocks in reading order (top-to-bottom, left-to-right)
            pages.append(page.get_text("text", sort=True))
            links.extend(_pdf_links(page))
        page_count = doc.page_count
    except CorruptedDocumentError:
        raise
    except Exception as exc:
        logger.warning("PDF text extraction failed:\n%s", format_safe_traceback(exc))
        raise CorruptedDocumentError("Text could not be extracted from this PDF.") from exc
    finally:
        doc.close()

    text = "\n".join(pages).strip()
    if not text:
        raise EmptyDocumentError(
            "No text found in this PDF. Scanned/image-only PDFs need OCR, which is not supported yet."
        )
    return {"text": text, "page_count": page_count, "file_type": "pdf", "links": links}
