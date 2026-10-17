#!/bin/bash
# list_voices.sh — the S4 voice-catalog lookup (free GET, no credits) as one argv.
# The provider still authenticates the GET, so this reads GIGGLE_API_KEY from the engine's .env
# internally — the executor never sources or prints it (contract §0: free commands carry no key).
#   list_voices.sh <out.json>
set -eo pipefail
OUT=${1:?usage: list_voices.sh <out.json>}
E=${NALU_ENGINE_ROOT:-$HOME/nalu_engine}
if [ -z "${GIGGLE_API_KEY:-}" ]; then
  [ -f "$E/.env" ] || { echo "LIST_VOICES: no GIGGLE_API_KEY and no $E/.env" >&2; exit 2; }
  set -a; . "$E/.env"; set +a
fi
[ -n "${GIGGLE_API_KEY:-}" ] || { echo "LIST_VOICES: GIGGLE_API_KEY is unset" >&2; exit 2; }
cd "$E"
exec "$E/.qingshan-venv/bin/python" tools/storyclaw_audio_provider.py speech-voices --out "$OUT"
