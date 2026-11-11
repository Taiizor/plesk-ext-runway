#!/bin/bash
# End-to-end test of a Runway package in the official Plesk Docker image (real systemd).
# Used by .github/workflows/ci.yml; also runs on a Linux or macOS machine with Docker.
#
#   .github/scripts/plesk-e2e.sh start             # start the Plesk container, wait for the panel
#   .github/scripts/plesk-e2e.sh install ZIP       # install or upgrade the extension package
#   .github/scripts/plesk-e2e.sh prepare           # customer, subscription, Go toolchain, Go sample app
#   .github/scripts/plesk-e2e.sh smoke             # helper-smoke, api-smoke, customer-smoke and the Go
#                                                  # part of runtime-e2e (RUNWAY_E2E_RUNTIMES=go)
#   .github/scripts/plesk-e2e.sh diagnostics DIR   # copy logs into DIR (after a failure)
#   .github/scripts/plesk-e2e.sh stop              # remove the container
#
# Environment: CONTAINER (runway-plesk), PLESK_IMAGE (plesk/plesk:latest), PANEL_PORT (18880),
# DOMAIN (gotest.local), SYSUSER (gotestuser, the name tests/helper-smoke.sh expects),
# CUSTOMER (cust1, owner of DOMAIN for tests/customer-smoke.sh), GO_VERSION (1.27.4),
# WAIT_MINUTES (25), E2E_RUNTIMES (go: runtimes of tests/runtime-e2e.sh in "smoke", "" skips it).
set -euo pipefail
CONTAINER=${CONTAINER:-runway-plesk}
PLESK_IMAGE=${PLESK_IMAGE:-plesk/plesk:latest}
PANEL_PORT=${PANEL_PORT:-18880}
DOMAIN=${DOMAIN:-gotest.local}
SYSUSER=${SYSUSER:-gotestuser}
CUSTOMER=${CUSTOMER:-cust1}
E2E_RUNTIMES=${E2E_RUNTIMES-go}
GO_VERSION=${GO_VERSION:-1.27.4}
WAIT_MINUTES=${WAIT_MINUTES:-25}
# pwd -W: Windows path in Git Bash (docker cp does not understand /e/... with MSYS_NO_PATHCONV).
ROOT=$(cd "$(dirname "$0")/../.." && { pwd -W 2>/dev/null || pwd; })
HELPER=/opt/runway/bin/runway-helper
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
in_ci() { dock exec -i "$CONTAINER" "$@"; }
log() { echo "== $*"; }
json_field() { "${PY:-python3}" -c "import json,sys; print(json.load(sys.stdin).get('$1', ''))"; }
site_id() { in_c plesk db -Ne "select id from domains where name='$DOMAIN'" | tr -d '\r\n'; }

cmd_start() {
    dock rm -f "$CONTAINER" >/dev/null 2>&1 || true
    # The same flags as the documented local test environment (README.md, "Development").
    dock run -d --name "$CONTAINER" --hostname plesk.runway.test \
        --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
        -v /sys/fs/cgroup:/sys/fs/cgroup --cgroupns=host \
        --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
        -p "$PANEL_PORT:8880" "$PLESK_IMAGE" >/dev/null
    log "waiting for Plesk ($PLESK_IMAGE, at most $WAIT_MINUTES minutes)"
    local deadline=$(( $(date +%s) + WAIT_MINUTES * 60 )) state code
    while :; do
        state=$(in_c systemctl is-system-running 2>/dev/null || true)
        code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PANEL_PORT/login_up.php" || true)
        if { [ "$state" = "running" ] || [ "$state" = "degraded" ]; } && [ "$code" = "200" ] \
                && in_c plesk bin admin --get-login-link -relative-url >/dev/null 2>&1; then
            break
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo "Plesk did not become ready (systemd: $state, panel: HTTP $code)" >&2
            exit 1
        fi
        sleep 10
    done
    [ "$state" = "degraded" ] && in_c systemctl --failed --no-pager || true
    in_c plesk version | head -n 2
}

cmd_install() {
    local zip=${1:?usage: install ZIP}
    log "installing $(basename "$zip")"
    dock cp "$zip" "$CONTAINER:/root/runway.zip"
    in_c plesk bin extension --upgrade /root/runway.zip
    in_c plesk bin extension --list | grep -E '^runway\b'
    echo '{}' | in_ci "$HELPER" info | head -c 600
    echo
}

wait_admin_job() {
    local state="" i
    for i in $(seq 1 240); do
        state=$(echo '{"job": "admin"}' | in_ci "$HELPER" job-status | json_field state)
        case "$state" in queued|running) sleep 5 ;; *) break ;; esac
    done
    if [ "$state" != "succeeded" ]; then
        echo "toolchain job: ${state:-unknown}" >&2
        in_c bash -c 'tail -n 60 /var/lib/runway/jobs/admin.log' >&2 || true
        exit 1
    fi
}

