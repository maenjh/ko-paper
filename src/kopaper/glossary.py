"""Glossary handling: curated domain glossaries + saved per-paper glossaries (BabelDOC CSV format)."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .config import GLOSSARY_DIR, PAPER_GLOSSARY_DIR

FIELDS = ["source", "target", "tgt_lng"]


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [
            {"source": r["source"].strip(), "target": (r.get("target") or "").strip(), "tgt_lng": (r.get("tgt_lng") or "").strip()}
            for r in csv.DictReader(f)
            if r.get("source") and r["source"].strip()
        ]


def write(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def merge(*sources: list[dict]) -> list[dict]:
    """Merge glossaries; earlier sources win on the same (case-insensitive) source term."""
    seen: dict[str, dict] = {}
    for rows in sources:
        for r in rows:
            k = r["source"].lower()
            if k not in seen and r["target"]:
                seen[k] = r
    return sorted(seen.values(), key=lambda r: r["source"].lower())


def domain_path(domain: str) -> Path:
    p = GLOSSARY_DIR / f"{domain}.csv"
    if not p.exists():
        names = ", ".join(sorted(x.stem for x in GLOSSARY_DIR.glob("*.csv")))
        raise FileNotFoundError(f"no domain glossary '{domain}' (available: {names})")
    return p


def paper_path(paper_id: str) -> Path:
    return PAPER_GLOSSARY_DIR / f"{paper_id}.csv"


def user_path(paper_id: str) -> Path:
    """Glossary edited by the user for one paper. Replaces the auto-extracted one when present."""
    return PAPER_GLOSSARY_DIR / f"{paper_id}.user.csv"


# Venue, institution, and publisher names should stay in their original form.
_PROPER = re.compile(
    r"\b(Conference|Proceedings|Symposium|Journal|Transactions|Workshop|University|Institute|"
    r"Association|Society|Press|Inc|Ltd|Foundation|Laboratory|Lab)\b"
)


def drop_proper_nouns(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not _PROPER.search(r["source"])]


def validate(entries: list) -> list[dict]:
    """Validate glossary entries coming from the web UI."""
    if not isinstance(entries, list) or len(entries) > 5000:
        raise ValueError("용어는 5000개까지 저장할 수 있습니다.")
    rows = []
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError("잘못된 형식입니다.")
        src = str(e.get("source", "")).strip()
        tgt = str(e.get("target", "")).strip()
        if not src:
            continue
        if len(src) > 200 or len(tgt) > 200 or "\n" in src + tgt:
            raise ValueError(f"용어가 너무 길거나 줄바꿈이 있습니다: {src[:40]}")
        rows.append({"source": src, "target": tgt, "tgt_lng": ""})
    return merge(rows)
