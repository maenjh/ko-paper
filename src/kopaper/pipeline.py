"""Translate one PDF: build glossary, run BabelDOC against the proxy, collect outputs and usage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import glossary
from .config import BABELDOC_BIN, DATA_DIR, JOBS_DIR, PROMPTS_DIR, PROXY_URL, SOURCE_LANGS


@dataclass
class Options:
    model: str = "sonnet"
    lang_in: str = "en"  # source language code, see config.SOURCE_LANGS
    domain: str | None = "cs_ml"
    user_glossaries: list[Path] = field(default_factory=list)
    pages: str | None = None
    mono: bool = True
    dual: bool = True
    qps: int = 4
    reextract_glossary: bool = False
    formula_hint: bool = False
    math_font_fix: bool = True
    restore_refs: bool = True
    review: bool = False  # second Claude pass that edits each batch (about 2x calls)
    ocr: bool = False  # experimental: layout quality on scanned PDFs is poor
    min_text_length: int = 2
    ignore_cache: bool = False
    proxy_url: str = PROXY_URL


@dataclass
class Result:
    paper_id: str
    job_dir: Path
    mono_pdf: Path | None
    dual_pdf: Path | None
    paper_glossary: Path | None
    restored_ref_pages: list[int]
    ocr_applied: bool
    seconds: float
    calls: int
    cache_hits: int
    errors: int
    input_tokens: int
    output_tokens: int
    returncode: int


def paper_id_of(pdf: Path) -> str:
    h = hashlib.sha256()
    with pdf.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def build_glossary(paper_id: str, opts: Options, dest: Path) -> tuple[Path | None, bool]:
    """Write the merged glossary for this run. Returns (path, skip_auto_extraction).

    Priority on conflicts: --glossary files > user-edited paper glossary > domain glossary
    > auto-extracted paper glossary (ignored once the user has edited it).
    """
    user_rows = [r for p in opts.user_glossaries for r in glossary.read(Path(p))]
    domain_rows = glossary.read(glossary.domain_path(opts.domain)) if opts.domain else []
    edited, auto = glossary.user_path(paper_id), glossary.paper_path(paper_id)
    edited_rows = glossary.read(edited) if edited.exists() else []
    auto_rows = glossary.read(auto) if auto.exists() and not edited.exists() else []
    reuse = (edited.exists() or auto.exists()) and not opts.reextract_glossary
    rows = glossary.merge(user_rows, edited_rows, domain_rows, auto_rows if reuse else [])
    if not rows:
        return None, reuse
    glossary.write(dest, rows)
    return dest, reuse


def babeldoc_entry(math_font_fix: bool) -> list[str]:
    """Plain `babeldoc`, or BabelDOC's interpreter + our launcher that patches math-font detection."""
    exe = shutil.which(BABELDOC_BIN) or BABELDOC_BIN
    if math_font_fix:
        # uv tools: ~/.local/bin/babeldoc links into the tool venv, whose bin/ holds its python.
        # Works even when the shebang is a /bin/sh trampoline (paths with spaces).
        py = Path(exe).resolve().with_name("python")
        if py.exists():
            return [str(py), str(Path(__file__).with_name("babeldoc_launcher.py"))]
        try:
            first = Path(exe).read_text(errors="ignore").splitlines()[0]
        except (OSError, IndexError):
            first = ""
        if first.startswith("#!") and "python" in first:
            return [first[2:].strip(), str(Path(__file__).with_name("babeldoc_launcher.py"))]
    return [exe]


def system_prompt(lang_in: str) -> str:
    text = (PROMPTS_DIR / "translate_ko.txt").read_text(encoding="utf-8")
    text = text.replace("{source}", SOURCE_LANGS[lang_in])
    if lang_in != "en":
        # Put the extra rule under "Content that must translate", right after the caption rule.
        anchor = '"Fig." → "그림").\n'
        text = text.replace(anchor, anchor + f"- Translate {SOURCE_LANGS[lang_in]} caption labels the same way "
                            "(the local words for \"Figure\" and \"Table\" → \"그림\", \"표\").\n", 1)
    return text


def proxy_model(opts: Options) -> str:
    """Model name sent to the proxy: `sonnet`, `sonnet@de`, `sonnet+review`, `sonnet@de+review`."""
    return opts.model + (f"@{opts.lang_in}" if opts.lang_in != "en" else "") + ("+review" if opts.review else "")


