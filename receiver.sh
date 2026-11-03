#!/bin/bash
# Public macOS pre-sync receiver. Configuration is data, never shell code.
# No production startup, no source deletion, no global SSH trust modification.
set -u
set -o pipefail
umask 077

TASK_FORMAT='PRODUCTION_PRESYNC_RECEIVER_V1'
TASK_MIN_FREE_KB=12582912
TASK_SSH_ACTIVE=0
TASK_SOCKET_DIR=''
TASK_ROOT=''
TASK_LOG=''
TASK_STATUS=''
TASK_INCLUDE_MODELS=0
TASK_LOCK_OWNED=0
TASK_RSYNC='/usr/bin/rsync'
TASK_SSH='/usr/bin/ssh'
TASK_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
TASK_REMOTE_USER=''
TASK_SOURCE_HOME=''
TASK_SOURCE_HOST=''
TASK_PUBLIC_KEY_FILE=''
TASK_PINNED_FINGERPRINT=''
TASK_CONFIG_PATH=''
TASK_VERIFIED_HOSTKEY=''
TASK_KNOWN_HOSTS=''
TASK_SSH_TRUST_OPTIONS=()
TASK_ROOT_KEYS=()
TASK_ROOT_PATHS=()
TASK_ROOT_KINDS=()
TASK_ROOT_OPTIONAL=()
TASK_EXCLUDES=(
  '--exclude=__pycache__/' '--exclude=pycache/' '--exclude=.pytest_cache/'
  '--exclude=.venv/' '--exclude=venv/' '--exclude=.qingshan-venv/' '--exclude=qa-venv/'
  '--exclude=.DS_Store' '--exclude=.env' '--exclude=.env.*' '--exclude=env'
  '--exclude=credentials' '--exclude=credentials.json' '--exclude=publisher_key.json'
  '--exclude=publisher.key.json' '--exclude=*私密包*' '--exclude=private_credentials/'
  '--exclude=admin.token' '--exclude=*.pem' '--exclude=*.key' '--exclude=.ssh/'
  '--exclude=.netrc' '--exclude=.npmrc' '--exclude=.pypirc' '--exclude=auth.json'
  '--exclude=token' '--exclude=stored_tokens' '--exclude=source_config.env'
)

task_dialog() {
  /usr/bin/osascript - "$1" "$2" <<'APPLESCRIPT'
on run argv
  display dialog (item 2 of argv) with title (item 1 of argv) buttons {"取消", "继续"} default button "继续" cancel button "取消"
end run
APPLESCRIPT
}

task_notice() {
  printf '%s\n' "$1"
  /usr/bin/osascript - "$1" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display dialog (item 1 of argv) with title "生产线 预同步" buttons {"知道了"} default button "知道了"
end run
APPLESCRIPT
}

task_fail() {
  task_notice "$1"
  exit 1
}

task_cancel() {
  printf '用户取消。没有启动生产；若已传输，专用接收目录保留，便于下次增量恢复。\n'
  exit 130
}

task_cleanup() {
  # 只关闭本次创建的独立 SSH master；不 kill 用户其他 ssh 会话。
  if [ "$TASK_SSH_ACTIVE" -eq 1 ]; then
    "$TASK_SSH" "${TASK_SSH_TRUST_OPTIONS[@]}" -S "$TASK_SOCKET_DIR/control" -O exit "$TASK_REMOTE" >/dev/null 2>&1 || true
  fi
  if [ -n "$TASK_SOCKET_DIR" ]; then
    if [ "$TASK_KNOWN_HOSTS" = "$TASK_SOCKET_DIR/known_hosts" ] && [ ! -L "$TASK_KNOWN_HOSTS" ]; then
      /bin/rm -f "$TASK_KNOWN_HOSTS"
    fi
    /bin/rmdir "$TASK_SOCKET_DIR" 2>/dev/null || true
  fi
  if [ "$TASK_LOCK_OWNED" -eq 1 ] && [ -n "$TASK_ROOT" ] && task_marker_valid "$TASK_ROOT"; then
    if [ "$(/bin/cat "$TASK_ROOT/.receiver-lock/pid" 2>/dev/null)" = "$$" ]; then
      /bin/rm -f "$TASK_ROOT/.receiver-lock/pid"
      /bin/rmdir "$TASK_ROOT/.receiver-lock" 2>/dev/null || true
    fi
  fi
}

