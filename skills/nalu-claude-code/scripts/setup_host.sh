#!/usr/bin/env bash
# setup_host.sh — one-shot, idempotent host setup for the NALU line on an OpenClaw miniPC.
#
# The OpenClaw agent runs this on every wake-up.  On a ready host it only re-checks and exits in
# seconds; otherwise it does whatever is missing, with nobody at the terminal:
#   1. system deps   git / ffmpeg / ffprobe / CJK font / uv  (passwordless sudo apt if available,
#                    else user-space: static ffmpeg in ~/.local/bin, Noto CJK in ~/.local/share/fonts)
#   2. engine        clone ~/nalu_engine, or move an existing checkout to the pinned commit
#                    (a checkout with local changes is renamed ~/nalu_engine_old_<ts>, never deleted)
#   3. runtime       a ~/nalu_runtime this script did not create is renamed ~/nalu_runtime_old_<ts>
#   4. python        .qingshan-venv (uv, CPython 3.12) + core/media/QA deps, runtime bootstrap
#   5. claude code   install (native installer, npm fallback) + configure_claude_code.py --verify
#                    (reads the StoryClaw provider from ~/.openclaw/openclaw.json; never prints the key)
# Result: ~/.nalu_setup_state.json and ONE final JSON line on stdout:
#   NALU_SETUP: {"status":"READY|BLOCKED", "failed_step":..., "steps":{...}, ...}
#
# usage: setup_host.sh --pin <engine commit> [--force] [--skip-verify]
set -uo pipefail

PIN="${NALU_ENGINE_PIN:-}"; FORCE=0; VERIFY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --pin) PIN="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --skip-verify) VERIFY=0; shift ;;
    *) echo "unknown arg $1" >&2; exit 2 ;;
  esac
done
[ -n "$PIN" ] || { echo 'NALU_SETUP: {"status":"BLOCKED","failed_step":"args","reason":"--pin <commit> is required"}'; exit 2; }

S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO=https://github.com/rogerwu188/qingshan-short-drama-production-line.git
ENGINE="${NALU_ENGINE_ROOT:-$HOME/nalu_engine}"
RUNTIME="${NALU_RUNTIME_ROOT:-$HOME/nalu_runtime}"
STATE="$HOME/.nalu_setup_state.json"
LOG="$HOME/.nalu_setup.log"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
NOTES=()

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }
run() { log "\$ $*"; "$@" >>"$LOG" 2>&1; }
finish() {  # status failed_step
  local steps="" k
  for k in deps engine runtime python claude_install claude_config; do
    v="STEP_$k"; steps="$steps\"$k\":\"${!v:-NOT_RUN}\","
  done
  local notes="" n
  for n in "${NOTES[@]+"${NOTES[@]}"}"; do notes="$notes\"${n//\"/\'}\","; done
  notes="${notes%,}"
  local json="{\"status\":\"$1\",\"failed_step\":\"$2\",\"pin\":\"$PIN\",\"engine\":\"$ENGINE\",\"runtime\":\"$RUNTIME\",\"log\":\"$LOG\",\"steps\":{${steps%,}},\"notes\":[${notes}],\"at\":\"$TS\"}"
  printf '%s\n' "$json" >"$STATE"
  printf 'NALU_SETUP: %s\n' "$json"
  [ "$1" = READY ] && exit 0 || exit 3
}
[ "$(id -u)" != 0 ] || { NOTES+=("run as the OpenClaw user, not root"); finish BLOCKED preflight; }
log "==== setup_host.sh pin=$PIN force=$FORCE"

# fast path: ready host, same pin, claude still answers through the relay
if [ $FORCE = 0 ] && [ -f "$STATE" ] && grep -q "\"status\":\"READY\"" "$STATE" && grep -q "\"pin\":\"$PIN\"" "$STATE" \
   && [ "$(git -C "$ENGINE" rev-parse HEAD 2>/dev/null)" = "$PIN" ] && [ -x "$ENGINE/.qingshan-venv/bin/python" ] \
   && command -v claude >/dev/null && [ -f "$HOME/.claude/settings.json" ]; then
  for k in deps engine runtime python claude_install claude_config; do eval "STEP_$k=OK_CACHED"; done
  finish READY ""
