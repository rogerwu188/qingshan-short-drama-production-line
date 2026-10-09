#!/bin/bash
# Whole-batch prompt gate, steps before the reviewer: S5 dry run (refresh keyframe prompts) -> planning compile -> register (HOLD) -> digest.
set -eo pipefail
EP=${1:-E01}; E=${NALU_ENGINE_ROOT:?}; R=${NALU_RUNTIME_ROOT:?}
cd $E; export NALU_WORK_ROOT=$E/workflow/nalu
$E/.qingshan-venv/bin/python lines/nalu/runtime/tools/nalu_pipeline.py run --episode $EP --from S5 --until S5 2>&1 | grep "=> " || true
"$(cd "$(dirname "$0")" && pwd)/plan_compile.sh" $EP | tail -1
REP=$E/workflow/nalu/$EP/preproduction/reports; mkdir -p $REP/prompt_batch_qa
rm -f $REP/prompt_batch_qa/*.json
env -u GIGGLE_API_KEY $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_register.py --episode $EP --execution-id $EP-PROMPT-BATCH-V1 --qa-dir $REP/prompt_batch_qa --report $REP/${EP}_PROMPT_BATCH_REGISTER.json | tail -1
env -u GIGGLE_API_KEY $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_qa.py digest --episode $EP --out $REP/${EP}_PROMPT_BATCH_DIGEST.json | tail -1
echo "next: reviewer writes $REP/${EP}_PROMPT_BATCH_ANSWERS.json, then prompt_batch_finish.sh $EP"
