#!/usr/bin/env bash
# Install ko-paper (macOS, Linux, WSL).
#   curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
#   ... | bash -s -- --with-claude-code   also install Claude Code (for Claude subscribers)
#   ... | bash -s -- --with-codex         also install Codex CLI (for ChatGPT subscribers)
#   ... | bash -s -- --claude | --codex   install the skill only for that agent
#
# What it does:
#   - installs uv if missing, clones the repo to ~/.ko-paper/src (re-running updates it)
#   - copies the skill into Claude Code (~/.claude/skills) and/or Codex ($CODEX_HOME/skills) when present
#   - puts a `ko-paper` command in ~/.local/bin: no arguments opens the web UI, or `ko-paper translate a.pdf`
#   - checks BabelDOC and the translation backend (Claude Code or Codex, logged in)
set -euo pipefail

main() {
  REPO="${KOPAPER_REPO:-https://github.com/maenjh/ko-paper.git}"
  REF="${KOPAPER_REF:-main}"
  SRC="${KOPAPER_SRC:-$HOME/.ko-paper/src}"
  BIN_DIR="${KOPAPER_BIN_DIR:-$HOME/.local/bin}"
  CLAUDE_SKILLS="$HOME/.claude/skills"
  CODEX_SKILLS="${CODEX_HOME:-$HOME/.codex}/skills"
  export PATH="$BIN_DIR:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

  want_claude=0 want_codex=0 with_claude_code=0 with_codex=0
  for a in "$@"; do
    case "$a" in
      --claude) want_claude=1 ;;
      --codex) want_codex=1 ;;
      --all) want_claude=1 want_codex=1 ;;
      --with-claude-code) with_claude_code=1 ;;
      --with-codex) with_codex=1 ;;
      *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
  done

  command -v git >/dev/null || { echo "✗ git is required (macOS: xcode-select --install)" >&2; exit 1; }

  if ! command -v uv >/dev/null; then
    echo "→ installing uv (https://docs.astral.sh/uv/)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi

  if [ "$with_claude_code" = 1 ] && ! command -v claude >/dev/null; then
    echo "→ installing Claude Code"
    curl -fsSL https://claude.ai/install.sh | bash
  fi
  if [ "$with_codex" = 1 ] && ! command -v codex >/dev/null; then
    echo "→ installing Codex CLI"
    if command -v brew >/dev/null; then
      brew install --cask codex
    elif command -v npm >/dev/null; then
      npm install -g @openai/codex
    else
      echo "✗ Codex needs Homebrew or Node.js (npm). Install one of them and re-run." >&2; exit 1
    fi
  fi

  if [ -d "$SRC/.git" ]; then
    echo "→ updating $SRC"
    git -C "$SRC" fetch --depth 1 --quiet origin "$REF"
    git -C "$SRC" checkout --quiet --force FETCH_HEAD
  else
    echo "→ downloading ko-paper into $SRC"
    mkdir -p "$(dirname "$SRC")"
    git clone --depth 1 --branch "$REF" --quiet "$REPO" "$SRC"
  fi

  # Skills go to every agent found on this machine unless --claude/--codex picked one.
  # On an update, keep the agents chosen at first install.
  if [ "$want_claude$want_codex" = "00" ]; then
    [ -f "$CLAUDE_SKILLS/ko-paper/.kopaper-home" ] && want_claude=1
    [ -f "$CODEX_SKILLS/ko-paper/.kopaper-home" ] && want_codex=1
  fi
  if [ "$want_claude$want_codex" = "00" ]; then
    { [ -d "$HOME/.claude" ] || command -v claude >/dev/null; } && want_claude=1
    { [ -d "${CODEX_HOME:-$HOME/.codex}" ] || command -v codex >/dev/null; } && want_codex=1
  fi

  # Lets `ko-paper update` (which runs the script in $SRC) know this copy came from install.sh.
  printf '%s\n' "$SRC" > "$SRC/skills/ko-paper/.kopaper-home"

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
  if [ "$want_claude" = 1 ]; then install_to "$CLAUDE_SKILLS"; fi
  if [ "$want_codex" = 1 ]; then install_to "$CODEX_SKILLS"; fi

  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/ko-paper" <<EOF
#!/usr/bin/env bash
# ko-paper launcher (written by install.sh). No arguments opens the web UI.
exec "$SRC/skills/ko-paper/scripts/kopaper.sh" "\$@"
EOF
  chmod +x "$BIN_DIR/ko-paper"
  echo "  command installed: $BIN_DIR/ko-paper"

  echo
  local status=0
  "$SRC/skills/ko-paper/scripts/kopaper.sh" doctor || status=$?

  echo
  if [ "$status" = 0 ]; then
    echo "✓ ko-paper is installed."
    echo "  Open the web UI:      ko-paper"
    echo "  Translate from shell: ko-paper translate ~/Downloads/paper.pdf"
    [ "$want_claude$want_codex" != "00" ] && echo "  In Claude Code / Codex (restart it first): \"이 논문 번역해줘 ~/Downloads/paper.pdf\""
  else
    echo "! ko-paper is downloaded but not ready yet. Fix the ✗ line above, then run: ko-paper doctor"
    if ! command -v claude >/dev/null && ! command -v codex >/dev/null; then
      echo "  Translation runs on your own Claude or ChatGPT subscription through its command-line tool:"
      echo "    Claude subscribers:  curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash -s -- --with-claude-code"
      echo "    ChatGPT subscribers: curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash -s -- --with-codex"
    fi
  fi
  case ":$ORIG_PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      # Homebrew's uv never adds ~/.local/bin to the shell config; do it so `ko-paper` works in new terminals.
      if [ "$BIN_DIR" = "$HOME/.local/bin" ]; then uv tool update-shell >/dev/null 2>&1 || true; fi
      echo "  Note: open a new terminal so the ko-paper command is found (or run: export PATH=\"$BIN_DIR:\$PATH\")" ;;
  esac
  return "$status"
}

ORIG_PATH="$PATH"
# Wrapped in a function so bash has parsed everything before the checkout above rewrites this file.
main "$@"