task_validate_hostkey() {
  local task_pub_file="$1" task_key_line task_key_fingerprint
  TASK_VERIFIED_HOSTKEY=''
  [ -f "$task_pub_file" ] && [ ! -L "$task_pub_file" ] && [ -r "$task_pub_file" ] || return 1
  task_key_line="$(/usr/bin/awk '
    NR != 1 || NF != 2 || $1 != "ssh-ed25519" || $2 !~ /^[A-Za-z0-9+\/=]+$/ {bad=1}
    {line=$0}
    END {if (NR != 1 || bad) exit 1; print line}
  ' "$task_pub_file")" || return 1
  # 对已读入的同一份公钥验指纹，避免校验与使用两次读取不同内容。
  task_key_fingerprint="$(/usr/bin/ssh-keygen -l -E sha256 -f /dev/stdin <<< "$task_key_line" 2>/dev/null | /usr/bin/awk '{print $2}')" || return 1
  [ "$task_key_fingerprint" = "$TASK_PINNED_FINGERPRINT" ] || return 1
  TASK_VERIFIED_HOSTKEY="$task_key_line"
}

task_prepare_pinned_hostkey() {
  local task_pub_file="$1" task_selected_host="$2"
  case "$task_selected_host" in ''|*[!a-zA-Z0-9.-]*|-*|.*) return 1 ;; esac
  [ -n "$TASK_SOCKET_DIR" ] && [ -d "$TASK_SOCKET_DIR" ] && [ ! -L "$TASK_SOCKET_DIR" ] || return 1
  task_validate_hostkey "$task_pub_file" || return 1
  TASK_KNOWN_HOSTS="$TASK_SOCKET_DIR/known_hosts"
  [ ! -e "$TASK_KNOWN_HOSTS" ] && [ ! -L "$TASK_KNOWN_HOSTS" ] || return 1
  printf '%s %s\n' "$task_selected_host" "$TASK_VERIFIED_HOSTKEY" > "$TASK_KNOWN_HOSTS" || return 1
  /bin/chmod 600 "$TASK_KNOWN_HOSTS" || return 1
  TASK_SSH_TRUST_OPTIONS=(
    -F /dev/null
    -o HostKeyAlgorithms=ssh-ed25519
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$TASK_KNOWN_HOSTS"
    -o GlobalKnownHostsFile=/dev/null
    -o VerifyHostKeyDNS=no
    -o UpdateHostKeys=no
  )
}

task_marker_valid() {
  [ -f "$1/.production-receiver-v1" ] && [ ! -L "$1/.production-receiver-v1" ] &&
    [ "$(/bin/cat "$1/.production-receiver-v1")" = "$TASK_FORMAT" ]
}

task_no_symlink_ancestors() {
  local task_check="$1"
  while [ "$task_check" != '/' ] && [ -n "$task_check" ]; do
    [ ! -L "$task_check" ] || return 1
    task_check="$(/usr/bin/dirname "$task_check")"
  done
}

