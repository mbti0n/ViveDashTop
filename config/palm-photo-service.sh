#!/bin/sh
set -u

APP_DIR="$HOME/palm-photo"
STATE_DIR="$HOME/.local/state/palm-photo"
PID_FILE="$STATE_DIR/gesture.pid"
LOG_FILE="$STATE_DIR/gesture.log"

service_pid() {
    [ -r "$PID_FILE" ] || return 1
    pid=$(cat "$PID_FILE")
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$pid" 2>/dev/null || return 1
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\000' ' ' < "/proc/$pid/cmdline" | grep -F "$APP_DIR/open_random_photo.py" >/dev/null || return 1
    printf '%s\n' "$pid"
}

case "${1:-ensure}" in
    ensure|start)
        mkdir -p "$STATE_DIR"
        if pid=$(service_pid); then
            printf 'Palm photo gesture service running (PID %s)\n' "$pid"
        else
            owner_pid=${2:-$(pgrep -xo wtfutil 2>/dev/null || true)}
            if [ -n "$owner_pid" ]; then
                nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/open_random_photo.py" \
                    --owner-pid "$owner_pid" </dev/null >>"$LOG_FILE" 2>&1 &
            else
                nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/open_random_photo.py" \
                    </dev/null >>"$LOG_FILE" 2>&1 &
            fi
            pid=$!
            printf '%s\n' "$pid" >"$PID_FILE"
            printf 'Starting palm photo gesture service (PID %s)\n' "$pid"
        fi
        ;;
    stop)
        if pid=$(service_pid); then
            kill -TERM "$pid"
            attempts=0
            while kill -0 "$pid" 2>/dev/null && [ "$attempts" -lt 30 ]; do
                sleep 0.1
                attempts=$((attempts + 1))
            done
            rm -f "$PID_FILE"
            printf 'Stopped palm photo gesture service (PID %s)\n' "$pid"
        else
            rm -f "$PID_FILE"
            printf 'Palm photo gesture service is not running\n'
        fi
        ;;
    status)
        if pid=$(service_pid); then
            printf 'Palm photo gesture service running (PID %s)\n' "$pid"
        else
            printf 'Palm photo gesture service is not running\n'
            exit 1
        fi
        ;;
    *)
        printf 'Usage: %s [start|stop|status]\n' "$0" >&2
        exit 2
        ;;
esac
