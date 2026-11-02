#!/bin/bash
set -u

python_bin="${MOVIEPILOT_PYTHON:?MOVIEPILOT_PYTHON is required}"
log_file="${MOVIEPILOT_LOG_FILE:?MOVIEPILOT_LOG_FILE is required}"
backend_pid=""
resource_restart_done=0
restart_marker="${TRIM_PKGVAR:?}/.backend-restart"
rm -f -- "$restart_marker"

resource_restart_requested() {
    awk '
        index($0, "[fnOS] MoviePilot service starting") { requested = 0 }
        index($0, "资源包更新完成，开始重启服务") { requested = 1 }
        END { exit requested ? 0 : 1 }
    ' "$log_file" 2>/dev/null
}

stop_backend() {
    if [ -n "$backend_pid" ] && kill -0 "$backend_pid" 2>/dev/null; then
        kill "$backend_pid" 2>/dev/null || true
        wait "$backend_pid" 2>/dev/null || true
    fi
    exit 0
}
trap stop_backend TERM INT

while true; do
    "$python_bin" -u -m app.main &
    backend_pid=$!
    wait "$backend_pid"
    exit_code=$?
    backend_pid=""
    if [ -f "$restart_marker" ]; then
        rm -f -- "$restart_marker"
        echo "[fnOS] MoviePilot V3 正在按应用请求重新启动后台服务"
        sleep 1
        continue
    fi

    # Replacing the loaded sites extension can terminate Python with SIGSEGV.
    # The resource marker, scoped to this start cycle, is the reliable signal.
    if [ "$resource_restart_done" -eq 0 ] && resource_restart_requested; then
        resource_restart_done=1
        echo "[fnOS] 资源包更新完成，正在自动重启 MoviePilot 后台服务（退出码 ${exit_code}）..."
        sleep 2
        continue
    fi
    exit "$exit_code"
done