def babeldoc_cmd(src: Path, job_dir: Path, opts: Options, glossary_file: Path | None, reuse: bool) -> list[str]:
    cmd = [
        *babeldoc_entry(opts.math_font_fix), "--files", str(src), "--lang-in", opts.lang_in, "--lang-out", "ko",
        "--openai", "--openai-base-url", opts.proxy_url, "--openai-api-key", run_tag(job_dir),
        "--openai-model", proxy_model(opts),
        "--custom-system-prompt", system_prompt(opts.lang_in),
        "--min-text-length", str(opts.min_text_length),
        "--translate-table-text",
        "--qps", str(opts.qps), "--pool-max-workers", str(opts.qps),
        "--no-watermark", "--output", str(job_dir),
    ]
    if glossary_file:
        cmd += ["--glossary-files", str(glossary_file)]
    # Same paper again → reuse its saved glossary for consistent terms and ~25% fewer tokens.
    cmd += ["--no-auto-extract-glossary"] if reuse else ["--save-auto-extracted-glossary"]
    if opts.pages:
        cmd += ["--pages", opts.pages]
    if not opts.mono:
        cmd.append("--no-mono")
    if not opts.dual:
        cmd.append("--no-dual")
    if opts.formula_hint:
        cmd.append("--add-formula-placehold-hint")
    if opts.ignore_cache:
        cmd.append("--ignore-cache")
    return cmd


def run_tag(job_dir: Path) -> str:
    """Sent as BabelDOC's API key; the proxy logs it so usage counts only this run's calls."""
    return f"kopaper-{job_dir.parent.name}-{job_dir.name}"


def usage_since(t0: float, run: str | None = None) -> dict:
    log = DATA_DIR / "proxy_usage.jsonl"
    rows = []
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("ts", 0) >= t0 and (run is None or r.get("run") in (None, run)):
                rows.append(r)
    ok = [r for r in rows if "error" not in r]
    return {
        "calls": len(ok),
        "cache_hits": sum(1 for r in ok if r.get("cache_hit")),
        "errors": len(rows) - len(ok),
        "input_tokens": sum(r.get("prompt_tokens", 0) for r in ok),
        "output_tokens": sum(r.get("completion_tokens", 0) for r in ok),
    }


# BabelDOC's rich progress output: "<stage> (i/n)  ━━━╺━━  done/total  elapsed eta"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BAR = re.compile(r"^(?P<name>.+?)\s+[━╸╺─\s]+\s(?P<done>\d+)/(?P<total>\d+)\b")

# (stage, overall percent 0-100)
ProgressFn = Callable[[str, float], None]


class Cancelled(Exception):
    pass


def run_with_progress(cmd: list[str], log_path: Path, on_progress: ProgressFn,
                      cancel: threading.Event | None = None, env: dict | None = None) -> int:
    """Run BabelDOC under a pseudo-terminal so its live progress bars can be parsed."""
    import pty

    master, slave = pty.openpty()
    env = dict(env or os.environ, COLUMNS="200", TERM="xterm")
    proc = subprocess.Popen(cmd, stdout=slave, stderr=slave, stdin=subprocess.DEVNULL, env=env, close_fds=True)
    os.close(slave)
    pending, overall, stage, last_emit = "", 0.0, "준비 중", 0.0
    with log_path.open("w") as log:
        while True:
            if cancel is not None and cancel.is_set() and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            ready, _, _ = select.select([master], [], [], 0.5)
            if not ready:
                if proc.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            pending += _ANSI.sub("", chunk.decode("utf-8", errors="replace"))
            *frames, pending = re.split(r"[\r\n]", pending)
            active = None
            for line in frames:
                line = line.strip()
                m = _BAR.match(line)
                if not m:
                    if line:
                        log.write(line + "\n")
                    continue
                name, done, total = m["name"].strip(), int(m["done"]), int(m["total"])
                if name == "translate":
                    overall = 100.0 * done / max(total, 1)
                elif done < total and active is None:
                    active = re.sub(r"\s*\(\d+/\d+\)$", "", name)
            if active:
                stage = active
            now = time.time()
            if now - last_emit > 0.5:
                on_progress(stage, overall)
                last_emit = now
        os.close(master)
    rc = proc.wait()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    on_progress("완료" if rc == 0 else "실패", 100.0 if rc == 0 else overall)
    return rc


