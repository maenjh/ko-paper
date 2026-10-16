"""Shared paths and settings (env-overridable)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("KOPAPER_DATA", ROOT / "data"))
PROMPTS_DIR = ROOT / "prompts"
GLOSSARY_DIR = ROOT / "glossary"            # curated, shipped domain glossaries
PAPER_GLOSSARY_DIR = DATA_DIR / "glossaries"  # auto-extracted per-paper glossaries
JOBS_DIR = DATA_DIR / "jobs"

PROXY_HOST = "127.0.0.1"
PROXY_PORT = int(os.environ.get("KOPAPER_PORT", "8787"))
PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}/v1"

# "claude-code" = Claude subscription via local `claude -p` (personal use only)
# "anthropic-api" = pay-as-you-go API key (required for any shared/public deployment)
BACKEND = os.environ.get("KOPAPER_BACKEND", "claude-code")
BABELDOC_BIN = os.environ.get("KOPAPER_BABELDOC_BIN", "babeldoc")

# Source languages a paper can be in. The output is always Korean.
SOURCE_LANGS = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "ru": "Russian", "ja": "Japanese", "zh": "Chinese",
}

for d in (DATA_DIR, PAPER_GLOSSARY_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)
