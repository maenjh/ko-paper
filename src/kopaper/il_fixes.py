"""Fixes applied to BabelDOC's intermediate representation before term extraction and translation.

Pure Python and duck-typed (no BabelDOC import) so it can be unit-tested; babeldoc_launcher.py loads it
inside BabelDOC's interpreter. stamped_verify is a startup-time fix that lives here for the same reason.
"""
from __future__ import annotations

import contextlib
import sys


def skip_regions(docs, SKIP: list[dict]) -> int:
    """Blank out paragraphs inside skip regions; BabelDOC ignores paragraphs whose unicode is None."""
    if not SKIP:
        return 0
    by_page: dict[int, list[dict]] = {}
    for r in SKIP:
        by_page.setdefault(r["page"], []).append(r)
    n = 0
    for page in docs.page:
        regions = by_page.get(page.page_number)
        if not regions:
            continue
        for p in page.pdf_paragraph:
            b = p.box
            if p.unicode is None or b is None:
                continue
            cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
            if any(r["x0"] <= cx <= r["x1"] and r["y0"] <= cy <= r["y1"] for r in regions):
                p.unicode = None
                n += 1
    if n:
        print(f"kopaper: skipped {n} reference paragraphs", file=sys.stderr)
    return n


def _chars(paragraph):
    """Original characters of a paragraph (their boxes come straight from the PDF)."""
    out = []
    for comp in paragraph.pdf_paragraph_composition or []:
        if getattr(comp, "pdf_character", None):
            out.append(comp.pdf_character)
        for attr in ("pdf_line", "pdf_same_style_characters", "pdf_formula"):
            obj = getattr(comp, attr, None)
            if obj is not None:
                out.extend(getattr(obj, "pdf_character", None) or [])
    return [c for c in out if getattr(c, "box", None) is not None]


def _text_box(paragraph):
    """(left, top) of the paragraph's actual glyphs, falling back to its layout box."""
    cs = _chars(paragraph)
    if not cs:
        return paragraph.box.x, paragraph.box.y2
    return min(c.box.x for c in cs), max(c.box.y2 for c in cs)


def merge_table_cells(docs) -> int:
    """Merge per-line paragraphs inside table cells into one paragraph per cell.

    BabelDOC's layout model puts each line of a multi-line table cell into its own paragraph, so a cell
    like "Adult family / member; driver or / passenger" is translated in fragments and the fragments are
    placed line by line, overlapping the next row once Korean text wraps differently. Rows are delimited
    by the entries of the leftmost column; columns by left edges.
    """
    merged_total = 0
    for page in docs.page:
        tables = [lay.box for lay in (getattr(page, "page_layout", None) or [])
                  if lay.class_name == "table" and lay.box is not None]
        if not tables:
            continue
        for tb in tables:
            cells = [p for p in page.pdf_paragraph
                     if p.unicode is not None and p.box is not None
                     and (p.layout_label or "") != "table_caption"
                     and tb.x <= (p.box.x + p.box.x2) / 2 <= tb.x2 and tb.y <= (p.box.y + p.box.y2) / 2 <= tb.y2]
            if len(cells) < 4:
                continue
            geo = {id(p): _text_box(p) for p in cells}
            left = lambda p: geo[id(p)][0]  # noqa: E731
            top = lambda p: geo[id(p)][1]  # noqa: E731
            # columns by left edge of the glyphs
            cols: list[list] = []
            for p in sorted(cells, key=left):
                if cols and abs(left(cols[-1][0]) - left(p)) <= 6:
                    cols[-1].append(p)
                else:
                    cols.append([p])
            # Row tops: heights where a line starts in at least half of the columns. Continuation lines of
            # multi-line cells occur in only one or two columns, so they never start a row.
            col_of = {id(p): ci for ci, col in enumerate(cols) for p in col}
            clusters: list[list] = []
            for p in sorted(cells, key=lambda p: -top(p)):
                if clusters and abs(top(clusters[-1][0]) - top(p)) <= 2.5:
                    clusters[-1].append(p)
                else:
                    clusters.append([p])
            need = max(2, (len(cols) + 1) // 2)
            tops = [top(c[0]) for c in clusters if len({col_of[id(p)] for p in c}) >= need]
            if len(tops) < 2:
                continue

            def band(p):
                for i, t in enumerate(tops):
                    nxt = tops[i + 1] if i + 1 < len(tops) else float("-inf")
                    if top(p) <= t + 2.5 and top(p) > nxt + 2.5:
                        return i
                return -1

            remove = set()
            for col in cols:
                groups: dict[int, list] = {}
                for p in col:
                    groups.setdefault(band(p), []).append(p)
                for b, ps in groups.items():
                    if b < 0 or len(ps) < 2:
                        continue
                    ps.sort(key=lambda p: -top(p))
                    head = ps[0]
                    text = head.unicode
                    for p in ps[1:]:
                        if text.endswith("-") and p.unicode[:1].islower():
                            text = text[:-1] + p.unicode
                        else:
                            text = f"{text} {p.unicode}"
                        head.pdf_paragraph_composition.extend(p.pdf_paragraph_composition)
                        head.box.x = min(head.box.x, p.box.x)
                        head.box.y = min(head.box.y, p.box.y)
                        head.box.x2 = max(head.box.x2, p.box.x2)
                        head.box.y2 = max(head.box.y2, p.box.y2)
                        remove.add(id(p))
                        merged_total += 1
                    head.unicode = text
            if remove:
                page.pdf_paragraph[:] = [p for p in page.pdf_paragraph if id(p) not in remove]
    if merged_total:
        print(f"kopaper: merged {merged_total} table-cell lines", file=sys.stderr)
    return merged_total


def stamped_verify(path, sha3_256: str, full_check) -> bool:
    """Drop-in for BabelDOC's verify_file: trust the last full hash while size and mtime are unchanged.

    BabelDOC re-hashes ~100 cached fonts on every run (~1s). The stamp next to the file stores
    "<sha3> <size> <mtime_ns>"; any mismatch or I/O error falls back to full_check.
    """
    if not path.exists():
        return False
    st = path.stat()
    stamp = path.with_name(path.name + ".verified")
    tag = f"{sha3_256} {st.st_size} {st.st_mtime_ns}"
    with contextlib.suppress(OSError):
        if stamp.read_text() == tag:
            return True
    ok = full_check(path, sha3_256)
    if ok:
        with contextlib.suppress(OSError):
            stamp.write_text(tag)
    return ok
