#!/usr/bin/env bash
# Install ko-paper as a skill for Claude Code and/or Codex.
#   curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
#   ... | bash -s -- --claude      only Claude Code (~/.claude/skills)
#   ... | bash -s -- --codex       only Codex ($CODEX_HOME/skills, default ~/.codex/skills)
# Without a flag it installs for every agent found on this machine.
# The repo lives in ~/.ko-paper/src; each agent gets a copy of skills/ko-paper that points back to it.
# Re-running updates everything.
set -euo pipefail

main() {
  REPO="${KOPAPER_REPO:-https://github.com/maenjh/ko-paper.git}"
  REF="${KOPAPER_REF:-main}"
  SRC="${KOPAPER_SRC:-$HOME/.ko-paper/src}"
  CLAUDE_SKILLS="$HOME/.claude/skills"
  CODEX_SKILLS="${CODEX_HOME:-$HOME/.codex}/skills"

  want_claude=0 want_codex=0
  for a in "$@"; do
    case "$a" in
      --claude) want_claude=1 ;;
      --codex) want_codex=1 ;;
      --all) want_claude=1 want_codex=1 ;;
      *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
  done
  if [ "$want_claude$want_codex" = "00" ]; then
    { [ -d "$HOME/.claude" ] || command -v claude >/dev/null; } && want_claude=1
    { [ -d "${CODEX_HOME:-$HOME/.codex}" ] || command -v codex >/dev/null; } && want_codex=1
    [ "$want_claude$want_codex" = "00" ] && want_claude=1
  fi

  command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

  if [ -d "$SRC/.git" ]; then
    echo "Updating $SRC..."
    git -C "$SRC" fetch --depth 1 --quiet origin "$REF"
    git -C "$SRC" checkout --quiet --force FETCH_HEAD
  else
    echo "Cloning $REPO ($REF) into $SRC..."
    mkdir -p "$(dirname "$SRC")"
    git clone --depth 1 --branch "$REF" --quiet "$REPO" "$SRC"
  fi

  install_to() {  # $1 = skills directory
    local dest="$1/ko-paper"
    mkdir -p "$1"
    if [ -L "$dest" ]; then
      rm "$dest"
    elif [ -d "$dest" ] && [ ! -f "$dest/.kopaper-home" ]; then
      local backup="$dest.backup-$(date +%Y%m%d-%H%M%S)"
      echo "  existing $dest is not ours; moving it to $backup"
      mv "$dest" "$backup"
    fi
    rm -rf "$dest"
    cp -R "$SRC/skills/ko-paper" "$dest"
    printf '%s\n' "$SRC" > "$dest/.kopaper-home"
    echo "  skill installed: $dest"
  }

  [ "$want_claude" = 1 ] && install_to "$CLAUDE_SKILLS"
  [ "$want_codex" = 1 ] && install_to "$CODEX_SKILLS"

  "$SRC/skills/ko-paper/scripts/kopaper.sh" doctor
  echo "Done. Restart Claude Code / Codex, then ask: \"이 논문 번역해줘 /path/to/paper.pdf\""
}

# Wrapped in a function so bash has parsed everything before the checkout below rewrites this file.
main "$@"