cmd_prepare() {
    local ip password home
    if ! in_c plesk bin subscription --info "$DOMAIN" >/dev/null 2>&1; then
        log "creating the subscription $DOMAIN (system user $SYSUSER)"
        ip=$(in_c hostname -I | awk '{print $1}')
        password="Rw9-$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')-Zq"
        in_c plesk bin subscription --create "$DOMAIN" -owner admin -service-plan "Default Domain" \
            -ip "$ip" -login "$SYSUSER" -passwd "$password"
    fi
    echo "site id: $(site_id)"
    # tests/customer-smoke.sh logs in as the owner of the subscription. A license without
    # customer accounts (some trial licenses) refuses this: customer-smoke is skipped then.
    if ! in_c plesk bin customer --info "$CUSTOMER" >/dev/null 2>&1; then
        log "creating the customer $CUSTOMER"
        password="Rw9-$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')-Zq"
        in_c plesk bin customer --create "$CUSTOMER" -name "Runway Test Customer" -passwd "$password" \
            -email "$CUSTOMER@example.com" >/dev/null 2>&1 || echo "customer $CUSTOMER could not be created (license?)"
    fi
    if in_c plesk bin customer --info "$CUSTOMER" >/dev/null 2>&1; then
        in_c plesk bin subscription --change-owner "$DOMAIN" -owner "$CUSTOMER" >/dev/null 2>&1 \
            || echo "the owner of $DOMAIN could not be changed to $CUSTOMER"
    fi
    if ! in_c test -x "/opt/runway/go/$GO_VERSION/bin/go"; then
        log "installing Go $GO_VERSION through the Runway helper"
        echo "{\"runtime\": \"go\", \"version\": \"$GO_VERSION\"}" | in_ci "$HELPER" toolchain-install
        echo
        wait_admin_job
    fi
    in_c "/opt/runway/go/$GO_VERSION/bin/go" version
    log "copying examples/go-hello into apps/$DOMAIN"
    home=$(in_c getent passwd "$SYSUSER" | cut -d: -f6)
    in_c mkdir -p "$home/apps/$DOMAIN"
    dock cp "$ROOT/examples/go-hello/." "$CONTAINER:$home/apps/$DOMAIN/"
    in_c chown -R "$SYSUSER:psacln" "$home/apps"
}

cmd_smoke() {
    local rc=0 id
    id=$(site_id)
    log "tests/helper-smoke.sh (inside the container)"
    dock cp "$ROOT/tests/helper-smoke.sh" "$CONTAINER:/root/helper-smoke.sh"
    in_c env GO_VERSION="$GO_VERSION" bash /root/helper-smoke.sh || rc=1
    log "tests/api-smoke.sh (JSON API through the panel)"
    CONTAINER="$CONTAINER" PANEL="http://localhost:$PANEL_PORT" SITE_ID="$id" DOMAIN="$DOMAIN" \
        APP_ROOT="apps/$DOMAIN" GO_VERSION="$GO_VERSION" RUNWAY_SMOKE_DEPLOY=1 \
        bash "$ROOT/tests/api-smoke.sh" || rc=1
    if in_c plesk bin subscription --info "$DOMAIN" 2>/dev/null | grep -q "($CUSTOMER)"; then
        log "tests/customer-smoke.sh (as $CUSTOMER)"
        CONTAINER="$CONTAINER" PANEL="http://localhost:$PANEL_PORT" SITE_ID="$id" DOMAIN="$DOMAIN" CUSTOMER="$CUSTOMER" \
            bash "$ROOT/tests/customer-smoke.sh" || rc=1
    else
        echo "SKIP  tests/customer-smoke.sh: $DOMAIN is not owned by the customer $CUSTOMER"
    fi
    if [ -n "$E2E_RUNTIMES" ]; then
        log "tests/runtime-e2e.sh (runtimes: $E2E_RUNTIMES)"
        CONTAINER="$CONTAINER" PANEL="http://localhost:$PANEL_PORT" SITE_ID="$id" DOMAIN="$DOMAIN" \
            RUNWAY_E2E_RUNTIMES="$E2E_RUNTIMES" bash "$ROOT/tests/runtime-e2e.sh" || rc=1
    fi
    return "$rc"
}

cmd_diagnostics() {
    local dir=${1:-e2e-logs}
    mkdir -p "$dir"
    in_c bash -c 'tail -n 1000 /var/log/plesk/panel.log' >"$dir/panel.log" 2>&1 || true
    in_c bash -c 'journalctl --no-pager -n 2000 -u "runway-*"' >"$dir/journal-runway.log" 2>&1 || true
    in_c bash -c 'for f in /var/lib/runway/jobs/*.log; do echo "### $f"; tail -n 300 "$f"; done' \
        >"$dir/jobs.log" 2>&1 || true
    in_c bash -c 'systemctl list-units --all --no-pager "runway-*"; systemctl --failed --no-pager' \
        >"$dir/units.log" 2>&1 || true
    in_c plesk bin extension --list >"$dir/extensions.log" 2>&1 || true
    dock logs "$CONTAINER" >"$dir/container.log" 2>&1 || true
    echo "diagnostics written to $dir"
}

cmd_stop() {
    dock rm -f "$CONTAINER" >/dev/null 2>&1 || true
}

command=${1:-}
[ $# -gt 0 ] && shift
case "$command" in
    start) cmd_start ;;
    install) cmd_install "$@" ;;
    prepare) cmd_prepare ;;
    smoke) cmd_smoke ;;
    diagnostics) cmd_diagnostics "$@" ;;
    stop) cmd_stop ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
esac
