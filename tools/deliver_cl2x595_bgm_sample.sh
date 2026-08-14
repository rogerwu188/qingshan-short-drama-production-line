#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/rogerwu/qingshan_short_drama"
cd "$ROOT"
set -a
source .secrets/s3_relay.env
set +a

PY="$ROOT/.s3_relay_env_py312/bin/python3"
RELAY="$ROOT/workflow/s3_relay/relay_client.py"

"$PY" "$RELAY" deliver-file "$ROOT/exports/e28/cl2x595_bgm_realmix_sample_20260722/E28_CL2X595_AGENTCUT_BGM_REALMIX_SAMPLE.mp4" --slug E28_CL2X595_AGENTCUT_BGM_REALMIX_SAMPLE.mp4
"$PY" "$RELAY" deliver-file "$ROOT/workflow/audio/e28_cl2x595/E28_CL2X595_BGM_CUE_SHEET.json" --slug E28_CL2X595_BGM_CUE_SHEET.json --content-type application/json
"$PY" "$RELAY" deliver-file "$ROOT/exports/e28/cl2x595_bgm_realmix_sample_20260722/E28_CL2X595_AGENTCUT_BGM_REALMIX_SAMPLE.mp4.manifest.json" --slug E28_CL2X595_AGENTCUT_BGM_REALMIX_SAMPLE.manifest.json --content-type application/json
"$PY" "$RELAY" deliver-file "$ROOT/workflow/tasks/CL2X595_E28_AGENTCUT_BGM_REALMIX_RECEIPT_20260722.json" --slug CL2X595_E28_AGENTCUT_BGM_REALMIX_RECEIPT_20260722.json --content-type application/json
"$PY" "$RELAY" send c2sc "$ROOT/workflow/storyclaw_replies/C2SC-CL2X595_E28_BGM_REALMIX_CANDIDATE_20260722.md" --slug C2SC-CL2X595_E28_BGM_REALMIX_CANDIDATE_20260722.md
