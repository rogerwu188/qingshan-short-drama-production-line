#!/bin/bash
# Whole-batch prompt gate, after the reviewer's answers exist: receipts -> register (must print PASS).
set -eo pipefail
EP=${1:-E01}; E=${NALU_ENGINE_ROOT:?}
cd $E; export NALU_WORK_ROOT=$E/workflow/nalu
REP=$E/workflow/nalu/$EP/preproduction/reports
env -u GIGGLE_API_KEY $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_qa.py receipts --episode $EP --digest $REP/${EP}_PROMPT_BATCH_DIGEST.json --answers $REP/${EP}_PROMPT_BATCH_ANSWERS.json --out-dir $REP/prompt_batch_qa | tail -1
env -u GIGGLE_API_KEY $E/.qingshan-venv/bin/python lines/nalu/runtime/tools/prompt_batch_register.py --episode $EP --execution-id $EP-PROMPT-BATCH-V1 --qa-dir $REP/prompt_batch_qa --report $REP/${EP}_PROMPT_BATCH_REGISTER.json | tail -1
