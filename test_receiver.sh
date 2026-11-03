#!/bin/bash
# Offline fixtures only. No production paths, real account identifiers or persistent keys.
set -u
set -o pipefail
umask 077
TASK_TEST_DIR="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
source "$TASK_TEST_DIR/receiver.sh" --library-only
TASK_TEST_TMP="$(/usr/bin/mktemp -d /private/tmp/public-migration-test.XXXXXX)" || exit 1
TASK_TEST_COUNT=0
task_test_assert() {
  if ! "$@"; then printf 'FAIL: %s\n' "$*" >&2; exit 1; fi
  TASK_TEST_COUNT=$((TASK_TEST_COUNT + 1))
}
task_test_reject() {
  "$@" >/dev/null 2>&1
  task_test_code=$?
  task_test_assert test "$task_test_code" -ne 0
}

# The generated key has never authenticated any device. Remove its private half immediately.
/usr/bin/ssh-keygen -q -t ed25519 -N '' -C '' -f "$TASK_TEST_TMP/synthetic_host" || exit 1
/bin/rm -f "$TASK_TEST_TMP/synthetic_host"
# Normalize trailing empty comment from ssh-keygen; no real host key is stored in this repository.
TASK_TEST_PUB="$(/usr/bin/awk '{print $1 " " $2}' "$TASK_TEST_TMP/synthetic_host.pub")"
printf '%s\n' "$TASK_TEST_PUB" > "$TASK_TEST_TMP/synthetic_host.pub"
TASK_TEST_FP="$(/usr/bin/ssh-keygen -l -E sha256 -f "$TASK_TEST_TMP/synthetic_host.pub" | /usr/bin/awk '{print $2}')"
task_test_config() {
  printf '%s\n' 'SOURCE_USER=test_operator' 'SOURCE_HOME=/fixture/source-home' 'SOURCE_HOST=source.invalid' 'SOURCE_HOST_KEY_FILE=synthetic_host.pub' "SOURCE_HOST_KEY_SHA256=$TASK_TEST_FP" \
    'ROOT_1_REL=Documents/Project Files' 'ROOT_1_KIND=dir' 'ROOT_1_OPTIONAL=0' \
    'ROOT_2_REL=handoff/RECOVERY.md' 'ROOT_2_KIND=file' 'ROOT_2_OPTIONAL=1' > "$1"
}
task_test_config "$TASK_TEST_TMP/source_config.env"
task_test_assert task_load_config "$TASK_TEST_TMP/source_config.env"
task_test_assert test "${#TASK_ROOT_PATHS[@]}" -eq 2
task_test_assert test "${TASK_ROOT_PATHS[0]}" = '/fixture/source-home/Documents/Project Files'
task_test_assert test "${TASK_ROOT_KINDS[1]}" = file
task_test_assert test "${TASK_ROOT_OPTIONAL[1]}" -eq 1
task_test_assert task_validate_hostkey "$TASK_PUBLIC_KEY_FILE"
task_test_reject task_validate_hostkey "$TASK_TEST_TMP/missing.pub"
task_test_assert test -z "$TASK_VERIFIED_HOSTKEY"
printf 'not-a-public-key\n' > "$TASK_TEST_TMP/invalid.pub"
task_test_reject task_validate_hostkey "$TASK_TEST_TMP/invalid.pub"
TASK_PINNED_FINGERPRINT='SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
task_test_reject task_validate_hostkey "$TASK_TEST_TMP/synthetic_host.pub"
task_test_assert task_load_config "$TASK_TEST_TMP/source_config.env"

# Reject duplicates, unknown secret keys, shell code and traversal; never execute configuration.
task_test_config "$TASK_TEST_TMP/duplicate.env"
printf '%s\n' 'SOURCE_HOST=another.invalid' >> "$TASK_TEST_TMP/duplicate.env"
task_test_reject task_load_config "$TASK_TEST_TMP/duplicate.env"
task_test_config "$TASK_TEST_TMP/unknown.env"
printf '%s\n' 'SECRET_PASSWORD=should-never-be-accepted' >> "$TASK_TEST_TMP/unknown.env"
task_test_reject task_load_config "$TASK_TEST_TMP/unknown.env"
/usr/bin/sed 's|ROOT_1_REL=.*|ROOT_1_REL=../outside|' "$TASK_TEST_TMP/source_config.env" > "$TASK_TEST_TMP/traversal.env"
task_test_reject task_load_config "$TASK_TEST_TMP/traversal.env"
/usr/bin/sed 's|ROOT_1_REL=.*|ROOT_1_REL=$(touch NEVER_EXECUTE)|' "$TASK_TEST_TMP/source_config.env" > "$TASK_TEST_TMP/injection.env"
task_test_reject task_load_config "$TASK_TEST_TMP/injection.env"
task_test_assert test ! -e NEVER_EXECUTE
/usr/bin/sed 's|ROOT_2_REL=|ROOT_3_REL=|' "$TASK_TEST_TMP/source_config.env" > "$TASK_TEST_TMP/missing-root.env"
task_test_reject task_load_config "$TASK_TEST_TMP/missing-root.env"
task_test_assert task_load_config "$TASK_TEST_TMP/source_config.env"
task_test_assert test "$(task_quote_remote "/fixture/It's a file")" = "'/fixture/It'\\''s a file'"

