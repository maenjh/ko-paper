"""Scanned-PDF support: detect PDFs without a text layer and add one with Tesseract."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pymupdf


class ScannedPdfError(Exception):
    pass


def is_scanned(pdf: Path, min_chars_per_page: int = 80) -> bool:
    """True when most pages are images with (almost) no extractable text."""
    doc = pymupdf.open(pdf)
    try:
        pages = list(doc)[:20]
        if not pages:
            return False
        empty = sum(1 for p in pages if len(p.get_text().strip()) < min_chars_per_page and p.get_images())
        return empty / len(pages) >= 0.5
    finally:
        doc.close()


def tessdata() -> str | None:
    try:
        return pymupdf.get_tessdata()
    except Exception:
        return None


def ocr_pdf(src: Path, dst: Path, lang: str = "eng", dpi: int = 300,
            on_page: Callable[[int, int], None] | None = None) -> Path:
    """Write a copy of `src` where every page is the scanned image plus an invisible OCR text layer."""
    td = tessdata()
    if not td:
        raise ScannedPdfError(
            "스캔본 PDF입니다. 글자 인식에 필요한 Tesseract가 없습니다. "
            "`brew install tesseract`로 설치한 뒤 다시 시도하세요.")
    doc = pymupdf.open(src)
    out = pymupdf.open()
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            one = pymupdf.open("pdf", pix.pdfocr_tobytes(language=lang, tessdata=td))
            out.insert_pdf(one)
            # keep the original page size so the layout matches the source
            out[-1].set_mediabox(page.rect)
            one.close()
            if on_page:
                on_page(i + 1, doc.page_count)
        out.save(dst, garbage=3, deflate=True)
    finally:
        out.close()
        doc.close()
    return dst
