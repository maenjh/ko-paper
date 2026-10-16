"""kopaper CLI: translate English paper PDFs into layout-preserving Korean PDFs."""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import httpx

from .config import BACKEND, PROXY_HOST, PROXY_PORT, PROXY_URL


def proxy_alive() -> str | None:
    try:
        r = httpx.get(f"{PROXY_URL}/models", timeout=2)
        return r.json().get("backend", "unknown") if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def ensure_proxy() -> str:
    """Reuse a running proxy or start one in a background thread of this process."""
    if (b := proxy_alive()):
        return b
    import uvicorn

    from .proxy.server import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host=PROXY_HOST, port=PROXY_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if (b := proxy_alive()):
            return b
        time.sleep(0.1)
    sys.exit(f"proxy failed to start on {PROXY_URL}")


def cmd_translate(a: argparse.Namespace) -> int:
    from .pipeline import Options, translate_pdf

    backend = ensure_proxy()
    if backend == "claude-code":
        print("backend: your Claude Code login (claude -p). Local use only, do not expose as a service.", file=sys.stderr)
    opts = Options(
        model=a.model, domain=None if a.domain == "none" else a.domain,
        user_glossaries=[Path(p) for p in a.glossary], pages=a.pages,
        mono=not a.dual_only, dual=not a.mono_only, qps=a.qps,
        reextract_glossary=a.reextract_glossary, formula_hint=a.formula_hint,
        math_font_fix=not a.no_math_font_fix, restore_refs=not a.translated_refs, ocr=a.ocr, review=a.review,
        ignore_cache=a.ignore_cache,
    )
    rc = 0
    for f in a.files:
        src = Path(f)
        if not src.is_file():
            print(f"skip: {src} not found", file=sys.stderr)
            rc = 1
            continue
        print(f"\n▶ {src.name}", file=sys.stderr)
        try:
            r = translate_pdf(src, a.out, opts, quiet=a.quiet)
        except Exception as e:
            print(f"✗ {e}", file=sys.stderr)
            rc = 1
            continue
        if r.returncode != 0 or not (r.mono_pdf or r.dual_pdf):
            print(f"✗ failed (babeldoc exit {r.returncode}). log: {r.job_dir}", file=sys.stderr)
            rc = 1
            continue
        print(f"✓ {r.seconds:.0f}s · calls {r.calls} (cache {r.cache_hits}, errors {r.errors}) · "
              f"tokens in {r.input_tokens:,} / out {r.output_tokens:,}")
        if r.ocr_applied:
            print("  scanned PDF: text layer added with Tesseract OCR")
        if r.restored_ref_pages:
            print(f"  references restored from original: pages {r.restored_ref_pages}")
        for p in (r.mono_pdf, r.dual_pdf, r.paper_glossary):
            if p:
                print(f"  {p}")
    return rc


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    if a.proxy_only:
        from .proxy.server import create_app

        app = create_app()
    else:
        from .web.app import create_web_app

        app = create_web_app()
    url = f"http://{PROXY_HOST}:{PROXY_PORT}/"
    print(f"{'proxy' if a.proxy_only else 'web UI'}: {url}  (backend={BACKEND})", file=sys.stderr)
    if not a.proxy_only and a.open:
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # Always loopback only: the subscription backend is for personal use.
    uvicorn.run(app, host=PROXY_HOST, port=PROXY_PORT, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kopaper", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("translate", help="translate PDF(s) to Korean, keeping layout and figures")
    t.add_argument("files", nargs="+")
    t.add_argument("-o", "--out", help="output directory (default: next to each input)")
    t.add_argument("-m", "--model", default="sonnet", choices=["sonnet", "opus", "haiku"])
    t.add_argument("-d", "--domain", default="cs_ml", help="domain glossary in glossary/ (or 'none')")
    t.add_argument("-g", "--glossary", action="append", default=[], help="extra glossary CSV (highest priority)")
    t.add_argument("-p", "--pages", help="pages to translate, e.g. 1-3,5")
    g = t.add_mutually_exclusive_group()
    g.add_argument("--mono-only", action="store_true", help="only the Korean PDF")
    g.add_argument("--dual-only", action="store_true", help="only the side-by-side EN/KO PDF")
    t.add_argument("--qps", type=int, default=4, help="parallel requests (default 4)")
    t.add_argument("--reextract-glossary", action="store_true", help="ignore this paper's saved glossary")
    t.add_argument("--formula-hint", action="store_true", help="BabelDOC formula placeholder hint (experimental)")
    t.add_argument("--no-math-font-fix", action="store_true", help="don't treat Cambria Math as formula font")
    t.add_argument("--review", action="store_true", help="second Claude pass that edits each translated batch (~2x usage)")
    t.add_argument("--ocr", action="store_true", help="experimental: OCR scanned PDFs with Tesseract first")
    t.add_argument("--translated-refs", action="store_true", help="keep BabelDOC's re-typeset bibliography")
    t.add_argument("--ignore-cache", action="store_true", help="bypass BabelDOC's translation cache")
    t.add_argument("-q", "--quiet", action="store_true", help="write BabelDOC progress to the job log only")
    t.set_defaults(func=cmd_translate)

    s = sub.add_parser("serve", help="run the web UI (and the proxy) on 127.0.0.1")
    s.add_argument("--proxy-only", action="store_true", help="serve only the OpenAI-compatible proxy")
    s.add_argument("--open", action="store_true", help="open the web UI in the default browser")
    s.set_defaults(func=cmd_serve)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
