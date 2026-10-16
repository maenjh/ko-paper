#!/usr/bin/env bash
# Install ko-paper as a Claude Code skill without the plugin system.
#   curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
# The repo is cloned to ~/.ko-paper/src and the skill folder is symlinked into ~/.claude/skills.
set -euo pipefail

REPO="${KOPAPER_REPO:-https://github.com/maenjh/ko-paper.git}"
REF="${KOPAPER_REF:-main}"
SRC="${KOPAPER_SRC:-$HOME/.ko-paper/src}"
DEST="${KOPAPER_SKILL_DEST:-$HOME/.claude/skills/ko-paper}"

command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

if [ -d "$SRC/.git" ]; then
  echo "Updating $SRC..."
  git -C "$SRC" fetch --depth 1 --quiet origin "$REF"
  git -C "$SRC" checkout --quiet FETCH_HEAD
else
  echo "Cloning $REPO ($REF) into $SRC..."
  mkdir -p "$(dirname "$SRC")"
  git clone --depth 1 --branch "$REF" --quiet "$REPO" "$SRC"
fi

if [ -e "$DEST" ] && [ ! -L "$DEST" ]; then
  BACKUP="$DEST.backup-$(date +%Y%m%d-%H%M%S)"
  echo "Existing skill found; moving it to $BACKUP"
  mv "$DEST" "$BACKUP"
fi
mkdir -p "$(dirname "$DEST")"
ln -sfn "$SRC/skills/ko-paper" "$DEST"
echo "Skill linked: $DEST -> $SRC/skills/ko-paper"

"$SRC/skills/ko-paper/scripts/kopaper.sh" doctor
