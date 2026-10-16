"""Lite mode helpers: pure-Python text extraction and HTML → PDF with an installed browser."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "ko-paper" / "scripts"
SAMPLE = REPO / "docs" / "sample" / "sample-paper.pdf"
sys.path.insert(0, str(SCRIPTS))

from extract_text import main as extract_main, page_numbers  # noqa: E402


def test_page_numbers():
    assert page_numbers(None, 3) == [0, 1, 2]
    assert page_numbers("1-2,5", 4) == [0, 1]  # clipped to the document
    assert page_numbers("2", 3) == [1]


def test_extract_text_pages(capsys):
    pytest.importorskip("pypdf")
    assert extract_main([str(SAMPLE), "--pages", "1"]) == 0
    out = capsys.readouterr().out
    assert "===== page 1 / 2 =====" in out and "Calibrated Reliance" in out and "page 2 /" not in out


def test_extract_text_needs_no_compiled_modules():
    # Smart App Control blocks compiled modules; pypdf must stay pure Python.
    pypdf = pytest.importorskip("pypdf")
    root = Path(pypdf.__file__).parent
    assert not [p for p in root.rglob("*") if p.suffix in (".so", ".pyd", ".dll")]


def test_html2pdf(tmp_path):
    if not any(Path(p).exists() for p in ("/Applications/Google Chrome.app", "/Applications/Microsoft Edge.app")) \
            and not any(shutil.which(b) for b in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge")):
        pytest.skip("no Chromium browser")
    html = tmp_path / "공백 있는 폴더" / "t.ko.lite.html"
    html.parent.mkdir()
    tpl = (SCRIPTS / "lite_template.html").read_text(encoding="utf-8")
    html.write_text(tpl.replace("<!-- CONTENT -->", "<h1>시험 제목</h1><p>한글 문단</p>"), encoding="utf-8")
    out = html.with_suffix(".pdf")
    r = subprocess.run([str(SCRIPTS / "html2pdf.sh"), str(html), str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes().startswith(b"%PDF")