def translate_pdf(src: Path, out_dir: Path | None = None, opts: Options | None = None, quiet: bool = False,
                  on_progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> Result:
    opts = opts or Options()
    src = Path(src).resolve()
    out_dir = Path(out_dir).resolve() if out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    pid = paper_id_of(src)
    job_dir = JOBS_DIR / pid / time.strftime("%Y%m%d-%H%M%S")
    job_dir.mkdir(parents=True, exist_ok=True)

    # Scanned PDFs have no text layer: add one with Tesseract and translate that copy instead.
    from .ocr import ScannedPdfError, is_scanned, ocr_pdf

    work_src, ocr_applied = src, False
    if is_scanned(src):
        if not opts.ocr:
            raise ScannedPdfError(
                "스캔본 PDF입니다(텍스트 레이어 없음). 번역하려면 OCR 실험 기능을 켜야 합니다. "
                "글자가 겹치고 그림 속 문자도 번역되는 등 품질이 낮으니, 가능하면 원문 PDF를 구해 쓰세요.")
        cb = (lambda i, n: on_progress("OCR", 100.0 * i / n * 0.1)) if on_progress else None
        work_src = ocr_pdf(src, job_dir / f"{src.stem}.pdf", on_page=cb)
        ocr_applied = True

    gfile, reuse = build_glossary(pid, opts, job_dir / "glossary.input.csv")
    cmd = babeldoc_cmd(work_src, job_dir, opts, gfile, reuse)
    if ocr_applied:
        cmd.append(os.environ.get("KOPAPER_OCR_FLAG", "--auto-enable-ocr-workaround"))
    (job_dir / "command.json").write_text(json.dumps(cmd[:cmd.index("--custom-system-prompt")] + ["<prompt>"] + cmd[cmd.index("--custom-system-prompt") + 2:], ensure_ascii=False, indent=1))

    env = dict(os.environ)
    if opts.restore_refs and opts.math_font_fix:  # skipping needs our launcher
        from .postprocess import skip_regions_pdf_coords

        try:
            env["KOPAPER_SKIP_REGIONS"] = json.dumps(skip_regions_pdf_coords(work_src))
        except Exception:  # never block a translation on the heuristic
            env.pop("KOPAPER_SKIP_REGIONS", None)

    t0 = time.time()
    if on_progress:
        rc = run_with_progress(cmd, job_dir / "babeldoc.log", on_progress, cancel, env=env)
    elif quiet:
        with (job_dir / "babeldoc.log").open("w") as log:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env).returncode
    else:
        rc = subprocess.run(cmd, env=env).returncode
    seconds = time.time() - t0

    def pick(pattern: str) -> Path | None:
        found = sorted(job_dir.glob(pattern))
        return found[0] if found else None

    mono = dual = saved = None
    restored: list[int] = []
    if (m := pick("*.ko.mono.pdf")):
        mono = out_dir / f"{src.stem}.ko.pdf"
        shutil.copy2(m, mono)
        if opts.restore_refs:
            from .postprocess import restore_references

            restored = restore_references(work_src, mono)
    if (d := pick("*.ko.dual.pdf")):
        dual = out_dir / f"{src.stem}.ko.dual.pdf"
        shutil.copy2(d, dual)
    if (g := pick("*.glossary.csv")) and not reuse and not opts.pages:
        # BabelDOC's auto-extracted terms for the whole paper; reused on the next run of the same file.
        # Partial (--pages) runs are not saved, since their terms cover only part of the paper.
        saved = glossary.paper_path(pid)
        glossary.write(saved, glossary.drop_proper_nouns(glossary.merge(glossary.read(g))))
    elif reuse:
        saved = glossary.user_path(pid) if glossary.user_path(pid).exists() else glossary.paper_path(pid)

    res = Result(pid, job_dir, mono, dual, saved, restored, ocr_applied, round(seconds, 1), returncode=rc, **usage_since(t0, run_tag(job_dir)))
    (job_dir / "result.json").write_text(json.dumps(asdict(res), default=str, ensure_ascii=False, indent=1))
    return res
