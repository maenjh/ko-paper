"""Run BabelDOC with extra math fonts treated as formulas.

Executed with BabelDOC's own interpreter (separate uv tool env), not kopaper's.
BabelDOC hard-excludes Cambria Math from formula detection, so Word-made papers with a broken
Cambria Math ToUnicode map (e.g. italic u, i extracted as "$", "%") get re-rendered as garbage.
Treating those fonts as formulas keeps the original glyphs in place.

It also skips paragraphs inside KOPAPER_SKIP_REGIONS (the bibliography) during term extraction and
translation, so references are never sent to Claude. kopaper restores them from the original later.

Usage: <babeldoc-python> babeldoc_launcher.py [babeldoc args...]
Env:   KOPAPER_EXTRA_MATH_FONTS  regex on the font name (subset prefix removed)
       KOPAPER_SKIP_REGIONS      JSON list of {page, x0, y0, x1, y1} in PDF user space
"""
import base64
import functools
import json
import os
import re
import sys

from babeldoc.format.pdf.document_il.utils import formular_helper as fh

EXTRA = re.compile(os.environ.get("KOPAPER_EXTRA_MATH_FONTS", r"^(CambriaMath|Cambria Math|Cambria-Math)"))
_orig = fh.is_formulas_font


@functools.cache
def is_formulas_font(font_name, formular_font_pattern):
    name = font_name
    if name.startswith("BASE64:"):
        name = base64.b64decode(name[7:]).split(b"+")[-1].decode("latin-1", "replace")
    else:
        name = name.split("+")[-1]
    if name and EXTRA.match(name):
        return True
    return _orig(font_name, formular_font_pattern)


# Patch before the rest of BabelDOC imports the function by name.
fh.is_formulas_font = is_formulas_font

SKIP = json.loads(os.environ.get("KOPAPER_SKIP_REGIONS") or "[]")


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from il_fixes import merge_table_cells, skip_regions  # noqa: E402


_prepared: set[int] = set()


def _prepare(docs) -> None:
    if id(docs) in _prepared:
        return
    _prepared.add(id(docs))
    if os.environ.get("KOPAPER_MERGE_TABLE_CELLS", "1") == "1":
        try:
            merge_table_cells(docs)
        except Exception as e:  # never break a translation over this heuristic
            print(f"kopaper: table-cell merge skipped: {e}", file=sys.stderr)
    skip_regions(docs, SKIP)


def _wrap(cls, method: str) -> None:
    orig = getattr(cls, method)

    def wrapped(self, docs, *a, **k):
        _prepare(docs)
        return orig(self, docs, *a, **k)

    setattr(cls, method, wrapped)


from babeldoc.format.pdf.document_il.midend.automatic_term_extractor import AutomaticTermExtractor  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator  # noqa: E402
from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import ILTranslatorLLMOnly  # noqa: E402

_wrap(AutomaticTermExtractor, "procress")
_wrap(ILTranslator, "translate")
_wrap(ILTranslatorLLMOnly, "translate")


# ---- Table cells: tighter line spacing, no growing into the next row ----
# Korean uses a 1.5x line skip in BabelDOC; in narrow table cells that pushes text into the row below,
# and the box-expansion fallback can grow a cell over its neighbours. Applies to paragraphs whose
# layout label matches KOPAPER_TABLE_LABELS.
import atexit  # noqa: E402
import collections  # noqa: E402
import threading  # noqa: E402

from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting  # noqa: E402

TABLE_RE = re.compile(os.environ.get("KOPAPER_TABLE_LABELS", r"table|table_cell|table_text"), re.I)
TABLE_LINE_SKIP = float(os.environ.get("KOPAPER_TABLE_LINE_SKIP", "1.15"))
_tls = threading.local()
_labels: collections.Counter = collections.Counter()

_orig_find = Typesetting._find_optimal_scale_and_layout
_orig_layout = Typesetting._layout_typesetting_units
_orig_bottom = Typesetting.get_max_bottom_space
_orig_right = Typesetting.get_max_right_space


def _in_table_layout(paragraph, page) -> bool:
    b = getattr(paragraph, "box", None)
    if b is None or page is None:
        return False
    cx, cy = (b.x + b.x2) / 2, (b.y + b.y2) / 2
    for lay in getattr(page, "page_layout", None) or []:
        lb = getattr(lay, "box", None)
        if lb is not None and lay.class_name == "table" and lb.x <= cx <= lb.x2 and lb.y <= cy <= lb.y2:
            return True
    return False


def _find(self, paragraph, page=None, *a, **k):
    label = getattr(paragraph, "layout_label", None) or ""
    is_table = bool(TABLE_RE.fullmatch(label)) or _in_table_layout(paragraph, page)
    _labels["table-cell" if is_table else label] += 1
    prev = getattr(_tls, "table", False)
    _tls.table = is_table
    try:
        return _orig_find(self, paragraph, page, *a, **k)
    finally:
        _tls.table = prev


def _layout(self, units, box, scale, line_skip, *a, **k):
    if getattr(_tls, "table", False):
        line_skip = min(line_skip, TABLE_LINE_SKIP)
    return _orig_layout(self, units, box, scale, line_skip, *a, **k)


def _bottom(self, box, page):
    return box.y if getattr(_tls, "table", False) else _orig_bottom(self, box, page)


def _right(self, box, page):
    return box.x2 if getattr(_tls, "table", False) else _orig_right(self, box, page)


Typesetting._find_optimal_scale_and_layout = _find
Typesetting._layout_typesetting_units = _layout
Typesetting.get_max_bottom_space = _bottom
Typesetting.get_max_right_space = _right


@atexit.register
def _report_labels():
    if _labels:
        print("kopaper: layout labels " + json.dumps(dict(_labels)), file=sys.stderr)


from babeldoc.main import cli  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "babeldoc"
    sys.exit(cli())
