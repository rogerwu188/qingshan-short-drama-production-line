#!/usr/bin/env bash
set -euo pipefail

cd /Users/rogerwu/qingshan_short_drama

if [[ -z "${GIGGLE_API_KEY:-}" && -f .secrets/giggle_api_key.env ]]; then
  # shellcheck disable=SC1091
  source .secrets/giggle_api_key.env
fi

if [[ -z "${GIGGLE_API_KEY:-}" ]]; then
  echo "Missing GIGGLE_API_KEY. Configure it in the environment or .secrets/giggle_api_key.env."
  exit 2
fi

out_dir="${E11_API_OUT_DIR:-working_assets/e11_api_20260710}"

python3 tools/build_e11_api_plan_20260710.py --out-dir "$out_dir"

python3 tools/asset_binding_validator.py \
  --config configs/e11_continuity_config_20shots_20260710.json \
  --manifest configs/e11_asset_binding_manifest_20260710.json \
  --out qa/e11_preflight_20260710/asset_binding_report.json

mode="${1:-smoke}"
if [[ "$mode" == "smoke" ]]; then
  shots=(01)
elif [[ "$mode" == "opening" ]]; then
  shots=(01 02 03 04 05)
elif [[ "$mode" == "act1" ]]; then
  shots=(01 02 03 04 05 06 07 08 09 10)
elif [[ "$mode" == "all" ]]; then
  shots=(01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20)
else
  shots=("$@")
fi

python3 tools/run_giggle_api_plan.py \
  --plan "$out_dir/run_plan.json" \
  --shots "${shots[@]}" \
  --model seedance-2.0-pro \
  --ratio 9:16 \
  --resolution 720p \
  --poll-seconds 15 \
  --timeout-minutes 35 \
  --skip-existing
