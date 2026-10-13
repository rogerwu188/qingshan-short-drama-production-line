#!/bin/bash
# Planning-only compile of the grouped video prompts (whole-batch prompt gate step 1). Free, no POST.
set -eo pipefail
EP=${1:-E01}
E=${NALU_ENGINE_ROOT:?}; R=${NALU_RUNTIME_ROOT:?}
export NALU_WORK_ROOT=$E/workflow/nalu NALU_POLICY_PROFILE=CURRENT_PORTABLE NALU_SERIES_SCOPES=$R/runtime/series_scopes.json \
  NALU_SERIES_SCOPE_ID=NALU-YEWUJIANG QINGSHAN_VOICE_REGISTRY=$R/runtime/voice_registry.json \
  QINGSHAN_ENTITY_REGISTRY=$R/runtime/nalu_entity_registry.json QINGSHAN_CHARACTER_REGISTRY=$R/runtime/nalu_character_asset_registry.json PYTHONPATH=$E
unset GIGGLE_API_KEY
PRE=$E/workflow/nalu/$EP/preproduction
cd $E
$E/.qingshan-venv/bin/python tools/compile_grouped_seedance_manifest.py --grouping-plan $PRE/${EP}_VIDEO_UNIT_GROUPING_PLAN_V1.json \
  --anchor-plan $PRE/${EP}_VIDEO_UNIT_ANCHOR_PLAN_V1.json --editorial-seedance-manifest $PRE/${EP}_EDITORIAL_SEEDANCE_MANIFEST_V1.json \
  --generation-contract $E/workflow/claude_writer_agent/scripts/${EP}_GENERATION_CONTRACT_v1.json \
  --out $PRE/${EP}_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.json --planning-only --planned-prompt-dir $PRE/planned_video_prompts