/bin/mkdir "$TASK_TEST_TMP/private-ssh"
TASK_SOCKET_DIR="$TASK_TEST_TMP/private-ssh"
task_test_assert task_prepare_pinned_hostkey "$TASK_PUBLIC_KEY_FILE" 'source.invalid'
task_test_assert /usr/bin/grep -q '^source.invalid ssh-ed25519 ' "$TASK_KNOWN_HOSTS"
task_test_assert test "$(/usr/bin/stat -f '%Lp' "$TASK_KNOWN_HOSTS")" = 600
task_test_assert test "${TASK_SSH_TRUST_OPTIONS[5]}" = StrictHostKeyChecking=yes
task_test_assert test "${TASK_SSH_TRUST_OPTIONS[7]}" = "UserKnownHostsFile=$TASK_KNOWN_HOSTS"
task_test_assert test "${TASK_SSH_TRUST_OPTIONS[9]}" = GlobalKnownHostsFile=/dev/null
task_cleanup
task_test_assert test ! -e "$TASK_TEST_TMP/private-ssh"
TASK_SOCKET_DIR='' TASK_KNOWN_HOSTS=''

(task_cancel) >/dev/null 2>&1
task_test_code=$?
task_test_assert test "$task_test_code" -eq 130
/bin/mkdir -p "$TASK_TEST_TMP/unrelated/Production-Migration-Receive"
printf 'KEEP\n' > "$TASK_TEST_TMP/unrelated/Production-Migration-Receive/important.txt"
task_test_reject task_prepare_target "$TASK_TEST_TMP/unrelated"
task_test_assert test "$(/bin/cat "$TASK_TEST_TMP/unrelated/Production-Migration-Receive/important.txt")" = KEEP
/bin/mkdir "$TASK_TEST_TMP/allowed"
task_test_assert task_prepare_target "$TASK_TEST_TMP/allowed"
task_test_assert task_bind_source SYNTHETIC-HARDWARE-ONE
task_test_assert task_bind_source SYNTHETIC-HARDWARE-ONE
task_test_reject task_bind_source SYNTHETIC-HARDWARE-TWO
task_test_assert task_lock_target
task_test_reject task_lock_target
task_cleanup
task_test_assert test ! -e "$TASK_ROOT/.receiver-lock"
TASK_LOCK_OWNED=0
printf 'KEEP\n' > "$TASK_ROOT/staging/keep.txt"
task_test_original_root="$TASK_ROOT"
task_test_assert task_prepare_target "$TASK_TEST_TMP/allowed"
task_test_assert test "$TASK_ROOT" = "$task_test_original_root"
/bin/ln -s "$TASK_TEST_TMP/allowed" "$TASK_TEST_TMP/link"
task_test_reject task_prepare_target "$TASK_TEST_TMP/link"
task_test_assert task_prepare_target "$TASK_TEST_TMP/allowed"

TASK_LOG="$TASK_ROOT/运行记录/test.log"
TASK_STATUS="$TASK_ROOT/运行记录/test.tsv"
TASK_REMOTE="$TASK_REMOTE_USER@$TASK_SOURCE_HOST"
TASK_RSH='ssh-stub-never-executed'
TASK_TEST_RSYNC_EXIT=23
TASK_RSYNC=task_test_rsync_stub
task_test_rsync_stub() {
  local task_arg
  printf '%s\n' "$@" > "$TASK_TEST_TMP/rsync-args.txt"
  for task_arg in "$@"; do
    case "$task_arg" in --delete*|--remove-source*|--copy-links|--keep-dirlinks) return 99 ;; esac
  done
  return "$TASK_TEST_RSYNC_EXIT"
}
task_run_root 1 COPY >/dev/null 2>&1
task_test_code=$?
task_test_assert test "$task_test_code" -eq 23
task_test_assert /usr/bin/grep -q RSYNC_FAILED_23 "$TASK_STATUS"
task_test_assert /usr/bin/grep -q -- '--exclude=.env' "$TASK_TEST_TMP/rsync-args.txt"
task_test_assert /usr/bin/grep -q -- '--exclude=publisher_key.json' "$TASK_TEST_TMP/rsync-args.txt"
task_test_assert /usr/bin/grep -q RECOVERY.md "$TASK_TEST_TMP/rsync-args.txt"
TASK_TEST_RSYNC_EXIT=0
task_test_assert task_run_root 0 DRY_RUN
task_test_assert /usr/bin/grep -q -- '^-n$' "$TASK_TEST_TMP/rsync-args.txt"
task_test_assert /usr/bin/grep -q RSYNC_OK "$TASK_STATUS"
task_test_assert test "$(/bin/cat "$TASK_ROOT/staging/keep.txt")" = KEEP
/bin/mv "$TASK_ROOT/.production-receiver-v1" "$TASK_ROOT/marker-original"
/bin/ln -s "$TASK_ROOT/marker-original" "$TASK_ROOT/.production-receiver-v1"
task_run_root 0 COPY >/dev/null 2>&1
task_test_code=$?
task_test_assert test "$task_test_code" -eq 91

printf 'PASS: %s offline assertions; no network, real SSH/rsync, GUI or production data access.\n' "$TASK_TEST_COUNT"
printf 'Synthetic test evidence: %s\n' "$TASK_TEST_TMP"
