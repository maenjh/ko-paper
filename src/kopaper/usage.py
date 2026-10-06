"""Summaries of Claude calls made through the proxy (from data/proxy_usage.jsonl).

These are local measurements. The subscription's own remaining quota is not exposed to the CLI.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import DATA_DIR

LOG = DATA_DIR / "proxy_usage.jsonl"
WINDOWS = {"h5": 5 * 3600, "d7": 7 * 86400}


def summarize(log: Path = LOG, now: float | None = None) -> dict:
    now = now or time.time()
    out = {k: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "limit_errors": 0, "errors": 0,
               "by_model": {}} for k in WINDOWS}
    last_limit = None
    if log.exists():
        with log.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                age = now - r.get("ts", 0)
                if "error" in r and r.get("error") == 429:
                    last_limit = max(last_limit or 0, r["ts"])
                for k, span in WINDOWS.items():
                    if age > span:
                        continue
                    w = out[k]
                    if "error" in r:
                        w["errors"] += 1
                        w["limit_errors"] += r.get("error") == 429
                    elif r.get("cache_hit"):
                        w["cache_hits"] += 1
                    else:
                        w["calls"] += 1
                        w["input_tokens"] += r.get("prompt_tokens", 0)
                        w["output_tokens"] += r.get("completion_tokens", 0)
                        m = w["by_model"].setdefault(r.get("model", "?"), 0)
                        w["by_model"][r.get("model", "?")] = m + 1
    out["last_limit_error"] = last_limit
    out["limited_now"] = bool(last_limit and now - last_limit < 120)
    return out
