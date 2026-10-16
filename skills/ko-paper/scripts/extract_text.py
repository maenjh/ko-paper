"""Print a PDF's text page by page for the lite mode.

Pure Python (pypdf only, no compiled modules), so Windows Smart App Control has nothing to block.
  uv run --no-project --with pypdf python extract_text.py paper.pdf [--pages 1-5]
  python -m pip install --user pypdf && python extract_text.py paper.pdf
"""
from __future__ import annotations

import argparse
import sys


def page_numbers(spec: str | None, total: int) -> list[int]:
    """'1-3,7' → [0, 1, 2, 6] (0-based, clipped to the document)."""
    if not spec:
        return list(range(total))
    out = []
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        out += range(int(lo) - 1, min(int(hi or lo), total))
    return out


def main(argv: list[str] | None = None) -> int:
    from pypdf import PdfReader

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="e.g. 1-5,8 (default: all)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp949
    reader = PdfReader(a.pdf)
    total = len(reader.pages)
    for i in page_numbers(a.pages, total):
        sys.stdout.write(f"\n===== page {i + 1} / {total} =====\n")
        sys.stdout.write((reader.pages[i].extract_text() or "").strip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
