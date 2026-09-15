#!/bin/zsh
ENGINE_ROOT=${NALU_ENGINE_ROOT:?set NALU_ENGINE_ROOT}
RUNTIME_ROOT=${NALU_RUNTIME_ROOT:?set NALU_RUNTIME_ROOT}
TOOLS=${NALU_TOOLS_DIR:-$RUNTIME_ROOT/runtime/tools}
EP=${1:-E03}
cd "$ENGINE_ROOT"
set -a; source .env; set +a
LOG=${NALU_LOOP_LOG:-/tmp/nalu_${EP}_s6_loop.log}
# guard: never start a wave that the reroll cost guard refused (2026-09-13 incident)
if [ -n "$REQUIRE_GUARD" ] && [ "$(python3 -c "import json;print(json.load(open('$REQUIRE_GUARD')).get('status',''))")" != "PASS_AUTO_REROLL_ALLOWED" ]; then echo "REROLL_GUARD_NOT_PASS $REQUIRE_GUARD" >> $LOG; exit 3; fi
for i in {1..60}; do
  echo "=== loop $i $(date -u +%FT%TZ) ===" >> $LOG
  ${NALU_VENV_PYTHON:-.qingshan-venv/bin/python} "$TOOLS/nalu_pipeline.py" run --episode $EP --from S6 --paid >> $LOG 2>&1
  rc=$?
  st=$(python3 -c "import json;s=json.load(open('$RUNTIME_ROOT/runtime/pipeline_state/$EP.json'))['stages']['S6'];print(s.get('status'),'|',','.join(s.get('blockers') or []))")
  echo "LOOP_RESULT rc=$rc S6=$st" >> $LOG
  case "$st" in
    *VIDEO_NOT_ALL_COMPLETED*) sleep 180 ;;
    *) echo "LOOP_STOP $st" >> $LOG; exit 0 ;;
  esac
done
echo "LOOP_EXHAUSTED" >> $LOG
