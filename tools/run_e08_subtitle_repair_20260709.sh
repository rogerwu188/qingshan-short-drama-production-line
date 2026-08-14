#!/usr/bin/env bash
set -euo pipefail

cd /Users/rogerwu/qingshan_short_drama

if [[ -z "${GIGGLE_API_KEY:-}" ]]; then
  echo "Missing GIGGLE_API_KEY. Export it before running subtitle repair."
  exit 2
fi

python3 tools/build_e08_subtitle_repair_plan_20260709.py

python3 tools/run_giggle_api_plan.py \
  --plan working_assets/e08_subtitle_repair_20260709/run_plan_subtitle_repair.json \
  --shots 07 09 10 14 20 22 \
  --model seedance-2.0-pro \
  --ratio 9:16 \
  --resolution 720p \
  --poll-seconds 15 \
  --timeout-minutes 35
