#!/usr/bin/env bash
set -euo pipefail

cd /Users/rogerwu/qingshan_short_drama

if [[ -z "${GIGGLE_API_KEY:-}" ]]; then
  echo "Missing GIGGLE_API_KEY. Export it before running this API fallback."
  exit 2
fi

python3 tools/build_e08_api_fallback_plan_20260709.py \
  --shots 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23

python3 tools/asset_binding_validator.py \
  --config configs/e08_continuity_config_v1_24shots_20260705.json \
  --manifest configs/e08_asset_binding_manifest_v1_24shots_20260705.json \
  --out qa/e08_repair_20260709/api_fallback_asset_binding_report.json

mode="${1:-smoke}"

if [[ "$mode" == "smoke" ]]; then
  shots=(05)
elif [[ "$mode" == "all" ]]; then
  shots=(05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23)
else
  shots=("$@")
fi

python3 tools/run_giggle_api_plan.py \
  --plan working_assets/e08_api_fallback_20260709/run_plan.json \
  --shots "${shots[@]}" \
  --model seedance-2.0-pro \
  --ratio 9:16 \
  --resolution 720p \
  --poll-seconds 15 \
  --timeout-minutes 35 \
  --skip-existing
