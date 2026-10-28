"""Test helpers: deterministic encoder + file builders."""
import hashlib
import io
import re
from pathlib import Path

import numpy as np
import pymupdf
from docx import Document
from spacy.lang.en.stop_words import STOP_WORDS

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


class HashingEncoder:
    """Deterministic bag-of-words encoder used ONLY in tests so the suite runs offline and fast.

    Texts that share words get a higher cosine similarity, which is enough to test the matching
    maths and pipeline. It is not a substitute for the real transformer (see test_embedding_real.py).
    """

    model_name = "test-hashing-encoder"
    loaded = True
    load_error = None
    DIM = 512

    def encode(self, texts):
        out = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z0-9+#.]+", t.lower()):
                if w in STOP_WORDS:
                    continue
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                out[i, h % self.DIM] += 1.0
        return out


def read_sample(name: str) -> str:
    return (SAMPLE_DIR / name).read_text(encoding="utf-8")


def make_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for line in text.split("\n"):
        if y > 780:
            page, y = doc.new_page(), 60
        page.insert_text((50, y), line, fontsize=10)
        y += 14
    data = doc.tobytes()
    doc.close()
    return data


def make_link_pdf_bytes() -> bytes:
    """Small PDF whose visible labels intentionally differ from URI targets."""
    doc = pymupdf.open()
    page = doc.new_page()
    labels = [("LinkedIn", "https://www.linkedin.com/in/test-person"),
              ("GitHub", "https://github.com/test-person"),
              ("Portfolio", "https://example.dev/test-person")]
    y = 60
    for label, target in labels:
        page.insert_text((50, y), label, fontsize=11)
        page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, y - 12, 120, y + 3), "uri": target})
        y += 20
    page.insert_text((50, y), "github.com/plain-text-profile", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def make_blank_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def make_docx_bytes(text: str) -> bytes:
    d = Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