task_prepare_target() {
  local task_parent="$1"
  [ -d "$task_parent" ] && [ -w "$task_parent" ] && [ "$task_parent" != '/' ] || return 1
  task_no_symlink_ancestors "$task_parent" || return 1
  TASK_ROOT="$task_parent/Production-Migration-Receive"
  task_no_symlink_ancestors "$TASK_ROOT" || return 1
  if [ -e "$TASK_ROOT" ]; then
    [ -d "$TASK_ROOT" ] && task_marker_valid "$TASK_ROOT" || return 1
  else
    /bin/mkdir "$TASK_ROOT" || return 1
    # 只写自己新建的目录；不存在标记的已有目录绝不接管。
    printf '%s\n' "$TASK_FORMAT" > "$TASK_ROOT/.production-receiver-v1" || return 1
  fi
  task_no_symlink_ancestors "$TASK_ROOT/staging" || return 1
  task_no_symlink_ancestors "$TASK_ROOT/运行记录" || return 1
  /bin/mkdir -p "$TASK_ROOT/staging" "$TASK_ROOT/运行记录" || return 1
  /bin/chmod 700 "$TASK_ROOT" "$TASK_ROOT/staging" "$TASK_ROOT/运行记录" || return 1
}

task_record() {
  printf '%s\t%s\t%s\t%s\n' "$(/bin/date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" "$2" "$3" >> "$TASK_STATUS"
}

task_lock_target() {
  local task_previous_pid
  task_no_symlink_ancestors "$TASK_ROOT/.receiver-lock" || return 1
  if [ -e "$TASK_ROOT/.receiver-lock" ]; then
    [ -f "$TASK_ROOT/.receiver-lock/pid" ] && [ ! -L "$TASK_ROOT/.receiver-lock/pid" ] || return 1
    task_previous_pid="$(/bin/cat "$TASK_ROOT/.receiver-lock/pid")"
    case "$task_previous_pid" in ''|*[!0-9]*) return 1 ;; esac
    # 不停止旧进程。仍有进程时直接拒绝第二个接收器。
    if /bin/kill -0 "$task_previous_pid" 2>/dev/null; then return 1; fi
    /bin/rm -f "$TASK_ROOT/.receiver-lock/pid" || return 1
    /bin/rmdir "$TASK_ROOT/.receiver-lock" || return 1
  fi
  /bin/mkdir "$TASK_ROOT/.receiver-lock" || return 1
  printf '%s\n' "$$" > "$TASK_ROOT/.receiver-lock/pid" || return 1
  TASK_LOCK_OWNED=1
}

task_bind_source() {
  local task_identity="$1" task_identity_file="$TASK_ROOT/.source-hardware-id"
  [ ! -L "$task_identity_file" ] || return 1
  if [ -e "$task_identity_file" ]; then
    [ "$(/bin/cat "$task_identity_file")" = "$task_identity" ] || return 1
  else
    printf '%s\n' "$task_identity" > "$task_identity_file" || return 1
  fi
}

task_run_root() {
  local task_idx="$1" task_phase="$2" task_path task_key task_dest task_code task_source_arg
  local task_args=()
  local task_pipe_status=()
  task_path="${TASK_ROOT_PATHS[$task_idx]}"
  task_key="${TASK_ROOT_KEYS[$task_idx]}"
  task_dest="$TASK_ROOT/staging$task_path"
  task_marker_valid "$TASK_ROOT" || return 91
  task_no_symlink_ancestors "$(/usr/bin/dirname "$task_dest")" || return 92
  task_no_symlink_ancestors "$task_dest" || return 92
  if [ "${TASK_ROOT_KINDS[$task_idx]}" = file ]; then
    [ ! -d "$task_dest" ] || return 92
    /bin/mkdir -p "$(/usr/bin/dirname "$task_dest")" || return 93
    task_source_arg="$TASK_REMOTE:$(task_quote_remote "$task_path")"
  else
    /bin/mkdir -p "$task_dest" || return 93
    task_source_arg="$TASK_REMOTE:$(task_quote_remote "$task_path/")"
    task_dest="$task_dest/"
  fi
  task_args=(-a --partial --itemize-changes)
  if [ "$task_phase" = 'DRY_RUN' ]; then
    task_args+=(-n)
  else
    task_args+=(--progress)
  fi
  printf '\n[%s] %s %s\n' "$task_phase" "$task_key" "$task_path" | /usr/bin/tee -a "$TASK_LOG"
  "$TASK_RSYNC" "${task_args[@]}" "${TASK_EXCLUDES[@]}" -e "$TASK_RSH" "$task_source_arg" "$task_dest" 2>&1 | /usr/bin/tee -a "$TASK_LOG"
  task_pipe_status=("${PIPESTATUS[@]}")
  task_code=${task_pipe_status[0]}
  [ "${task_pipe_status[1]}" -eq 0 ] || task_code=94
  if [ "$task_code" -eq 0 ]; then
    # RSYNC_OK 仅表示传输工具成功，不是最终 SHA 验证或生产验收通过。
    task_record "$task_key" "$task_phase" 'RSYNC_OK' || return 95
  else
    task_record "$task_key" "$task_phase" "RSYNC_FAILED_$task_code" || return 95
  fi
  return "$task_code"
}