fi

# ---------------------------------------------------------------- 1. system deps
SUDO=""; sudo -n true 2>/dev/null && SUDO="sudo -n"
if [ -n "$SUDO" ] && command -v apt-get >/dev/null; then
  run $SUDO apt-get update -qq
  run $SUDO apt-get install -y -qq git ffmpeg fonts-noto-cjk build-essential python3-dev curl xz-utils
fi
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/fonts"
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  tmp="$(mktemp -d)"
  if run curl -fsSL -o "$tmp/ff.tar.xz" https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
     && run tar -xJf "$tmp/ff.tar.xz" -C "$tmp"; then
    cp "$tmp"/ffmpeg-*-static/ffmpeg "$tmp"/ffmpeg-*-static/ffprobe "$HOME/.local/bin/" && NOTES+=("ffmpeg: user-space static build")
  fi
  rm -rf "$tmp"
fi
FONT="$(fc-list 2>/dev/null | grep -i -m1 -E 'Noto Sans CJK|NotoSansCJK' | cut -d: -f1)"
if [ -z "$FONT" ]; then
  FONT="$HOME/.local/share/fonts/NotoSansCJKsc-Regular.otf"
  [ -f "$FONT" ] || run curl -fsSL -o "$FONT" https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf
  command -v fc-cache >/dev/null && run fc-cache -f "$HOME/.local/share/fonts"
fi
if ! command -v uv >/dev/null; then run sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'; fi
missing=""
for c in git ffmpeg ffprobe uv curl; do command -v $c >/dev/null || missing="$missing $c"; done
[ -f "$FONT" ] || missing="$missing cjk-font"
if [ -n "$missing" ]; then STEP_deps="MISSING:${missing# }"; finish BLOCKED deps; fi
STEP_deps=OK

