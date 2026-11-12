#!/bin/bash
# Local Plesk test server for Runway development: the official plesk/plesk image with real
# systemd, driven by the same script CI uses (.github/scripts/plesk-e2e.sh). Linux, macOS and
# Windows with Git Bash; scripts/plesk-dev.ps1 is the PowerShell version.
#
#   scripts/plesk-dev.sh up                    start the container, wait for the panel, print a login link
#   scripts/plesk-dev.sh install               build dist/runway-<version>-<release>.zip, install or upgrade it
#   scripts/plesk-dev.sh install --no-frontend package the existing frontend build (faster)
#   scripts/plesk-dev.sh login                 print a one-time administrator login link
#   scripts/plesk-dev.sh prepare               subscription gotest.local, customer cust1, Go toolchain, sample app
#   scripts/plesk-dev.sh test                  helper-smoke, api-smoke, customer-smoke, Go part of runtime-e2e
#   scripts/plesk-dev.sh status                container, extension and Runway units
#   scripts/plesk-dev.sh shell                 root shell inside the container
#   scripts/plesk-dev.sh logs [-f]             panel log and the journal of the Runway units (-f follows the journal)
#   scripts/plesk-dev.sh down                  remove the container (toolchains and test data are lost)
#
# Environment: CONTAINER (runway-plesk), PLESK_IMAGE (plesk/plesk:latest), PANEL_PORT (18880:
# http://localhost:18880), PANEL_SSL_PORT (18443: https://localhost:18443), HTTP_PORT (18080: the
# hosted sites; add "127.0.0.1 gotest.local" to the hosts file and open http://gotest.local:18080),
# E2E_RUNTIMES (go: runtimes of tests/runtime-e2e.sh in "test", "" skips it), SMOKE_SUITES (the
# suites of "test": helper,api,customer,runtime), WAIT_MINUTES (25).
# The first "up" downloads the image (about 2 GB); Plesk then needs a few minutes to initialise.
set -euo pipefail
# pwd -W: Windows path in Git Bash (docker cp does not understand /e/... with MSYS_NO_PATHCONV).
ROOT=$(cd "$(dirname "$0")/.." && { pwd -W 2>/dev/null || pwd; })
E2E=$ROOT/.github/scripts/plesk-e2e.sh
export CONTAINER=${CONTAINER:-runway-plesk}
export PLESK_IMAGE=${PLESK_IMAGE:-plesk/plesk:latest}
export PANEL_PORT=${PANEL_PORT:-18880}
export E2E_RUNTIMES=${E2E_RUNTIMES-go}
PANEL_SSL_PORT=${PANEL_SSL_PORT:-18443}
HTTP_PORT=${HTTP_PORT:-18080}
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    # "python3" may be a non-working Microsoft Store alias on Windows: probe it.
    for candidate in python3 python; do
        if "$candidate" -c 'import json' >/dev/null 2>&1; then PY=$candidate; break; fi
    done
fi

# Git Bash on Windows: no path conversion for docker arguments.
dock() { MSYS_NO_PATHCONV=1 docker "$@"; }
in_c() { dock exec "$CONTAINER" "$@"; }
usage() { sed -n '2,22p' "$0"; }
state() {
    # docker inspect prints an empty line (and fails) for a missing container.
    local status
    status=$(dock inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null) || status=absent
    echo "${status:-absent}"
}
need_running() {
    if [ "$(state)" != "running" ]; then
        echo "the container $CONTAINER is not running: scripts/plesk-dev.sh up" >&2
        exit 1
    fi
}
login_link() {
    local rel
    rel=$(in_c plesk bin admin --get-login-link -relative-url | tr -d '\r') || return 1
    echo "http://localhost:$PANEL_PORT$rel"
}
package_name() {
    local version release
    version=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$ROOT/src/meta.xml")
    release=$(sed -n 's:.*<release>\(.*\)</release>.*:\1:p' "$ROOT/src/meta.xml")
    echo "runway-$version-$release.zip"
}

cmd_up() {
    case "$(state)" in
        running)
            echo "$CONTAINER is already running"
            bash "$E2E" wait ;;
        absent) PUBLISH="$PANEL_SSL_PORT:8443 $HTTP_PORT:80" bash "$E2E" start ;;
        *)
            echo "== starting the existing container $CONTAINER"
            dock start "$CONTAINER" >/dev/null
            bash "$E2E" wait ;;
    esac
    echo "panel: http://localhost:$PANEL_PORT (https://localhost:$PANEL_SSL_PORT), sites: http://localhost:$HTTP_PORT"
    local link
    link=$(login_link)
    echo "login: $link"
}

cmd_install() {
    local frontend=() package
    if [ "${1:-}" = "--no-frontend" ]; then frontend=(--no-frontend); shift; fi
    [ $# -eq 0 ] || { usage; exit 2; }
    need_running
    [ -n "$PY" ] || { echo "python3 (3.8+) is needed for build.py" >&2; exit 1; }
    (cd "$ROOT" && "$PY" build.py --strict ${frontend[@]+"${frontend[@]}"})
    package=$(package_name)
    bash "$E2E" install "$ROOT/dist/$package"
    local link
    link=$(login_link)
    echo "login: $link"
}

cmd_status() {
    dock ps -a --filter "name=^/$CONTAINER\$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    [ "$(state)" = "running" ] || exit 0
    echo
    in_c plesk bin extension --list | grep -E '^runway\b' || echo "runway: not installed"
    echo
    in_c systemctl list-units --all --no-pager --plain 'runway-*' | sed '/^$/,$d'
}

cmd_shell() {
    need_running
    # Git Bash (mintty) needs winpty for an interactive docker session.
    if command -v winpty >/dev/null 2>&1; then exec winpty docker exec -it "$CONTAINER" bash; fi
    exec docker exec -it "$CONTAINER" bash
}

cmd_logs() {
    need_running
    if [ "${1:-}" = "-f" ]; then
        # A pty, so that Ctrl+C reaches journalctl instead of leaving it running in the container.
        if command -v winpty >/dev/null 2>&1; then exec winpty docker exec -it "$CONTAINER" journalctl -f -n 50 -u 'runway-*'; fi
        exec docker exec -it "$CONTAINER" journalctl -f -n 50 -u 'runway-*'
    fi
    in_c bash -c 'echo "== /var/log/plesk/panel.log"; tail -n 50 /var/log/plesk/panel.log 2>/dev/null; echo;
        echo "== journalctl -u runway-*"; journalctl --no-pager -n 100 -u "runway-*" 2>&1'
}

command=${1:-}
[ $# -gt 0 ] && shift
case "$command" in
    up) cmd_up ;;
    install) cmd_install "$@" ;;
    login) need_running; login_link ;;
    prepare) need_running; bash "$E2E" prepare ;;
    test) need_running; bash "$E2E" smoke ;;
    status) cmd_status ;;
    shell) cmd_shell ;;
    logs) cmd_logs "$@" ;;
    down) bash "$E2E" stop; echo "$CONTAINER removed" ;;
    *) usage; exit 2 ;;
esac
