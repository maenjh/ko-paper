#!/usr/bin/env bash
# Run kopaper from this checkout, setting it up on first use.
#   kopaper.sh doctor            check prerequisites, install what can be installed
#   kopaper.sh update            pull the latest ko-paper and refresh installed skills
#   kopaper.sh translate a.pdf   any other arguments go to the kopaper CLI
#   kopaper.sh                   no arguments: open the web UI in the browser
set -euo pipefail

# Find the checkout: $KOPAPER_HOME, else the path install.sh wrote next to a copied skill,
# else the repo this script sits in (plugin install, or a symlinked skill folder).
HERE="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${KOPAPER_HOME:-}" ]; then
  ROOT="$KOPAPER_HOME"
elif [ -f "$HERE/../.kopaper-home" ]; then
  ROOT="$(cat "$HERE/../.kopaper-home")"
else
  ROOT="$(cd "$HERE/../../.." && pwd)"
fi
# uv tool installs babeldoc here; shells set up by Homebrew's uv may not have it on PATH.
export PATH="$HOME/.local/bin:$PATH"
# Keep caches and glossaries outside the checkout so plugin updates don't wipe them.
export KOPAPER_DATA="${KOPAPER_DATA:-$HOME/.ko-paper/data}"
export PYTHONUTF8=1  # localized (e.g. Korean) Windows error text comes through readable

need() { command -v "$1" >/dev/null 2>&1; }

# Backend: $KOPAPER_BACKEND, else the one picked at install (~/.ko-paper/backend),
# else Claude Code when it is the only CLI or is logged in, else Codex.
BACKEND_FILE="$HOME/.ko-paper/backend"
if [ -z "${KOPAPER_BACKEND:-}" ] && [ -s "$BACKEND_FILE" ]; then KOPAPER_BACKEND="$(cat "$BACKEND_FILE")"; fi
if [ -z "${KOPAPER_BACKEND:-}" ]; then
  if need claude && { ! need codex || [ -n "${ANTHROPIC_API_KEY:-}" ] || claude auth status >/dev/null 2>&1; }; then
    KOPAPER_BACKEND=claude-code
  elif need codex; then KOPAPER_BACKEND=codex
  fi
fi
export KOPAPER_BACKEND="${KOPAPER_BACKEND:-}"

venv_python() {  # Scripts\python.exe under Git Bash on Windows
  if [ -f "$ROOT/.venv/Scripts/python.exe" ]; then echo "$ROOT/.venv/Scripts/python.exe"; else echo "$ROOT/.venv/bin/python"; fi
}
babeldoc_python() {
  local d; d="$(uv tool dir 2>/dev/null)"
  if need cygpath; then d="$(cygpath -u "$d")"; fi
  if [ -f "$d/babeldoc/Scripts/python.exe" ]; then echo "$d/babeldoc/Scripts/python.exe"; else echo "$d/babeldoc/bin/python"; fi
}

setup() {
  local ok=1
  if ! need uv; then
    echo "✗ uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; ok=0
  fi
  case "${KOPAPER_BACKEND:-}" in
    claude-code|codex|anthropic-api) ;;
    "") echo "✗ neither Claude Code (claude) nor Codex (codex) is installed; install and log in to one" >&2; ok=0 ;;
    *) echo "✗ unknown KOPAPER_BACKEND=$KOPAPER_BACKEND (claude-code, codex, anthropic-api)" >&2; ok=0 ;;
  esac
  if [ "${KOPAPER_BACKEND:-}" = "claude-code" ] && ! need claude; then
    echo "✗ KOPAPER_BACKEND=claude-code but the claude CLI is missing" >&2; ok=0
  fi
  if [ "${KOPAPER_BACKEND:-}" = "codex" ] && ! need codex; then
    echo "✗ KOPAPER_BACKEND=codex but the codex CLI is missing" >&2; ok=0
  fi
  [ "$ok" = 1 ] || exit 1
  if ! need babeldoc && [ -z "${KOPAPER_BABELDOC_BIN:-}" ]; then
    echo "→ installing BabelDOC (uv tool install babeldoc)" >&2
    # 3.12: the most common build of every compiled dependency, so the best reputation with
    # Windows Smart App Control. BabelDOC doesn't support 3.14 anyway.
    uv tool install --python 3.12 babeldoc >&2
  fi
  # Always sync: after an update the editable install has new code but maybe not its new dependencies.
  # --inexact keeps the optional `api` extra if someone installed it.
  (cd "$ROOT" && uv sync --quiet --inexact) >&2
}

if [ "${1:-}" = "update" ]; then
  # Pull the latest version and refresh the installed skill copies.
  # Only for copies made by install.sh: it force-checks-out $ROOT, which must not hit a dev checkout.
  if [ -f "$HERE/../.kopaper-home" ] && [ -f "$ROOT/install.sh" ] && [ -d "$ROOT/.git" ]; then
    KOPAPER_SRC="$ROOT" exec bash "$ROOT/install.sh"
  fi
  echo "✗ not installed by install.sh; re-run it, or update the plugin with /plugin" >&2
  exit 1
fi

logged_in() {
  case "$KOPAPER_BACKEND" in
    # claude -p also runs on ANTHROPIC_API_KEY, so don't send the user to a browser login for nothing.
    claude-code) [ -n "${ANTHROPIC_API_KEY:-}" ] || claude auth status >/dev/null 2>&1 ;;
    codex) codex login status >/dev/null 2>&1 ;;
    *) true ;;
  esac
}

native_fail() {  # $1 = which environment, $2 = python's output
  echo "✗ $1 could not load its compiled modules:" >&2
  printf '%s\n' "$2" | grep -iE "error" | head -3 | sed 's/^/    /' >&2
  if printf '%s' "$2" | grep -qiE "4551|application control|애플리케이션 제어"; then
    echo "  Windows Smart App Control blocked an unsigned file. Don't turn it off:" >&2
    echo "  see https://github.com/maenjh/ko-paper#windows-smart-app-control" >&2
  fi
  echo "  Lite mode still works without these modules (no layout): see lite.md in the skill folder." >&2
  exit 1
}

# Import the compiled modules once: Smart App Control blocks unsigned ones only when they load.
native_check() {
  local out
  out="$("$(venv_python)" -c "import pymupdf" 2>&1)" || native_fail "ko-paper" "$out"
  if [ -z "${KOPAPER_BABELDOC_BIN:-}" ]; then
    out="$("$(babeldoc_python)" -c "import pymupdf, onnxruntime, cv2, numpy, babeldoc.format.pdf.high_level" 2>&1)" \
      || native_fail "BabelDOC" "$out"
  fi
}

if [ "${1:-}" = "doctor" ]; then
  setup
  native_check
  if ! logged_in; then
    case "$KOPAPER_BACKEND" in
      claude-code) echo "✗ Claude Code is installed but not logged in. Run: claude auth login" >&2 ;;
      codex) echo "✗ Codex is installed but not logged in. Run: codex login" >&2 ;;
    esac
    exit 1
  fi
  echo "✓ kopaper ready  root=$ROOT  data=$KOPAPER_DATA"
  echo "  babeldoc: $(command -v babeldoc || echo "${KOPAPER_BABELDOC_BIN:-?}")"
  echo "  backend:  $KOPAPER_BACKEND"
  exit 0
fi

[ -x "$(venv_python)" ] && need babeldoc || setup
[ $# -gt 0 ] || set -- serve --open
# python -m, not the venv's kopaper.exe: that file is generated per install, so Smart App Control
# never knows it.
exec "$(venv_python)" -m kopaper "$@"
