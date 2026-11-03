#!/bin/bash
TASK_LAUNCHER_DIR="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
/bin/bash "$TASK_LAUNCHER_DIR/receiver.sh" "$@"
TASK_LAUNCHER_RESULT=$?
if [ -t 0 ] && [ "${1:-}" != '--self-test' ]; then
  printf '\n按回车关闭窗口。\n'
  read -r _task_finished
fi
exit "$TASK_LAUNCHER_RESULT"
