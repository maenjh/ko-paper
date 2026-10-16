"""Persistent job queue for the web UI. One translation runs at a time (subscription limits)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

from .. import pipeline
from ..config import DATA_DIR

WEB_DIR = DATA_DIR / "web"
DB_PATH = DATA_DIR / "web_jobs.sqlite"

STAGE_KO = {
    "준비 중": "준비 중",
    "OCR": "글자 인식",
    "DetectScannedFile": "스캔본 확인",
    "Parse PDF and Create Intermediate Representation": "PDF 분석",
    "Parse Page Layout": "레이아웃 인식",
    "Parse Paragraphs": "문단 분석",
    "Parse Formulas and Styles": "수식·서식 분석",
    "Automatic Term Extraction": "용어 추출",
    "Translate Paragraphs": "번역",
    "Typesetting": "조판",
    "Add Fonts": "폰트 추가",
    "Generate drawing instructions": "그리기",
    "Subset font": "폰트 정리",
    "Save PDF": "PDF 저장",
    "완료": "완료",
    "실패": "실패",
}

COLUMNS = ["id", "name", "status", "stage", "progress", "options", "result", "error",
           "created", "started", "finished"]


class JobManager:
    def __init__(self, db_path: Path = DB_PATH, work_dir: Path = WEB_DIR, translate=None):
        self.db_path = db_path
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.translate = translate or pipeline.translate_pdf
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._cancel: dict[str, threading.Event] = {}
        self._live: dict[str, tuple[str, float]] = {}
        with self._db() as con:
            con.execute(f"CREATE TABLE IF NOT EXISTS jobs ({', '.join(c + ' TEXT' for c in COLUMNS)})")
            # A restart kills any running BabelDOC process.
            con.execute("UPDATE jobs SET status='failed', error='서버 재시작으로 중단됨' WHERE status='running'")

    def _db(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _update(self, job_id: str, **fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._db() as con:
            con.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))

    # ---- public API ----
    def create(self, name: str, pdf_bytes: bytes, options: dict, glossary_bytes: bytes | None = None) -> dict:
        job_id = uuid.uuid4().hex[:12]
        options = {**options, "paper_id": hashlib.sha256(pdf_bytes).hexdigest()[:12]}
        d = self.work_dir / job_id
        d.mkdir(parents=True)
        stem = _safe_stem(name)
        (d / f"{stem}.pdf").write_bytes(pdf_bytes)
        if glossary_bytes:
            (d / "user_glossary.csv").write_bytes(glossary_bytes)
            options = {**options, "user_glossary": True}
        with self._lock, self._db() as con:
            con.execute(f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                        (job_id, f"{stem}.pdf", "queued", "대기 중", "0", json.dumps(options, ensure_ascii=False),
                         None, None, str(time.time()), None, None))
        self._wake.set()
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._db() as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._view(row) if row else None

    def list(self) -> list[dict]:
        with self._db() as con:
            rows = con.execute("SELECT * FROM jobs ORDER BY CAST(created AS REAL) DESC LIMIT 200").fetchall()
        return [self._view(r) for r in rows]

    def retry(self, job_id: str) -> dict | None:
        """Queue a new job with the same PDF and options (e.g. after editing the glossary)."""
        job = self.get(job_id)
        if not job or job["status"] in ("queued", "running"):
            return None
        d = self.work_dir / job_id
        pdf = d / job["name"]
        if not pdf.exists():
            return None
        g = d / "user_glossary.csv"
        opts = {k: v for k, v in job["options"].items() if k not in ("paper_id", "user_glossary")}
        return self.create(job["name"], pdf.read_bytes(), opts, g.read_bytes() if g.exists() else None)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job["status"] not in ("queued", "running"):
            return False
        if job["status"] == "queued":
            self._update(job_id, status="cancelled", stage="취소됨", finished=str(time.time()))
        elif (ev := self._cancel.get(job_id)):
            ev.set()
        return True

    def delete(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job["status"] == "running":
            return False
        with self._lock, self._db() as con:
            con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        shutil.rmtree(self.work_dir / job_id, ignore_errors=True)
        return True

    def file_path(self, job_id: str, kind: str) -> Path | None:
        job = self.get(job_id)
        if not job or not job.get("result"):
            return None
        key = {"mono": "mono_pdf", "dual": "dual_pdf", "glossary": "paper_glossary"}.get(kind)
        p = job["result"].get(key) if key else None
        return Path(p) if p and Path(p).exists() else None

    # ---- worker ----
    def start_worker(self) -> threading.Thread:
        t = threading.Thread(target=self._loop, daemon=True, name="kopaper-worker")
        t.start()
        return t

    def _loop(self) -> None:
        while True:
            if not self.run_next():
                self._wake.wait(timeout=2)
                self._wake.clear()

    def run_next(self) -> bool:
        with self._db() as con:
            row = con.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY CAST(created AS REAL) LIMIT 1").fetchone()
        if not row:
            return False
        self._run(row["id"])
        return True

    def _claim(self, job_id: str) -> bool:
        """queued → running in one statement, so a cancel that just landed wins."""
        with self._lock, self._db() as con:
            cur = con.execute("UPDATE jobs SET status='running', stage='준비 중', started=? WHERE id=? AND status='queued'",
                              (str(time.time()), job_id))
            return cur.rowcount == 1

    def _run(self, job_id: str) -> None:
        if not self._claim(job_id):
            return
        job = self.get(job_id)
        d = self.work_dir / job_id
        o = job["options"]
        opts = pipeline.Options(
            model=o.get("model", "sonnet"),
            lang_in=o.get("lang", "en"),
            domain=None if o.get("domain") in (None, "", "none") else o["domain"],
            user_glossaries=[d / "user_glossary.csv"] if o.get("user_glossary") else [],
            pages=o.get("pages") or None,
            mono=o.get("output", "both") in ("both", "mono"),
            dual=o.get("output", "both") in ("both", "dual"),
            reextract_glossary=bool(o.get("reextract_glossary")),
            ocr=bool(o.get("ocr")),
            review=bool(o.get("review")),
        )
        cancel = self._cancel[job_id] = threading.Event()
        last = [0.0]

        def progress(stage: str, pct: float) -> None:
            self._live[job_id] = (stage, pct)
            if time.time() - last[0] > 3:  # persist occasionally; live values are served from memory
                last[0] = time.time()
                self._update(job_id, stage=STAGE_KO.get(stage, stage), progress=f"{pct:.1f}")

        try:
            res = self.translate(d / job["name"], d / "out", opts, on_progress=progress, cancel=cancel)
            # BabelDOC exits 0 even when every call failed; then the PDF is still untranslated.
            all_failed = res.errors and not res.calls
            ok = res.returncode == 0 and (res.mono_pdf or res.dual_pdf) and not all_failed
            error = (f"번역 호출 {res.errors}회가 모두 실패했습니다. 로그인 상태를 확인하세요. 로그: {res.job_dir}"
                     if all_failed else f"BabelDOC 종료 코드 {res.returncode}. 로그: {res.job_dir}/babeldoc.log")
            self._update(job_id, status="done" if ok else "failed", stage="완료" if ok else "실패",
                         progress="100" if ok else f"{self._live.get(job_id, ('', 0))[1]:.1f}",
                         result=json.dumps(asdict(res), default=str, ensure_ascii=False),
                         error=None if ok else error,
                         finished=str(time.time()))
        except pipeline.Cancelled:
            self._update(job_id, status="cancelled", stage="취소됨", finished=str(time.time()))
        except Exception as e:  # keep the worker alive
            self._update(job_id, status="failed", stage="실패", error=f"{type(e).__name__}: {e}",
                         finished=str(time.time()))
            traceback.print_exc()
        finally:
            self._cancel.pop(job_id, None)
            self._live.pop(job_id, None)

    def _view(self, row: sqlite3.Row) -> dict:
        j = dict(row)
        j["options"] = json.loads(j["options"] or "{}")
        j["result"] = json.loads(j["result"]) if j["result"] else None
        for k in ("created", "started", "finished"):
            j[k] = float(j[k]) if j[k] else None
        j["progress"] = float(j["progress"] or 0)
        if j["status"] == "running" and j["id"] in self._live:
            stage, pct = self._live[j["id"]]
            j["stage"], j["progress"] = STAGE_KO.get(stage, stage), round(pct, 1)
        if j["status"] == "queued":
            with self._db() as con:
                j["queue_position"] = con.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND CAST(created AS REAL) < ?",
                    (j["created"],)).fetchone()[0] + 1
        return j


def _safe_stem(name: str) -> str:
    stem = Path(name).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = "".join(c for c in stem if c not in '/\\:*?"<>|\x00').strip(" .")
    return (stem or "paper")[:120]
