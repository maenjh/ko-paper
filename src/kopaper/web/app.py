"""Web UI + JSON API, served together with the OpenAI-compatible proxy on 127.0.0.1."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .. import glossary as gl
from .. import usage
from ..config import BACKEND, GLOSSARY_DIR, SOURCE_LANGS
from ..proxy.server import create_app
from .jobs import JobManager

STATIC = Path(__file__).with_name("static")
MAX_PDF_BYTES = 100 * 1024 * 1024
MODELS = ["sonnet", "opus", "haiku"]
LANG_NAMES = {"en": "영어", "de": "독일어", "fr": "프랑스어", "es": "스페인어", "it": "이탈리아어",
              "pt": "포르투갈어", "nl": "네덜란드어", "ru": "러시아어", "ja": "일본어", "zh": "중국어"}
assert LANG_NAMES.keys() == SOURCE_LANGS.keys()


def create_web_app(manager: JobManager | None = None, start_worker: bool = True, backend: str = BACKEND) -> FastAPI:
    app = create_app(backend)  # includes /v1/* proxy routes
    jobs = manager or JobManager()
    if start_worker:
        jobs.start_worker()
    app.state.jobs = jobs

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/options")
    async def options():
        domains = sorted(p.stem for p in GLOSSARY_DIR.glob("*.csv"))
        return {"backend": backend, "models": MODELS, "domains": domains, "default_domain": "cs_ml",
                "langs": LANG_NAMES, "default_lang": "en"}

    @app.get("/api/jobs")
    async def list_jobs():
        return jobs.list()

    @app.post("/api/jobs")
    async def create_job(
        file: UploadFile = File(...),
        model: str = Form("sonnet"),
        lang: str = Form("en"),
        domain: str = Form("cs_ml"),
        output: str = Form("both"),
        pages: str = Form(""),
        reextract_glossary: bool = Form(False),
        ocr: bool = Form(False),
        review: bool = Form(False),
        glossary: UploadFile | None = File(None),
    ):
        data = await file.read(MAX_PDF_BYTES + 1)
        if len(data) > MAX_PDF_BYTES:
            raise HTTPException(413, "PDF는 100MB 이하만 올릴 수 있습니다.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "PDF 파일이 아닙니다.")
        if model not in MODELS:
            raise HTTPException(400, f"알 수 없는 모델: {model}")
        if lang not in LANG_NAMES:
            raise HTTPException(400, f"지원하지 않는 원문 언어: {lang}")
        if output not in ("both", "mono", "dual"):
            raise HTTPException(400, f"알 수 없는 출력 형식: {output}")
        if domain not in ("none", *(p.stem for p in GLOSSARY_DIR.glob("*.csv"))):
            raise HTTPException(400, f"알 수 없는 분야 용어집: {domain}")
        pages = pages.strip()
        if pages and not all(c.isdigit() or c in ",- " for c in pages):
            raise HTTPException(400, "페이지는 1-3,5 형식으로 입력하세요.")
        gbytes = None
        if glossary is not None and glossary.filename:
            gbytes = await glossary.read(2 * 1024 * 1024)
        opts = {"model": model, "lang": lang, "domain": domain, "output": output, "pages": pages.replace(" ", ""),
                "reextract_glossary": reextract_glossary, "ocr": ocr, "review": review}
        return jobs.create(file.filename or "paper.pdf", data, opts, gbytes)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        if not jobs.cancel(job_id):
            raise HTTPException(409, "취소할 수 없는 상태입니다.")
        return jobs.get(job_id)

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str):
        if not jobs.delete(job_id):
            raise HTTPException(409, "진행 중인 작업은 삭제할 수 없습니다.")
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry")
    async def retry_job(job_id: str):
        job = jobs.retry(job_id)
        if not job:
            raise HTTPException(409, "다시 번역할 수 없는 작업입니다.")
        return job

    def _pid(paper_id: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{12}", paper_id):
            raise HTTPException(400, "잘못된 논문 ID입니다.")
        return paper_id

    @app.get("/api/papers/{paper_id}/glossary")
    async def get_glossary(paper_id: str):
        pid = _pid(paper_id)
        edited, auto = gl.user_path(pid), gl.paper_path(pid)
        src = edited if edited.exists() else auto
        if not src.exists():
            raise HTTPException(404, "이 논문의 용어집이 아직 없습니다. 전체 페이지를 한 번 번역하면 만들어집니다.")
        return {"paper_id": pid, "edited": edited.exists(), "entries": gl.read(src)}

    @app.put("/api/papers/{paper_id}/glossary")
    async def put_glossary(paper_id: str, payload: dict = Body(...)):
        pid = _pid(paper_id)
        try:
            rows = gl.validate(payload.get("entries"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        gl.write(gl.user_path(pid), rows)
        return {"paper_id": pid, "edited": True, "count": len(rows)}

    @app.delete("/api/papers/{paper_id}/glossary")
    async def reset_glossary(paper_id: str):
        gl.user_path(_pid(paper_id)).unlink(missing_ok=True)
        return {"ok": True}

    @app.get("/api/usage")
    async def get_usage():
        return usage.summarize()

    @app.get("/api/jobs/{job_id}/files/{kind}")
    async def download(job_id: str, kind: str, inline: bool = False):
        p = jobs.file_path(job_id, kind)
        if not p:
            raise HTTPException(404, "파일이 없습니다.")
        media = "text/csv" if p.suffix == ".csv" else "application/pdf"
        return FileResponse(p, media_type=media, filename=p.name,
                            content_disposition_type="inline" if inline else "attachment")

    return app
