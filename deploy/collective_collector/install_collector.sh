#!/bin/bash
# Collective-learning collector + publisher on the fleet server (Hetzner nalu-fleet, approved design 2026-11-12).
#
# One machine, one publisher: this host ingests the devices' inbox batches, runs the daily release train and signs
# channel pointers with ITS OWN publisher key.  Devices never publish (they get their config from the fleet service,
# GET /v1/collective/provision, and only run device-sync).
#
# Phase 1 (this script, safe to re-run): user, directories, engine checkout at a pinned commit, a minimal venv
# (boto3 + cryptography), the two wrapper scripts, a release-train config template and the systemd timers.  It does
# NOT create keys, does NOT touch the bucket and does NOT enable the timers unless --enable is given.
#
# Phase 2 (human, with the real credentials) -- printed at the end, see also the PR description:
#   1. /var/lib/nalu-collector/runtime/collective/env (0600, owner nalucollect): the 5 lines
#      AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / S3CTL_ENDPOINT_URL / S3CTL_BUCKET / S3CTL_PUBLIC_BASE_URL
#   2. sudo -u nalucollect <venv>/python <engine>/tools/collective_learning/s3_sync.py bootstrap \
#        --runtime-root /var/lib/nalu-collector --tenant nalu --key-id pub-fleet
#      (new Ed25519 key, 0600; REPLACES collective/nalu/trust.json in the bucket with this key only)
#   3. copy runtime/collective/trust.json -> /etc/nalu-fleet/collective/trust.json and put config.json +
#      credentials.env there (see the fleet server's collective_provision docs); restart nalu-fleet
#   4. install_collector.sh --pin <sha> --enable
#
# Usage: install_collector.sh --pin <40-hex engine commit> [--repo <git url>] [--enable]
set -euo pipefail

PIN="" ; ENABLE=0 ; REPO="https://github.com/rogerwu188/qingshan-short-drama-production-line.git"
while [ $# -gt 0 ]; do
  case "$1" in
    --pin) PIN="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --enable) ENABLE=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ "$PIN" =~ ^[0-9a-f]{40}$ ]] || { echo "--pin <40-hex engine commit> is required" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME=nalucollect
OPT=/opt/nalu-collector
ENGINE="$OPT/engine"
VENV="$OPT/venv"
RUNTIME=/var/lib/nalu-collector
SHARED=/var/lib/nalu-fleet/collective          # cohort.json (written by the fleet service), release_train_status.json
ETC=/etc/nalu-collector

getent group nalufleet >/dev/null || groupadd --system nalufleet
id "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$RUNTIME" --shell /usr/sbin/nologin -G nalufleet "$USER_NAME"
usermod -a -G nalufleet "$USER_NAME"
install -d -m 755 "$OPT" "$ETC"
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "$RUNTIME" "$RUNTIME/runtime" "$RUNTIME/runtime/collective"
install -d -m 2770 -o nalufleet -g nalufleet "$SHARED"

if [ ! -d "$ENGINE/.git" ]; then
  git clone --quiet "$REPO" "$ENGINE"
fi
git -C "$ENGINE" fetch --quiet origin
git -C "$ENGINE" checkout --quiet --detach "$PIN"
chown -R root:root "$ENGINE"

[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "boto3>=1.34,<2" "cryptography>=42,<46"

install -m 755 "$HERE/collector_cycle.sh" "$OPT/collector_cycle.sh"
install -m 755 "$HERE/collector_daily.sh" "$OPT/collector_daily.sh"
install -m 755 "$HERE/collector_review_bridge.sh" "$OPT/collector_review_bridge.sh"
[ -f "$ETC/release_train.json" ] || install -m 644 "$HERE/release_train.example.json" "$ETC/release_train.json"
for unit in nalu-collective-cycle.service nalu-collective-cycle.timer nalu-collective-daily.service nalu-collective-daily.timer; do
  install -m 644 "$HERE/systemd/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [ "$ENABLE" = 1 ]; then
  [ -s "$RUNTIME/runtime/collective/env" ] || { echo "phase 2 missing: $RUNTIME/runtime/collective/env" >&2; exit 3; }
  [ -s "$RUNTIME/runtime/collective/publisher.key.json" ] || { echo "phase 2 missing: publisher key (s3_sync.py bootstrap)" >&2; exit 3; }
  systemctl enable --now nalu-collective-cycle.timer nalu-collective-daily.timer
  echo "timers enabled"
else
  echo "installed (timers NOT enabled).  Phase 2: see the header of $0"
fi
echo "engine=$(git -C "$ENGINE" rev-parse --short HEAD) venv=$VENV runtime=$RUNTIME shared=$SHARED"
