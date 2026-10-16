"""Post-processing of BabelDOC output.

restore_references: BabelDOC re-typesets the bibliography even though it is left in English, and
the year/volume/page fragments often scatter. References need no translation, so we put the
original page content back from the "References" heading onward.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

_HEADING = re.compile(
    r"^(\d+\.?\s*)?(References|REFERENCES|Bibliography|BIBLIOGRAPHY|Works Cited"
    # de, fr, es, it, pt, nl, ru, ja/zh
    r"|(?i:Literatur|Literaturverzeichnis|Quellenverzeichnis|Références|Références bibliographiques|Bibliographie"
    r"|Referencias|Bibliografía|Bibliografia|Riferimenti bibliografici|Referências|Referências bibliográficas"
    r"|Literatuur|Referenties|Литература|Список литературы)|参考文献)$"
)
_APPENDIX = re.compile(r"^(Appendix|APPENDIX|Supplementary|SUPPLEMENTARY)\b|^A(\.\d*)?\s+[A-Z][A-Za-z].{2,60}$")
_REF_LINE = re.compile(r"^\[\d+\]|\b(19|20)\d{2}[a-z]?\b")


def _lines(page: pymupdf.Page):
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            text = "".join(s["text"] for s in l["spans"]).strip()
            if text:
                yield text, pymupdf.Rect(l["bbox"]), l["spans"]


def find_reference_heading(doc: pymupdf.Document) -> tuple[int, pymupdf.Rect] | None:
    """Last "References" heading in the document (avoids tables of contents)."""
    found = None
    for i, page in enumerate(doc):
        for text, rect, _ in _lines(page):
            if _HEADING.match(text):
                found = (i, rect)
    return found


def _is_two_column(page: pymupdf.Page) -> bool:
    mid = page.rect.width / 2
    rights = sum(1 for _, r, _ in _lines(page) if r.x0 > mid - 5)
    lefts = sum(1 for _, r, _ in _lines(page) if r.x1 < mid + 5)
    return rights > 5 and lefts > 5


def _full_width_bottom(page: pymupdf.Page, before_y: float) -> float:
    """Lowest edge of full-width items (tables, wide figures, captions) above `before_y`."""
    W, H = page.rect.width, page.rect.height
    mid = W / 2
    rects = [r for _, r, _ in _lines(page)] + [d["rect"] for d in page.get_drawings()]
    ys = [r.y1 for r in rects
          if r.x0 < mid - 15 and r.x1 > mid + 15 and H * 0.05 < r.y0 < before_y and r.y1 < H * 0.93]
    return max(ys, default=0.0)


def _column_regions(page: pymupdf.Page, start: tuple[int, float] | None) -> tuple[list[pymupdf.Rect], list[str], bool]:
    """Regions from `start` (column index, y) to the end of the page in reading order.

    Stops at an appendix heading. Returns (regions, texts inside them, appendix_reached).
    """
    W, H = page.rect.width, page.rect.height
    mid = W / 2
    lines = sorted(_lines(page), key=lambda x: x[1].y0)
    cols = [(0.0, mid), (mid, W)] if _is_two_column(page) else [(0.0, W)]
    first_col, first_y = start if start else (0, None)
    first_col = min(first_col, len(cols) - 1)
    regions, texts, ended = [], [], False
    for ci in range(first_col, len(cols)):
        x0, x1 = cols[ci]
        col = [(t, r) for t, r, _ in lines if r.x0 >= x0 - 5 and r.x1 <= x1 + 5 and H * 0.05 < r.y0 < H * 0.95]
        if ci == first_col and first_y is not None:
            y0 = first_y
        else:
            floor = _full_width_bottom(page, H * 0.95)
            body = [r.y0 for _, r in col if r.y0 > floor]
            if not body:
                continue
            y0 = min(body) - 2
        y1 = H
        for t, r in col:
            if r.y0 > y0 + 2 and _APPENDIX.match(t):
                y1, ended = r.y0 - 2, True
                break
        texts += [t for t, r in col if y0 <= r.y0 < y1]
        regions.append(pymupdf.Rect(x0, y0, x1, y1))
        if ended:
            break
    return regions, texts, ended


def _ref_ratio(texts: list[str]) -> float:
    return sum(1 for t in texts if _REF_LINE.search(t)) / len(texts) if texts else 0.0


def _overlay(out_page: pymupdf.Page, src: pymupdf.Document, pno: int, rect: pymupdf.Rect) -> None:
    out_page.add_redact_annot(rect)
    out_page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    out_page.show_pdf_page(rect, src, pno, clip=rect)


def reference_regions(src: pymupdf.Document) -> list[tuple[int, pymupdf.Rect]]:
    """Bibliography regions (page index, rect in PyMuPDF top-left coordinates)."""
    hit = find_reference_heading(src)
    if not hit:
        return []
    pno, head = hit
    W = src[pno].rect.width
    col = 1 if _is_two_column(src[pno]) and head.x0 >= W / 2 else 0
    out: list[tuple[int, pymupdf.Rect]] = []
    start: tuple[int, float] | None = (col, head.y0 - 4)
    for i in range(pno, src.page_count):
        regions, texts, ended = _column_regions(src[i], start)
        if i > pno and _ref_ratio(texts) < 0.3:
            break
        out += [(i, r) for r in regions if r.height > 4]
        if ended:
            break
        start = None
    return out


def skip_regions_pdf_coords(src_pdf: Path) -> list[dict]:
    """Reference regions in PDF user space (bottom-left origin) for BabelDOC's IL boxes."""
    src = pymupdf.open(src_pdf)
    res = []
    for pno, r in reference_regions(src):
        h = src[pno].mediabox.height
        res.append({"page": pno, "x0": r.x0, "x1": r.x1, "y0": h - r.y1, "y1": h - r.y0})
    src.close()
    return res


def restore_references(src_pdf: Path, translated_pdf: Path) -> list[int]:
    """Restore the bibliography region in a translated (mono) PDF. Returns 1-based restored pages."""
    src = pymupdf.open(src_pdf)
    out = pymupdf.open(translated_pdf)
    if src.page_count != out.page_count:
        return []
    regions = reference_regions(src)
    for pno, r in regions:
        _overlay(out[pno], src, pno, r)
    restored = sorted({pno + 1 for pno, _ in regions})
    if restored:
        tmp = translated_pdf.with_suffix(".tmp.pdf")
        out.save(tmp, garbage=3, deflate=True)
        out.close()
        tmp.replace(translated_pdf)
    else:
        out.close()
    src.close()
    return restored
