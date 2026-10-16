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

need() { command -v "$1" >/dev/null 2>&1; }

# Backend: Claude Code if it is installed, otherwise Codex. KOPAPER_BACKEND overrides.
if [ -z "${KOPAPER_BACKEND:-}" ]; then
  if need claude; then export KOPAPER_BACKEND=claude-code
  elif need codex; then export KOPAPER_BACKEND=codex
  fi
fi

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
    uv tool install babeldoc >&2
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
    # An API key in the environment also works, so don't send the user to a browser login for nothing.
    claude-code) [ -n "${ANTHROPIC_API_KEY:-}" ] || claude auth status >/dev/null 2>&1 ;;
    codex) [ -n "${OPENAI_API_KEY:-}" ] || codex login status >/dev/null 2>&1 ;;
    *) true ;;
  esac
}

if [ "${1:-}" = "doctor" ]; then
  setup
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

kp() {  # the venv's kopaper; Scripts/kopaper.exe under Git Bash on Windows
  if [ -f "$ROOT/.venv/Scripts/kopaper.exe" ]; then echo "$ROOT/.venv/Scripts/kopaper.exe"; else echo "$ROOT/.venv/bin/kopaper"; fi
}
[ -x "$(kp)" ] && need babeldoc || setup
[ $# -gt 0 ] || set -- serve --open
exec "$(kp)" "$@"