task_check_tool_options() {
  local task_help
  task_help="$("$TASK_RSYNC" --help 2>&1)" || return 1
  local task_flag
  for task_flag in '--partial' '--progress' '--itemize-changes'; do
    case "$task_help" in *"$task_flag"*) ;; *) return 1 ;; esac
  done
}


task_quote_remote() {
  printf "'"
  printf '%s' "$1" | /usr/bin/sed "s/'/'\\\\''/g"
  printf "'"
}

task_path_safe() {
  case "$1" in ''|*[$'\r\n\t']*|*$'\x60'*|*'$'*|*';'*|*'|'*|*'&'*|*'<'*|*'>'*|*'\'*) return 1 ;; esac
  case "/${1#/}/" in *'/../'*|*'/./'*|*'//'*) return 1 ;; esac
}

task_config_error() {
  printf '配置无效：%s\n' "$1" >&2
  return 1
}

task_load_config() {
  local task_cfg="$1" task_line task_key task_value task_seen_key task_cfg_dir task_index task_field task_max=0 task_i
  local task_seen=() task_rels=() task_kinds=() task_optional=()
  [ -f "$task_cfg" ] && [ ! -L "$task_cfg" ] && [ -r "$task_cfg" ] || { task_config_error '文件不存在、不可读或是符号链接'; return 1; }
  TASK_REMOTE_USER='' TASK_SOURCE_HOME='' TASK_SOURCE_HOST='' TASK_PUBLIC_KEY_FILE='' TASK_PINNED_FINGERPRINT=''
  TASK_ROOT_KEYS=() TASK_ROOT_PATHS=() TASK_ROOT_KINDS=() TASK_ROOT_OPTIONAL=()
  while IFS= read -r task_line || [ -n "$task_line" ]; do
    task_line="${task_line%$'\r'}"
    case "$task_line" in ''|'#'*) continue ;; esac
    case "$task_line" in *=*) ;; *) task_config_error '必须是无引号的 KEY=value；不支持 shell 命令'; return 1 ;; esac
    task_key="${task_line%%=*}"
    task_value="${task_line#*=}"
    for task_seen_key in ${task_seen[@]+"${task_seen[@]}"}; do
      [ "$task_seen_key" != "$task_key" ] || { task_config_error '键重复'; return 1; }
    done
    task_seen+=("$task_key")
    case "$task_key" in
      SOURCE_USER) TASK_REMOTE_USER="$task_value" ;;
      SOURCE_HOME) TASK_SOURCE_HOME="$task_value" ;;
      SOURCE_HOST) TASK_SOURCE_HOST="$task_value" ;;
      SOURCE_HOST_KEY_FILE) TASK_PUBLIC_KEY_FILE="$task_value" ;;
      SOURCE_HOST_KEY_SHA256) TASK_PINNED_FINGERPRINT="$task_value" ;;
      *)
        if [[ "$task_key" =~ ^ROOT_([1-9][0-9]?)_(REL|KIND|OPTIONAL)$ ]]; then
          task_index="${BASH_REMATCH[1]}"
          task_field="${BASH_REMATCH[2]}"
          [ "$task_index" -le 32 ] || { task_config_error '最多 32 个根'; return 1; }
          [ "$task_index" -le "$task_max" ] || task_max="$task_index"
          case "$task_field" in
            REL) task_rels[$task_index]="$task_value" ;;
            KIND) task_kinds[$task_index]="$task_value" ;;
            OPTIONAL) task_optional[$task_index]="$task_value" ;;
          esac
        else
          task_config_error '出现白名单之外的键；不要填写密码、API Key 或 shell 命令'; return 1
        fi ;;
    esac
  done < "$task_cfg"
  [[ "$TASK_REMOTE_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || { task_config_error 'SOURCE_USER 无效'; return 1; }
  case "$TASK_SOURCE_HOST" in ''|*[!a-zA-Z0-9.-]*|-*|.*) task_config_error 'SOURCE_HOST 只允许主机名或 IPv4'; return 1 ;; esac
  case "$TASK_SOURCE_HOME" in /*) ;; *) task_config_error 'SOURCE_HOME 必须为源电脑绝对路径'; return 1 ;; esac
  [ "$TASK_SOURCE_HOME" != '/' ] && [ "${TASK_SOURCE_HOME%/}" = "$TASK_SOURCE_HOME" ] && task_path_safe "$TASK_SOURCE_HOME" || { task_config_error 'SOURCE_HOME 不能是根目录、含尾斜线或特殊路径'; return 1; }
  case "$TASK_PUBLIC_KEY_FILE" in ''|*/*|*[$'\r\n\t']*|.*) task_config_error '公钥必须是配置同目录下的 .pub 文件名'; return 1 ;; esac
  case "$TASK_PUBLIC_KEY_FILE" in *.pub) ;; *) task_config_error '公钥文件须以 .pub 结尾'; return 1 ;; esac
  [[ "$TASK_PINNED_FINGERPRINT" =~ ^SHA256:[A-Za-z0-9+/]{43}$ ]] || { task_config_error '公钥 SHA256 指纹格式无效'; return 1; }
  [ "$task_max" -gt 0 ] || { task_config_error '至少需要 ROOT_1_REL/KIND/OPTIONAL'; return 1; }
  for ((task_i=1; task_i<=task_max; task_i++)); do
    task_value="${task_rels[$task_i]:-}"
    case "$task_value" in ''|/*) task_config_error 'ROOT 编号须连续，REL 须为非空相对路径'; return 1 ;; esac
    task_path_safe "$task_value" || { task_config_error 'ROOT 路径不能逃出源 HOME 或包含 shell 片段'; return 1; }
    case "$task_value" in .ssh|.ssh/*|.aws|.aws/*|.codex|.codex/auth*|.agents|.cache/huggingface|Library|Library/Keychains|Library/Keychains/*|.env|.env.*)
      task_config_error '禁止整体迁移账号/应用凭据目录；只可指定必要公开模型或 Skill 子目录'; return 1 ;;
    esac
    [ "${task_value%/}" = "$task_value" ] || { task_config_error 'ROOT 路径不要带尾斜线'; return 1; }
    case "${task_kinds[$task_i]:-}" in dir|file) ;; *) task_config_error '每根 KIND 必须明确为 dir 或 file'; return 1 ;; esac
    case "${task_optional[$task_i]:-}" in 0|1) ;; *) task_config_error '每根 OPTIONAL 必须明确为 0 或 1'; return 1 ;; esac
    TASK_ROOT_KEYS+=("R$task_i")
    TASK_ROOT_PATHS+=("$TASK_SOURCE_HOME/$task_value")
    TASK_ROOT_KINDS+=("${task_kinds[$task_i]}")
    TASK_ROOT_OPTIONAL+=("${task_optional[$task_i]}")
  done
  task_cfg_dir="$(cd "$(dirname "$task_cfg")" && pwd -P)" || return 1
  TASK_CONFIG_PATH="$task_cfg_dir/$(basename "$task_cfg")"
  TASK_PUBLIC_KEY_FILE="$task_cfg_dir/$TASK_PUBLIC_KEY_FILE"
}

task_main() {
  [ "$(/usr/bin/uname -s)" = Darwin ] || task_fail '此工具只用于新 Mac，不会在其他系统上迁移。'
  local task_cfg="${1:-$TASK_SCRIPT_DIR/source_config.env}" task_local_name task_host task_parent task_free task_fs task_choice task_count=0 task_i task_fail_count task_remote_name task_local_uuid task_remote_uuid
  for task_tool in "$TASK_SSH" "$TASK_RSYNC" /usr/bin/osascript /usr/bin/ssh-keygen; do
    [ -x "$task_tool" ] || task_fail "缺少系统工具：$task_tool"
  done
  if [ ! -f "$task_cfg" ]; then
    task_cfg="$(/usr/bin/osascript <<'APPLESCRIPT'
POSIX path of (choose file with prompt "选择由旧电脑代理私密交付的 source_config.env（不是示例模板；不含登录密码）。")
APPLESCRIPT
    )" || task_cancel
  fi
  task_load_config "$task_cfg" || task_fail '迁移配置检查失败。详见终端；请让旧机代理修正私密配置，不要编辑程序绕过保护。'
  task_validate_hostkey "$TASK_PUBLIC_KEY_FILE" || task_fail '配置指定的公钥缺失、损坏或指纹不匹配。拒绝连接；请重新取得旧机核实后的配置和公钥。'
  task_local_name="$(/usr/sbin/scutil --get LocalHostName 2>/dev/null || /bin/hostname -s)"
  case "$TASK_SOURCE_HOST" in "$task_local_name"|"$task_local_name.local"|localhost|127.*|0.0.0.0) task_fail '源地址指向本机。必须在新电脑运行接收器。' ;; esac
  task_check_tool_options || task_fail '本机 rsync 选项不兼容，未连接或传输。'
  task_dialog '只做预同步，不会启动生产' '在新 Mac 运行。旧机须由主人开启远程登录。工具将严格核对私密配置中的旧机公钥，只需输入旧机登录密码；不保存密码、不修改全局 SSH 信任。不删除任何一端文件，也不复制密钥文件。' >/dev/null || task_cancel
  task_host="$(/usr/bin/osascript - "$TASK_SOURCE_HOST" <<'APPLESCRIPT'
on run argv
  text returned of (display dialog "旧电脑的局域网地址；可改为旧机现在的 IP。公钥仍必须匹配同一旧机。" with title "连接旧电脑" default answer (item 1 of argv) buttons {"取消", "继续"} default button "继续" cancel button "取消")
end run
APPLESCRIPT
  )" || task_cancel
  case "$task_host" in ''|*[!a-zA-Z0-9.-]*|-*|.*) task_fail '地址只能是主机名或 IPv4，不能含命令、用户名或端口。' ;; esac
  case "$task_host" in "$task_local_name"|"$task_local_name.local"|localhost|127.*|0.0.0.0) task_fail '不能以本机作为源。' ;; esac
  TASK_REMOTE="$TASK_REMOTE_USER@$task_host"
  task_parent="$(/usr/bin/osascript <<'APPLESCRIPT'
POSIX path of (choose folder with prompt "选择新机本地磁盘或直连移动硬盘，至少留 12 GiB；工具会创建专用 Production-Migration-Receive 目录。")
APPLESCRIPT
  )" || task_cancel
  task_parent="${task_parent%/}"
  [ -n "$task_parent" ] || task_fail '不能选择磁盘根。'
  task_fs="$(/bin/df -Pk "$task_parent" | /usr/bin/awk 'NR==2 {print $1}')"
  case "$task_fs" in /dev/*) ;; *) task_fail '请用新机本地或直连磁盘，不能写网络共享盘，以免写回旧机。' ;; esac
  task_free="$(/bin/df -Pk "$task_parent" | /usr/bin/awk 'NR==2 {print $4}')"
  case "$task_free" in ''|*[!0-9]*) task_fail '无法确认目标余量。' ;; esac
  [ "$task_free" -ge "$TASK_MIN_FREE_KB" ] || task_fail '目标余量不足 12 GiB。'
  task_choice="$(/usr/bin/osascript <<'APPLESCRIPT'
button returned of (display dialog "是否同时复制配置中 OPTIONAL=1 的依赖目录？例如可重下载的模型。配置中必需项始终复制。" with title "可选依赖" buttons {"取消", "仅必需资料", "包含可选依赖"} default button "包含可选依赖" cancel button "取消")
APPLESCRIPT
  )" || task_cancel
  [ "$task_choice" != '包含可选依赖' ] || TASK_INCLUDE_MODELS=1
  task_dialog '确认后先预演' "源：$TASK_REMOTE
源 HOME：$TASK_SOURCE_HOME
目标：$task_parent/Production-Migration-Receive/staging$TASK_SOURCE_HOME
逐项复制配置清单，严格固定旧机公钥；不删除、不启动生产。接下来在终端按提示输入旧机登录密码（输入不显示）。" >/dev/null || task_cancel
  task_prepare_target "$task_parent" || task_fail '目标含无关内容/链接或不可写，未覆盖。请选择干净位置，或原工具创建的带标记目录。'
  TASK_LOG="$TASK_ROOT/运行记录/$(/bin/date '+%Y%m%d_%H%M%S')_$$.log"
  TASK_STATUS="$TASK_ROOT/运行记录/roots_status.tsv"
  [ ! -L "$TASK_STATUS" ] && [ ! -e "$TASK_LOG" ] || task_fail '日志位置异常。'
  trap task_cleanup EXIT
  task_lock_target || task_fail '同一接收器正在运行或锁异常，不并发写同一目录。'
  printf 'PRE_SYNC_ONLY\nsource=%s\nconfig=%s\n' "$TASK_REMOTE" "$TASK_CONFIG_PATH" > "$TASK_LOG"
  TASK_SOCKET_DIR="$(/usr/bin/mktemp -d /tmp/production-migrate-ssh.XXXXXX)" || task_fail '无法建立私有连接目录。'
  task_prepare_pinned_hostkey "$TASK_PUBLIC_KEY_FILE" "$task_host" || task_fail '无法固定旧机公钥。'
  trap 'task_record ALL INTERRUPTED INTERRUPTED; exit 130' INT TERM
  printf '\n已固定旧机公钥。请按提示输入旧电脑登录密码（输入不显示）。\n'
  "$TASK_SSH" "${TASK_SSH_TRUST_OPTIONS[@]}" -M -N -f -S "$TASK_SOCKET_DIR/control" -o ControlMaster=yes -o ControlPersist=600 -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o NumberOfPasswordPrompts=3 "$TASK_REMOTE" || task_fail '连接失败。检查旧机远程登录、地址、用户名及密码；主机密钥不符时停止，不能关闭验证。'
  TASK_SSH_ACTIVE=1
  TASK_RSH="/usr/bin/ssh -F /dev/null -o HostKeyAlgorithms=ssh-ed25519 -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$TASK_KNOWN_HOSTS -o GlobalKnownHostsFile=/dev/null -o VerifyHostKeyDNS=no -o UpdateHostKeys=no -S $TASK_SOCKET_DIR/control -o ControlMaster=no -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
  task_remote_name="$("$TASK_SSH" "${TASK_SSH_TRUST_OPTIONS[@]}" -S "$TASK_SOCKET_DIR/control" -o BatchMode=yes "$TASK_REMOTE" '/usr/sbin/scutil --get LocalHostName' 2>/dev/null)" || task_fail '无法确认源设备名称。'
  [ "$task_remote_name" != "$task_local_name" ] || task_fail '两端设备名相同，暂停核实，避免复制自身。'
  task_local_uuid="$(/usr/sbin/ioreg -rd1 -c IOPlatformExpertDevice | /usr/bin/awk -F '"' '/IOPlatformUUID/ {print $(NF-1)}')"
  task_remote_uuid="$("$TASK_SSH" "${TASK_SSH_TRUST_OPTIONS[@]}" -S "$TASK_SOCKET_DIR/control" -o BatchMode=yes "$TASK_REMOTE" "/usr/sbin/ioreg -rd1 -c IOPlatformExpertDevice | /usr/bin/awk -F '\"' '/IOPlatformUUID/ {print \$(NF-1)}'" 2>/dev/null)" || task_fail '无法核实源硬件。'
  [ -n "$task_local_uuid" ] && [ -n "$task_remote_uuid" ] && [ "$task_local_uuid" != "$task_remote_uuid" ] || task_fail '设备标识为空或为同一台，未复制。'
  task_bind_source "$task_remote_uuid" || task_fail '本接收目录以前绑定另一台来源设备。拒绝混合两套资料。'
  task_fail_count=0
  for ((task_i=0; task_i<${#TASK_ROOT_PATHS[@]}; task_i++)); do
    if [ "${TASK_ROOT_OPTIONAL[$task_i]}" -eq 1 ] && [ "$TASK_INCLUDE_MODELS" -eq 0 ]; then continue; fi
    task_count=$((task_count + 1))
    task_run_root "$task_i" DRY_RUN || task_fail_count=$((task_fail_count + 1))
  done
  [ "$task_count" -gt 0 ] || task_fail '没有选择任何可复制条目。'
  [ "$task_fail_count" -eq 0 ] || task_fail "预演 $task_fail_count 项失败，没有正式复制。请查日志：$TASK_LOG"
  task_dialog '预演完成：开始预同步？' "$task_count 项预演完成。清单已显示在终端。
日志：$TASK_LOG
允许再次运行增量恢复。源机仍可能写入，此次不是一致性快照、不是最终迁移成功。" >/dev/null || task_cancel
  task_fail_count=0
  for ((task_i=0; task_i<${#TASK_ROOT_PATHS[@]}; task_i++)); do
    if [ "${TASK_ROOT_OPTIONAL[$task_i]}" -eq 1 ] && [ "$TASK_INCLUDE_MODELS" -eq 0 ]; then continue; fi
    task_run_root "$task_i" COPY || task_fail_count=$((task_fail_count + 1))
  done
  [ "$task_fail_count" -eq 0 ] || { task_record ALL COPY PRE_SYNC_INCOMPLETE; task_fail "预同步 $task_fail_count 项失败。已收到文件保留，可选原目标再次增量恢复；不能启动生产。"; }
  task_record ALL COPY PRE_SYNC_RSYNC_OK_NOT_FINAL_VERIFIED || task_fail '复制返回成功，但状态写入失败。不能认定完成。'
  [ ! -L "$TASK_ROOT/预同步状态.txt" ] || task_fail '状态文件是链接，未覆盖。'
  printf '%s\n' 'PRE_SYNC_ONLY: rsync 成功，不代表最终 SHA/环境/生产权验收。' > "$TASK_ROOT/预同步状态.txt" || task_fail '无法保存状态。'
  task_notice "预同步工具已结束；$task_count 项 rsync 返回成功。
接收位置：$TASK_ROOT/staging
尚未最终迁移：由代理安排旧机停写、最后增量、SHA 校验、环境重建、唯一生产权交接。未启动生产或发行。"
}

case "${1:-}" in
  --self-test) exec /bin/bash "$TASK_SCRIPT_DIR/test_receiver.sh" ;;
  --library-only) return 0 2>/dev/null || exit 0 ;;
  --config) [ "$#" -eq 2 ] || { printf 'Usage: receiver.sh --config source_config.env\n' >&2; exit 2; }; task_main "$2" ;;
  '') task_main ;;
  *) printf 'Usage: receiver.sh [--config source_config.env | --self-test]\n' >&2; exit 2 ;;
esac

