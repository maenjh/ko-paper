"""OpenAI-compatible /v1/chat/completions proxy in front of a Claude backend.

BabelDOC talks to this as if it were OpenAI. Responses are cached in SQLite and usage is logged to JSONL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..config import BACKEND, DATA_DIR, PROXY_HOST, PROXY_PORT
from .backends import BackendError, make_backend

CACHE_DB = DATA_DIR / "proxy_cache.sqlite"
USAGE_LOG = DATA_DIR / "proxy_usage.jsonl"
MAX_CONCURRENCY = int(os.environ.get("KOPAPER_MAX_CONCURRENCY", "4"))

BASE_SYSTEM = (
    "You are a professional translator of academic papers from English into Korean. "
    "Follow the user's instructions exactly. "
    "Output only what is requested, with no commentary."
)
JSON_SUFFIX = " Respond with valid JSON only. Do not wrap it in code fences."
REVIEW_SYSTEM = (
    "You are the reviewing editor of an English-to-Korean academic translation. You receive the original "
    "translation task and a draft answer. Fix mistranslations, omissions, additions, inconsistent terminology, "
    "and Korean translationese. Keep everything else identical: the same output format, the same ids, every "
    "placeholder, tag, formula, and citation marker. Keep the length close to the draft. "
    "Output only the corrected answer in the exact format the task requires."
)
REVIEW_SUFFIX = "+review"
_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.S)


def flatten_messages(messages: list[dict]) -> tuple[str, str]:
    """Split OpenAI chat messages into (system text, user prompt)."""
    sys_parts, convo = [], []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        c = c or ""
        if m.get("role") == "system":
            sys_parts.append(c)
        elif m.get("role") == "user":
            convo.append(c)
        else:
            convo.append(f"[{m.get('role')}]\n{c}")
    return "\n\n".join(sys_parts), "\n\n".join(convo)


def strip_fence(text: str) -> str:
    m = _FENCE.match(text.strip())
    return m.group(1) if m else text


def _same_shape(draft: str, revised: str) -> bool:
    """Accept a review only if it keeps the draft's JSON structure (same ids) when the draft is JSON."""
    try:
        d = json.loads(draft)
    except (json.JSONDecodeError, ValueError):
        return True
    try:
        r = json.loads(revised)
    except (json.JSONDecodeError, ValueError):
        return False
    ids = lambda x: [i.get("id") for i in x] if isinstance(x, list) and all(isinstance(i, dict) for i in x) else None  # noqa: E731
    return type(d) is type(r) and ids(d) == ids(r)


class Cache:
    def __init__(self, path):
        self.path = path
        with self._con() as con:
            con.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, created REAL)")

    def _con(self):
        return sqlite3.connect(self.path)

    def get(self, k: str) -> str | None:
        with self._con() as con:
            row = con.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def put(self, k: str, v: str) -> None:
        with self._con() as con:
            con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (k, v, time.time()))


def create_app(backend_name: str = BACKEND) -> FastAPI:
    app = FastAPI()
    backend = make_backend(backend_name)
    cache = Cache(CACHE_DB)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "backend": backend.name,
                "data": [{"id": m, "object": "model"} for m in ("sonnet", "opus", "haiku")]}

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        model = body.get("model") or "sonnet"
        review = model.endswith(REVIEW_SUFFIX)
        if review:
            model = model[: -len(REVIEW_SUFFIX)] or "sonnet"
        extra_sys, prompt = flatten_messages(body.get("messages", []))
        json_mode = (body.get("response_format") or {}).get("type") == "json_object"
        system = BASE_SYSTEM + ("\n\n" + extra_sys if extra_sys else "") + (JSON_SUFFIX if json_mode else "")

        key = hashlib.sha256(json.dumps([backend.name, model, system, prompt, review]).encode()).hexdigest()
        t0 = time.time()
        tin = tout = 0
        text = cache.get(key)
        hit = text is not None
        if not hit:
            try:
                async with sem:
                    c = await backend.complete(system, prompt, model)
            except BackendError as e:
                _log({"ts": t0, "model": model, "error": e.status, "msg": e.message[:200]})
                # 429 makes BabelDOC's OpenAI client back off and retry.
                return JSONResponse({"error": {"message": e.message, "type": "backend_error"}}, status_code=e.status)
            text, tin, tout = strip_fence(c.text), c.input_tokens, c.output_tokens
            if review:
                rprompt = f"## Original task\n\n{prompt}\n\n## Draft answer\n\n{text}"
                rsys = REVIEW_SYSTEM + ("\n\n" + extra_sys if extra_sys else "") + (JSON_SUFFIX if json_mode else "")
                try:
                    async with sem:
                        c2 = await backend.complete(rsys, rprompt, model)
                    revised = strip_fence(c2.text).strip()
                    tin, tout = tin + c2.input_tokens, tout + c2.output_tokens
                    if revised and _same_shape(text, revised):
                        text = revised
                except BackendError:
                    pass  # keep the draft; the review is best-effort
            cache.put(key, text)

        _log({"ts": t0, "ms": int((time.time() - t0) * 1000), "backend": backend.name, "model": model, "review": review,
              "cache_hit": hit, "json_mode": json_mode, "prompt_chars": len(prompt), "out_chars": len(text),
              "prompt_tokens": tin, "completion_tokens": tout})
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(t0), "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": tin, "completion_tokens": tout, "total_tokens": tin + tout},
        })

    return app


def _log(row: dict) -> None:
    with USAGE_LOG.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    import uvicorn
    uvicorn.run(create_app(), host=PROXY_HOST, port=PROXY_PORT)


if __name__ == "__main__":
    main()
