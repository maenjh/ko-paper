#!/usr/bin/env bash
# Print an HTML file to PDF with a Chromium browser already on the machine (Chrome, Edge, Chromium).
#   html2pdf.sh in.html out.pdf
# Lite mode uses this instead of BabelDOC, so nothing compiled is installed.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: html2pdf.sh in.html out.pdf" >&2; exit 2; }
in="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
out="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"

browser=""
for b in "${KOPAPER_BROWSER:-}" \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  "/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
  google-chrome google-chrome-stable chromium chromium-browser microsoft-edge; do
  [ -n "$b" ] || continue
  if [ -x "$b" ]; then browser="$b"; break; fi
  if command -v "$b" >/dev/null 2>&1; then browser="$(command -v "$b")"; break; fi
done
[ -n "$browser" ] || { echo "✗ no Chrome, Edge or Chromium found. Open $in in a browser and print it to PDF." >&2; exit 1; }

url="file://$in"
if command -v cygpath >/dev/null 2>&1; then  # Git Bash: the browser is a Windows program
  url="file:///$(cygpath -m "$in")"; out="$(cygpath -w "$out")"
fi
rm -f "$out"
# A throwaway profile: works while the user's own browser is open, and leaves their profile alone.
profile="$(mktemp -d)"
trap 'rm -rf "$profile"' EXIT
if command -v cygpath >/dev/null 2>&1; then profile_arg="$(cygpath -w "$profile")"; else profile_arg="$profile"; fi
"$browser" --headless=new --disable-gpu --no-first-run --user-data-dir="$profile_arg" --no-pdf-header-footer \
  --print-to-pdf="$out" "$url" >/dev/null 2>&1 || true
[ -s "$out" ] || { echo "✗ the browser did not write $out" >&2; exit 1; }
echo "$out"
