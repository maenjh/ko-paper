#!/usr/bin/env bash
# Run kopaper from this checkout, setting it up on first use.
#   kopaper.sh doctor            check prerequisites, install what can be installed
#   kopaper.sh update            pull the latest ko-paper and refresh installed skills
#   kopaper.sh translate a.pdf   any other arguments go to the kopaper CLI
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
# Keep caches and glossaries outside the checkout so plugin updates don't wipe them.
export KOPAPER_DATA="${KOPAPER_DATA:-$HOME/.ko-paper/data}"

need() { command -v "$1" >/dev/null 2>&1; }

setup() {
  local ok=1
  if ! need uv; then
    echo "✗ uv is missing: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; ok=0
  fi
  if ! need claude && [ "${KOPAPER_BACKEND:-claude-code}" = "claude-code" ]; then
    echo "✗ Claude Code CLI (claude) is missing and KOPAPER_BACKEND is claude-code" >&2; ok=0
  fi
  [ "$ok" = 1 ] || exit 1
  if ! need babeldoc && [ -z "${KOPAPER_BABELDOC_BIN:-}" ]; then
    echo "→ installing BabelDOC (uv tool install babeldoc)" >&2
    uv tool install babeldoc >&2
  fi
  if [ ! -x "$ROOT/.venv/bin/kopaper" ]; then
    echo "→ installing kopaper into $ROOT/.venv (uv sync)" >&2
    (cd "$ROOT" && uv sync --quiet) >&2
  fi
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

if [ "${1:-}" = "doctor" ]; then
  setup
  echo "✓ kopaper ready  root=$ROOT  data=$KOPAPER_DATA"
  echo "  babeldoc: $(command -v babeldoc || echo "${KOPAPER_BABELDOC_BIN:-?}")"
  echo "  backend:  ${KOPAPER_BACKEND:-claude-code}"
  exit 0
fi

[ -x "$ROOT/.venv/bin/kopaper" ] && need babeldoc || setup
exec "$ROOT/.venv/bin/kopaper" "$@"
