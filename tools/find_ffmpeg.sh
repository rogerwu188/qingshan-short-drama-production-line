#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

candidates=(
  "${FFMPEG:-}"
  "$ROOT/.video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
  "/opt/homebrew/bin/ffmpeg"
  "/usr/local/bin/ffmpeg"
  "$(command -v ffmpeg 2>/dev/null || true)"
  "/Applications/CapCut.app/Contents/Resources/ffmpeg"
)

for item in "${candidates[@]}"; do
  if [[ -n "$item" && -x "$item" ]]; then
    printf '%s\n' "$item"
    exit 0
  fi
done

cat >&2 <<'EOF'
ffmpeg not found.

Install ffmpeg for the device, set FFMPEG to an executable path, or place the
portable binary under $QINGSHAN_FACTORY_ROOT/.video_deps/imageio_ffmpeg/binaries.
EOF
exit 1