# ---------------------------------------------------------------- 2. engine at the pinned commit
if [ -d "$ENGINE/.git" ]; then
  run git -C "$ENGINE" fetch -q origin
  if [ -n "$(git -C "$ENGINE" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    # keep local edits recoverable without moving .env / workflow state away from the engine
    run git -C "$ENGINE" -c user.name=setup -c user.email=setup@localhost stash push -m "setup_host $TS" \
      && NOTES+=("engine local changes stashed: git -C $ENGINE stash list")
  fi
elif [ -e "$ENGINE" ]; then
  mv "$ENGINE" "${ENGINE}_old_$TS" && NOTES+=("non-git $ENGINE kept as ${ENGINE}_old_$TS")
fi
[ -d "$ENGINE/.git" ] || run git clone -q "$REPO" "$ENGINE" || { STEP_engine=CLONE_FAILED; finish BLOCKED engine; }
before="$(git -C "$ENGINE" rev-parse HEAD)"
run git -C "$ENGINE" checkout -q --detach "$PIN" || { STEP_engine=CHECKOUT_FAILED; finish BLOCKED engine; }
[ "$before" = "$PIN" ] || NOTES+=("engine moved ${before:0:7} -> ${PIN:0:7}")
[ -d "$ENGINE/skills/nalu-claude-code/scripts" ] || { STEP_engine=SKILL_DIR_MISSING_AT_PIN; finish BLOCKED engine; }
STEP_engine=OK

# ---------------------------------------------------------------- 3. runtime (keep ours, set aside foreign ones)
if [ -d "$RUNTIME" ] && [ ! -f "$RUNTIME/.nalu_setup_owner" ]; then
  mv "$RUNTIME" "${RUNTIME}_old_$TS" && NOTES+=("pre-existing runtime kept as ${RUNTIME}_old_$TS")
fi
STEP_runtime=OK

# ---------------------------------------------------------------- 4. python env + runtime bootstrap
cd "$ENGINE" || finish BLOCKED python
if [ ! -x .qingshan-venv/bin/python ] || [ "$before" != "$PIN" ] || [ $FORCE = 1 ]; then
  run uv python install 3.12 && run uv venv --allow-existing -q --python 3.12 --seed .qingshan-venv || { STEP_python=VENV_FAILED; finish BLOCKED python; }
  export VIRTUAL_ENV="$ENGINE/.qingshan-venv"
  run uv pip install -q -r requirements-core.txt -r requirements-media.txt && run uv pip install -q -e . \
    || { STEP_python=CORE_DEPS_FAILED; finish BLOCKED python; }
  run uv pip install -q insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc "av==18.1.0" \
    || { STEP_python="QA_DEPS_FAILED(insightface needs build-essential+python3-dev: passwordless sudo or a preinstalled compiler)"; finish BLOCKED python; }
fi
.qingshan-venv/bin/python -c "import insightface, faster_whisper, rapidocr_onnxruntime, opencc" >>"$LOG" 2>&1 \
  || { STEP_python=IMPORT_CHECK_FAILED; finish BLOCKED python; }
[ -f .env ] || cp .env.example .env; chmod 600 .env
if [ ! -f "$RUNTIME/.nalu_setup_owner" ]; then
  run python3 lines/nalu/runtime/tools/bootstrap_runtime_root.py --runtime-root "$RUNTIME" --line-id nalu-minipc --work "短剧工作流" \
    || { STEP_python=RUNTIME_BOOTSTRAP_FAILED; finish BLOCKED python; }
  [ -f "$RUNTIME/qingshan.json" ] || cp configs/pipeline.example.json "$RUNTIME/qingshan.json"
  run .qingshan-venv/bin/python "$S/apply_runtime_fixups.py" --runtime-root "$RUNTIME"
  printf '{"created_by":"setup_host.sh","at":"%s","pin":"%s"}\n' "$TS" "$PIN" >"$RUNTIME/.nalu_setup_owner"
fi
grep -q 'NALU_ENGINE_ROOT=' "$HOME/.bashrc" 2>/dev/null || cat >>"$HOME/.bashrc" <<EOF
# NALU line (setup_host.sh)
export NALU_ENGINE_ROOT="$ENGINE" NALU_RUNTIME_ROOT="$RUNTIME" NALU_WORK_ROOT="$ENGINE/workflow/nalu"
export NALU_QA_WORKERS=1 NALU_Q2_WORKERS=1 QINGSHAN_CJK_FONT="$FONT"
export PATH="\$HOME/.local/bin:\$HOME/.npm-global/bin:\$PATH"
EOF
STEP_python=OK

# ---------------------------------------------------------------- 5. claude code + relay config
if ! command -v claude >/dev/null; then
  run sh -c 'curl -fsSL https://claude.ai/install.sh | bash'
  if ! command -v claude >/dev/null && command -v npm >/dev/null; then
    npm config get prefix 2>/dev/null | grep -q "^$HOME" || run npm config set prefix "$HOME/.npm-global"
    run npm install -g @anthropic-ai/claude-code
  fi
fi
command -v claude >/dev/null || { STEP_claude_install=INSTALL_FAILED; finish BLOCKED claude_install; }
STEP_claude_install="OK:$(claude --version 2>/dev/null | head -1)"
args=(); [ $VERIFY = 1 ] && args+=(--verify)
out="$(python3 "$S/configure_claude_code.py" ${args[@]+"${args[@]}"} 2>>"$LOG")"; rc=$?
log "configure_claude_code: $(printf '%s' "$out" | tr -d '\n' | cut -c1-400)"
status="$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)"
if [ $rc != 0 ] || { [ $VERIFY = 1 ] && [ "$status" != VERIFIED ]; }; then
  STEP_claude_config="${status:-FAILED}"; finish BLOCKED claude_config
fi
STEP_claude_config="$status"
finish READY ""
