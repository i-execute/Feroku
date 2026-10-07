#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT_DIR/Storage/Compat.sh"
PARENT_PID="$PPID"
PARENT_COMMAND="$(ps -p "$PARENT_PID" -o args= 2>/dev/null || true)"
DAEMON_PID="$(cat "$ROOT_DIR/sessions/.daemon.pid" 2>/dev/null || true)"
DAEMON_COMMAND="$(ps -p "$DAEMON_PID" -o args= 2>/dev/null || true)"
DAEMON_CWD="$(readlink "/proc/$DAEMON_PID/cwd" 2>/dev/null || true)"

if [ ! -f "$ROOT_DIR/feroku/__main__.py" ]; then
    printf '%s\n' "Refusing to remove an invalid installation path: $ROOT_DIR" >&2
    exit 1
fi

is_daemon_command() {
    printf '%s' "$1" | grep -Eq 'python([^ ]*)? .*[-]m feroku' \
        || compat_is_daemon_command "$1"
}

if [ "$(id -u)" -eq 0 ]; then
    systemctl disable feroku.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/feroku.service
    rm -f /etc/systemd/system/multi-user.target.wants/feroku.service
    compat_disable_system_service
    systemctl daemon-reload >/dev/null 2>&1 || true
    rm -rf -- "$ROOT_DIR"
    systemctl stop feroku.service >/dev/null 2>&1 || true
    compat_stop_system_service
else
    systemctl --user disable feroku.service >/dev/null 2>&1 || true
    rm -f "$HOME/.config/systemd/user/feroku.service"
    rm -f "$HOME/.config/systemd/user/default.target.wants/feroku.service"
    compat_disable_user_service
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    rm -rf -- "$ROOT_DIR"
    systemctl --user stop feroku.service >/dev/null 2>&1 || true
    compat_stop_user_service
fi

if [[ "$DAEMON_PID" =~ ^[0-9]+$ ]] \
    && [ "$DAEMON_CWD" = "$ROOT_DIR" ] \
    && is_daemon_command "$DAEMON_COMMAND"; then
    kill -TERM "$DAEMON_PID" >/dev/null 2>&1 || true
fi

if is_daemon_command "$PARENT_COMMAND"; then
    kill -TERM "$PARENT_PID" >/dev/null 2>&1 || true
fi

printf '%s\n' "Feroku userbot removed."
