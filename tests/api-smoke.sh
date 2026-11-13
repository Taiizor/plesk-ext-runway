#!/bin/bash
# Smoke test of the JSON API (docs/DESIGN.md section 6) and the CLI (section 9). Runs on the
# development machine against the local Plesk test container: logs in with a one-time login
# link, keeps the session in a cookie jar, reads the CSRF token from a panel page and calls the
# API with curl; CLI checks run "plesk ext runway" through docker exec.
#
#   bash tests/api-smoke.sh                      # read-only checks, validation errors, CLI,
#                                                # plus the scratch subdomain tests below
#   RUNWAY_SMOKE_DEPLOY=1 bash tests/api-smoke.sh  # first enable the Go app of SITE_ID and
#                                                  # check that nginx serves it (needs Go
#                                                  # $GO_VERSION installed through Runway)
#
# The updater checks (api/update, the settings updateCheck/updateAuto, CLI --check-update) ask
# GitHub once; they never install anything (helper-smoke covers the update job).
#
# Zero-downtime deployments (docs/DESIGN.md section 12): validation and caps of the new fields and
# settings; with RUNWAY_SMOKE_DEPLOY=1 the Go app of SITE_ID also turns the setting on, deploys,
# restarts (panel and CLI) and turns it off again from slot a, followed by a Reconcile, while a
# request loop inside the container counts every non-2xx answer of nginx (Restart in place, which
# interrupts by design, runs outside the loop).
#
# The sample, fetch, path mode, worker and maxAppsPerSubscription tests use a scratch subdomain
# SUB.DOMAIN (created when missing, deleted at the end unless KEEP_SUB=1), so the application
# of SITE_ID is never modified unless RUNWAY_SMOKE_DEPLOY=1. The fetch test serves a copy of
# the SITE_ID binary ($APP_ROOT/bin/app) with python3 -m http.server inside the container and
# creates the helper's test-only switch /etc/runway/allow-insecure-fetch while it runs.
# RUNWAY_SMOKE_SUB=0 skips everything that needs the subdomain.
#
# Document roots (Plesk's setting, api/app/save documentRoot): validation errors on DOMAIN, then a
# folder inside the application root as the document root of DOMAIN (with RUNWAY_SMOKE_DEPLOY=1
# together with the static path /media, served by nginx from there) and of the subdomain (path
# mode: its static path /api/static); both are restored through the API, and cleanup restores
# them through Plesk's CLI whenever a run stops before that.
#
# Environment: CONTAINER (runway-plesk), PANEL (http://localhost:18880), SITE_ID (1),
# DOMAIN (gotest.local), APP_ROOT (apps/gotest.local), GO_VERSION (1.27.4), SUB (runway-smoke),
# FETCH_PORT (18765), PYTHON.
set -u
CONTAINER=${CONTAINER:-runway-plesk}
PANEL=${PANEL:-http://localhost:18880}
SITE_ID=${SITE_ID:-1}
DOMAIN=${DOMAIN:-gotest.local}
APP_ROOT=${APP_ROOT:-apps/gotest.local}
GO_VERSION=${GO_VERSION:-1.27.4}
SUB=${SUB:-runway-smoke}
SUB_DOMAIN=$SUB.$DOMAIN
FETCH_PORT=${FETCH_PORT:-18765}
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    # "python3" may be a non-working Microsoft Store alias on Windows: probe it.
    for candidate in python3 python; do
        if "$candidate" -c 'import json' >/dev/null 2>&1; then PY=$candidate; break; fi
    done
fi
API=$PANEL/modules/runway/index.php/api
WORK=$(mktemp -d)
JAR=$WORK/cookies
PASS=0
FAIL=0
SKIP=0
SUB_ID=""
CREATED_SUB=0
MAX_APPS_BEFORE=""
SWITCHES_BEFORE=""
ZD_BEFORE=""
# Set while the navigation check has turned on the administrator's Power User view.
POWER_USER_RESTORE=""
# Set while the health watch and expected content checks have changed the health settings of
# SITE_ID (cleanup restores the health check path HP_BEFORE, without a watch or a content).
HM_RESTORE=""
HP_BEFORE=""
# The document roots (Plesk's setting) before the document root checks changed them: set before the
# first change, cleared only after a verified restore, so that cleanup restores them through
# Plesk's CLI whenever a run stops in between (SP_BEFORE: the static paths of SITE_ID, JSON).
DR_MAIN_BEFORE=""
DR_SUB_BEFORE=""
SP_BEFORE=""

# Git Bash on Windows: no path conversion for docker arguments (but keep it for curl's
# cookie jar path, which is a POSIX path there).
dock() { MSYS_NO_PATHCONV=1 docker "$@"; }
ok()   { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }
skip() { echo "SKIP  $1"; SKIP=$((SKIP + 1)); }
# jexpr EXPR: evaluates a Python expression with d = the decoded JSON on stdin.
jexpr() { "$PY" -c "import json,sys
try:
    d = json.load(sys.stdin)
    print($1)
except Exception as exc:
    print('ERROR', exc)"; }
get()  { curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' "$API/$1"; }
post() { curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' -H "X-Forgery-Protection-Token: $TOKEN" \
              -H 'Content-Type: application/json' -d "$2" "$API/$1"; }
check() { # check NAME EXPR JSON
    if [ "$(echo "$3" | jexpr "$2")" = "True" ]; then ok "$1"; else bad "$1: $(echo "$3" | head -c 400)"; fi
}
# check_or_helper NAME EXPR JSON HELPER_ERROR: passes when EXPR holds, or when the helper
# answered HELPER_ERROR (feature of the helper not deployed yet: reported as SKIP).
check_or_helper() {
    if [ "$(echo "$3" | jexpr "$2")" = "True" ]; then ok "$1"
    elif [ "$(echo "$3" | jexpr "d['status'] == 'error' and '$4' in str(d['errors'])")" = "True" ]; then
        skip "$1: the deployed helper answers \"$4\""
    else bad "$1: $(echo "$3" | head -c 400)"; fi
}
cli() { dock exec "$CONTAINER" plesk ext runway "$@" 2>&1; }
# wait_deploy ID: waits for the deploy job of a domain, prints its final state.
wait_deploy() {
    local state=""
    for _ in $(seq 1 90); do
        state=$(get "app/status?site_id=$1" | jexpr "d['data']['deploy']['state']")
        case "$state" in queued|running) sleep 2 ;; *) break ;; esac
    done
    echo "$state"
}
# Plesk regenerates the vhost configuration through its task manager, so on a slow server the
# files lag a few seconds behind app/save: poll before judging them.
# wait_conf GREP_FLAGS PATTERN FILE: 0 as soon as PATTERN matches (within 30 s).
wait_conf() {
    local _i
    for _i in $(seq 1 15); do
        dock exec "$CONTAINER" grep "$1" "$2" "$3" 2>/dev/null && return 0
        sleep 2
    done
    return 1
}
# wait_conf_gone GREP_FLAGS PATTERN FILE: 0 as soon as PATTERN no longer matches (within 30 s).
wait_conf_gone() {
    local _i
    for _i in $(seq 1 15); do
        dock exec "$CONTAINER" grep "$1" "$2" "$3" 2>/dev/null || return 0
        sleep 2
    done
    return 1
}
# docroot_info DOMAIN: the document root that Plesk stores for a domain (absolute path).
docroot_info() { dock exec "$CONTAINER" plesk bin site --info "$1" 2>/dev/null | sed -n 's/^--WWW-Root--: *//p' | tr -d '\r'; }
# https_get DOMAIN PATH [CURL OPTIONS...]: a request through nginx inside the container (Host = DOMAIN).
https_get() {
    local host=$1 path=$2 ip
    shift 2
    ip=$(dock exec "$CONTAINER" hostname -I | awk '{print $1}')
    dock exec "$CONTAINER" curl -s -k "$@" --resolve "$host:443:$ip" "https://$host$path"
}
# wait_body DOMAIN PATH TEXT: the body of PATH once it is TEXT (polled up to 30 s), else the last one.
# After a document root change nginx follows at once, but Apache, which serves what nginx passes on
# (e.g. .txt files in proxy mode), may answer from the old root for a few seconds until it reloads.
wait_body() {
    local body=""
    for _ in $(seq 1 15); do
        body=$(https_get "$1" "$2")
        [ "$body" = "$3" ] && break
        sleep 2
    done
    echo "$body"
}
# A request loop inside the container through nginx (HTTPS to the container's address, Host =
# the domain), counting every answer that is not 2xx: loop_start DOMAIN, loop_stop NAME.
LOOP_PY=$(cat <<'PYEOF'
import http.client, os, socket, ssl, sys, threading, time
host, out, stop = sys.argv[1], sys.argv[2], sys.argv[3]
addr = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")][0]
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
lock = threading.Lock()
count = {"ok": 0, "bad": 0}
bad = []
def worker():
    while not os.path.exists(stop):
        try:
            conn = http.client.HTTPSConnection(addr, 443, timeout=10, context=ctx)
            conn.request("GET", "/", headers={"Host": host, "Connection": "close"})
            resp = conn.getresponse()
            resp.read()
            code = resp.status
            conn.close()
        except Exception as exc:
            code = "ERR %s" % exc
        with lock:
            if isinstance(code, int) and 200 <= code < 300:
                count["ok"] += 1
            else:
                count["bad"] += 1
                if len(bad) < 5:
                    bad.append("%s %s" % (time.strftime("%H:%M:%S"), code))
threads = [threading.Thread(target=worker) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
with open(out, "w") as fh:
    fh.write("%d %d %s\n" % (count["ok"], count["bad"], "; ".join(bad)))
PYEOF
)
LOOP_PID=""
loop_start() {
    dock exec "$CONTAINER" rm -f /root/runway-smoke-loop.out /root/runway-smoke-loop.stop
    echo "$LOOP_PY" | dock exec -i "$CONTAINER" sh -c 'cat > /root/runway-smoke-loop.py'
    dock exec "$CONTAINER" python3 /root/runway-smoke-loop.py "$1" /root/runway-smoke-loop.out /root/runway-smoke-loop.stop &
    LOOP_PID=$!
    sleep 2
}
loop_stop() {
    local result n_ok n_bad
    dock exec "$CONTAINER" touch /root/runway-smoke-loop.stop
    wait "$LOOP_PID" 2>/dev/null
    LOOP_PID=""
    result=$(dock exec "$CONTAINER" cat /root/runway-smoke-loop.out 2>/dev/null)
    n_ok=$(echo "$result" | awk '{print $1}')
    n_bad=$(echo "$result" | awk '{print $2}')
    [ "${n_bad:-1}" = "0" ] && [ "${n_ok:-0}" -gt 20 ] && ok "$1: $n_ok requests through nginx, none failed" || bad "$1: ${result:-no result}"
}
cleanup() {
    # Never leave a changed document root behind (restored through Plesk's CLI, which also
    # regenerates the web server configuration).
    if [ -n "$DR_MAIN_BEFORE" ]; then
        dock exec "$CONTAINER" plesk bin site --update "$DOMAIN" -www-root "/$DR_MAIN_BEFORE" >/dev/null 2>&1 \
            || echo "cleanup: the document root of $DOMAIN could not be restored to $DR_MAIN_BEFORE"
        if [ -n "$SP_BEFORE" ]; then post app/save "{\"site_id\": $SITE_ID, \"staticPaths\": $SP_BEFORE}" >/dev/null; fi
    fi
    if [ -n "$DR_SUB_BEFORE" ]; then
        dock exec "$CONTAINER" plesk bin site --update "$SUB_DOMAIN" -www-root "/$DR_SUB_BEFORE" >/dev/null 2>&1 \
            || echo "cleanup: the document root of $SUB_DOMAIN could not be restored to $DR_SUB_BEFORE"
    fi
    dock exec "$CONTAINER" sh -c "rm -rf '/var/www/vhosts/$DOMAIN/$APP_ROOT/runway-smoke-docroot' '/var/www/vhosts/$DOMAIN/runway-smoke-out' '/var/www/vhosts/$DOMAIN/runway-smoke-file'" >/dev/null 2>&1
    if [ -n "$MAX_APPS_BEFORE" ]; then post settings "{\"maxAppsPerSubscription\": $MAX_APPS_BEFORE}" >/dev/null; fi
    if [ -n "$SWITCHES_BEFORE" ]; then post settings "$SWITCHES_BEFORE" >/dev/null; fi
    if [ -n "$ZD_BEFORE" ]; then post settings "$ZD_BEFORE" >/dev/null; fi
    if [ -n "$POWER_USER_RESTORE" ]; then dock exec "$CONTAINER" plesk bin poweruser --off >/dev/null 2>&1; fi
    # A run stopped during the health checks must not leave an expected content behind (other
    # tests, e.g. runtime-e2e.sh, would find every application unhealthy).
    if [ -n "$HM_RESTORE" ]; then
        post app/save "{\"site_id\": $SITE_ID, \"healthMatch\": \"\", \"healthWatch\": false, \"healthPath\": \"$HP_BEFORE\"}" >/dev/null
    fi
    dock exec "$CONTAINER" rm -f /root/runway-smoke-loop.py /root/runway-smoke-loop.out /root/runway-smoke-loop.stop >/dev/null 2>&1
    # "[.]" keeps pkill from matching (and killing) this very shell.
    dock exec "$CONTAINER" sh -c "rm -rf /root/runway-smoke-www /etc/runway/allow-insecure-fetch; pkill -f 'http[.]server $FETCH_PORT'" >/dev/null 2>&1
    if [ -n "$SUB_ID" ]; then
        post app/remove "{\"site_id\": $SUB_ID}" >/dev/null
        if [ "$CREATED_SUB" = "1" ] && [ "${KEEP_SUB:-0}" != "1" ]; then
            dock exec "$CONTAINER" plesk bin subdomain --remove "$SUB" -domain "$DOMAIN" >/dev/null 2>&1
            dock exec "$CONTAINER" rm -rf "/var/www/vhosts/$DOMAIN/apps/$SUB_DOMAIN" >/dev/null 2>&1
        fi
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "== login"
LINK=$(dock exec "$CONTAINER" plesk bin admin --get-login-link -relative-url | tr -d '\r')
curl -s -c "$JAR" -b "$JAR" -L "$PANEL$LINK" -o /dev/null
PAGE=$(curl -s -c "$JAR" -b "$JAR" "$PANEL/modules/runway/index.php/overview")
TOKEN=$(echo "$PAGE" | grep -o 'id="forgery_protection_token" content="[^"]*"' | sed 's/.*content="//;s/"$//')
[ -n "$TOKEN" ] && ok "panel login + CSRF token" || { bad "login failed"; exit 1; }
echo "$PAGE" | grep -q '<div id="runway"></div>' && ok "overview page renders the SDK view" || bad "overview page"
echo "$PAGE" | grep -q '"Overview.title"' && ok "app locale section passed to the frontend" || bad "app locale"
for page in toolchains settings "domain?site_id=$SITE_ID"; do
    curl -s -b "$JAR" "$PANEL/modules/runway/index.php/$page" | grep -q '<div id="runway"></div>' && ok "page $page" || bad "page $page"
done

if [ "${RUNWAY_SMOKE_DEPLOY:-0}" = "1" ]; then
    echo "== deploy (Go $GO_VERSION, $DOMAIN)"
    out=$(post app/save "{\"site_id\": $SITE_ID, \"enabled\": true, \"runtime\": \"go\", \"toolchain\": \"$GO_VERSION\", \"appRoot\": \"$APP_ROOT\", \"listen\": \"tcp\", \"buildCmd\": \"go build -o bin/app .\", \"startCmd\": \"./bin/app\", \"staticPaths\": [], \"mode\": \"web\"}")
    check "app/save enables the app" "d['status'] == 'success' and d['data']['config']['enabled'] is True" "$out"
    state=$(wait_deploy "$SITE_ID")
    [ "$state" = "succeeded" ] && ok "deployment succeeded" || bad "deployment: $state"
    check "service is running and listening" "d['data']['service']['active_state'] == 'active' and d['data']['listener'] == 'ok'" "$(get "app/status?site_id=$SITE_ID")"
    IP=$(dock exec "$CONTAINER" hostname -I | awk '{print $1}')
    code=$(dock exec "$CONTAINER" curl -s -k -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/")
    [ "$code" = "200" ] && ok "nginx serves $DOMAIN through the app" || bad "nginx answered HTTP $code"
    acme=$(dock exec "$CONTAINER" curl -s -k -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/.well-known/acme-challenge/runway-smoke")
    [ "$acme" = "404" ] && ok "ACME challenges stay on Plesk" || bad "ACME path answered HTTP $acme"
    out=$(cli --deploy "$DOMAIN"); code=$?
    [ $code -eq 0 ] && echo "$out" | grep -q "Job deploy-$SITE_ID: succeeded" && ok "CLI --deploy waits for the build" || bad "CLI --deploy ($code): $out"

    echo "== zero-downtime deployment through nginx (Go $GO_VERSION, $DOMAIN)"
    loop_start "$DOMAIN"
    out=$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": true, \"readyTimeout\": 30, \"drainSeconds\": 2}")
    check "app/save turns zero-downtime on (switchable, a job)" \
        "d['status'] == 'success' and d['data']['config']['zeroDowntime'] is True and d['data']['config']['switchable'] is True and d['data']['job'] == 'deploy-$SITE_ID'" "$out"
    state=$(wait_deploy "$SITE_ID")
    st=$(get "app/status?site_id=$SITE_ID")
    [ "$state" = "succeeded" ] && check "status: zero-downtime on, slot b live, both slots reported" \
        "d['data']['zero_downtime'] is True and d['data']['switchable'] is True and d['data']['slot'] == 'b' and 'b' in d['data']['slots'] and d['data']['listener'] == 'ok'" "$st" \
        || bad "first switch: $state $(get "app/logs?site_id=$SITE_ID&kind=deploy&lines=15" | jexpr "d['data']['log']" | tail -n 5)"
    out=$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"deploy\"}")
    state=$(wait_deploy "$SITE_ID")
    [ "$state" = "succeeded" ] && ok "Build & restart with zero-downtime (job $state)" || bad "zero-downtime deploy: $state $out"
    out=$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\"}")
    check "app/control restart of a switchable app answers with the switch job" "d['status'] == 'success' and d['data']['job'] == 'deploy-$SITE_ID'" "$out"
    state=$(wait_deploy "$SITE_ID")
    [ "$state" = "succeeded" ] && ok "zero-downtime restart (job $state)" || bad "zero-downtime restart: $state"
    loop_stop "requests during turning it on, Build & restart and Restart"
    # Restart in place interrupts the application by design: outside the request loop.
    check "app/control restart with plain: true restarts in place (no job)" "d['status'] == 'success' and 'job' not in d['data'] and 'in place' in d['data']['message']" \
        "$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\", \"plain\": true}")"
    out=$(cli --status "$DOMAIN")
    echo "$out" | grep -q '^Zero-downtime: *on (slot ' && echo "$out" | grep -q '^Slots:' && ok "CLI --status shows the zero-downtime state and the slots" || bad "CLI --status: $out"
    for _ in $(seq 1 15); do [ "$(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['listener']")" = "ok" ] && break; sleep 2; done
    loop_start "$DOMAIN"
    out=$(cli --restart "$DOMAIN"); code=$?
    [ $code -eq 0 ] && echo "$out" | grep -q "Job deploy-$SITE_ID: succeeded" && ok "CLI --restart waits for the switch" || bad "CLI --restart ($code): $out"
    check "overview: zeroDowntime and the live port" "[(a['zeroDowntime'], a['port'] == $(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['port']")) for a in d['data']['apps'] if a['domainId'] == $SITE_ID] == [(True, True)]" "$(get overview)"
    # The fourth switch made slot a live, whose port is the classic unit's: turning it off gives the
    # classic unit a new port, which the Reconcile that follows stores in the panel (docs/DESIGN.md
    # section 12.8) before Plesk renders the classic snippet again.
    SLOT_OFF=$(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['slot']")
    out=$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": false}")
    state=$(wait_deploy "$SITE_ID")
    check "turning it off switches back to the classic unit (from slot $SLOT_OFF)" "d['data']['zero_downtime'] is False and d['data']['slot'] == '' and d['data']['listener'] == 'ok'" "$(get "app/status?site_id=$SITE_ID")"
    # (The scheduled Reconcile may have come first: then nothing is left to re-apply.)
    out=$(cli --reconcile); code=$?
    [ $code -eq 0 ] && ok "CLI --reconcile ($(echo "$out" | grep '^Re-applied:' | tr -d '\r'))" || bad "CLI --reconcile ($code): $out"
    wait_conf_gone -q "Runway: zero-downtime #$SITE_ID" "/var/www/vhosts/system/$DOMAIN/conf/nginx.conf" \
        && check "after the Reconcile the panel has the helper's port and the classic snippet" \
            "d['data']['config']['switchable'] is False and d['data']['config']['port'] == $(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['port']")" "$(get "app?site_id=$SITE_ID")" \
        || bad "the generated configuration of $DOMAIN still uses the zero-downtime snippet"
    sleep 3
    loop_stop "requests during CLI --restart, turning it off and the Reconcile"
    code=$(dock exec "$CONTAINER" curl -s -k -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/")
    [ "$code" = "200" ] && ok "nginx serves $DOMAIN after turning it off" || bad "nginx answered HTTP $code after turning it off"
fi

# Checks below that need a configured application of SITE_ID are skipped when it has none.
CONFIGURED=$(get "app?site_id=$SITE_ID" | jexpr "d['data']['configured']")

echo "== read-only endpoints"
CONTEXT=$(get context)
check "context" "d['status'] == 'success' and d['data']['isAdmin'] is True and 'go' in [r['key'] for r in d['data']['runtimes']] and d['data']['urls']['api'].endswith('/index.php/api')" "$CONTEXT"
check "context: runtime metadata from the helper" "all(set(['key', 'label', 'toolchain', 'version_re', 'default_listen', 'supports_build']) <= set(r) for r in d['data']['runtimes']) and d['data']['limits']['maxStaticPaths'] == 20" "$CONTEXT"
KEYS=$(echo "$CONTEXT" | jexpr "sorted(r['key'] for r in d['data']['runtimes'])")
check "overview" "d['status'] == 'success' and $SITE_ID in [a['domainId'] for a in d['data']['apps']] and 'os' in d['data']['server'] and all('appUrl' in a and 'mode' in a for a in d['data']['apps'])" "$(get overview)"
# Links use https when the domain's hosting has SSL/TLS support (pm_Domain::hasSsl()).
SCHEME=http
dock exec "$CONTAINER" plesk bin subscription --info "$DOMAIN" | grep -Eq '^SSL/TLS support:[[:space:]]+On' && SCHEME=https
check "overview: site URL uses $SCHEME (SSL/TLS support of $DOMAIN)" "[a['url'] for a in d['data']['apps'] if a['domainId'] == $SITE_ID] == ['$SCHEME://$DOMAIN/']" "$(get overview)"
check "toolchains" "d['status'] == 'success' and d['data']['runtimes']['go']['toolchainKind'] == 'managed' and isinstance(d['data']['runtimes']['go']['available'], list)" "$(get 'toolchains?available=0')"
check "settings" "d['status'] == 'success' and d['data']['portMin'] <= d['data']['portMax'] and 'maxAppsPerSubscription' in d['data']" "$(get settings)"
check "job" "d['status'] == 'success' and 'state' in d['data']" "$(get 'job?job=admin')"
check "update: status of the built-in updater (no network)" \
    "d['status'] == 'success' and set(['installed', 'latest', 'available', 'checkedAt', 'error', 'job', 'updateCheck', 'updateAuto']) <= set(d['data']) and d['data']['installed'].count('-') == 1 and isinstance(d['data']['available'], bool)" \
    "$(get update)"
APP=$(get "app?site_id=$SITE_ID")
check "app" "d['status'] == 'success' and d['data']['domain']['id'] == $SITE_ID and 'config' in d['data'] and d['data']['config']['mode'] in ('web', 'path', 'worker')" "$APP"
check "app: defaults and toolchains for every runtime" "sorted(d['data']['defaults']) == $KEYS and sorted(d['data']['toolchains']) == $KEYS and all('start_cmd' in v for v in d['data']['defaults'].values())" "$APP"
check "app: document roots of the webspace (own one: httpdocs) and the default application root" \
    "d['data']['domain']['documentRoot'] == 'httpdocs' and {'domain': '$DOMAIN', 'path': 'httpdocs', 'own': True} in d['data']['documentRoots'] and d['data']['defaultAppRoot'] == 'apps/$DOMAIN'" "$APP"
check "app/status" "d['status'] == 'success' and 'service' in d['data']" "$(get "app/status?site_id=$SITE_ID")"
check "app/status: memory_used_bytes and memory_cache_bytes next to memory_bytes" \
    "set(['memory_bytes', 'memory_used_bytes', 'memory_cache_bytes']) <= set(d['data']['service']) and (d['data']['service']['memory_bytes'] is None or d['data']['service']['memory_used_bytes'] <= d['data']['service']['memory_bytes'])" \
    "$(get "app/status?site_id=$SITE_ID")"
check "overview: memoryUsedBytes and memoryCacheBytes (the application's memory and the file cache)" \
    "all('memoryUsedBytes' in a and 'memoryCacheBytes' in a for a in d['data']['apps']) and all(a['memoryUsedBytes'] is not None for a in d['data']['apps'] if a['state'] == 'running')" "$(get overview)"
check "app/logs" "d['status'] == 'success' and d['data']['kind'] == 'deploy'" "$(get "app/logs?site_id=$SITE_ID&kind=deploy&lines=20")"
check "unknown domain is rejected" "d['status'] == 'error'" "$(get 'app?site_id=999999')"

echo "== mutations and validation"
check "POST without CSRF token is rejected" "d.get('status') != 'success'" \
    "$(curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' -d '{"portMin": 20000}' "$API/settings")"
check "GET on a mutation is rejected" "d['status'] == 'error'" "$(get toolchain)"
check "GET on app/sample is rejected" "d['status'] == 'error'" "$(get "app/sample?site_id=$SITE_ID")"
check "settings: errors keyed by field" "d['status'] == 'error' and 'portMax' in d['errors']" "$(post settings '{"portMin": 30000, "portMax": 29000}')"
check "toolchain: unknown runtime" "d['status'] == 'error' and 'runtime' in d['errors']" "$(post toolchain '{"runtime": "cobol", "op": "install", "version": "1"}')"

echo "== built-in updater"
check "GET on update/check is rejected" "d['status'] == 'error'" "$(get update/check)"
check "update/install: invalid version" "d['status'] == 'error' and list(d['errors']) == ['version']" "$(post update/install '{"version": "latest"}')"
check "update/install: an older version is refused" "d['status'] == 'error' and 'not newer' in str(d['errors'])" "$(post update/install '{"version": "0.0.1-1"}')"
out=$(post update/check '{}')
if echo "$out" | grep -q 'rate limit'; then
    skip "update/check: GitHub API rate limit reached"
else
    # Without a published release GitHub answers 404: no release, no error.
    check "update/check asks GitHub (no release yet: latest null, no error)" \
        "d['status'] == 'success' and d['data']['error'] is None and d['data']['checkedAt'] and (d['data']['latest'] is None or d['data']['latest']['full'].count('-') == 1)" "$out"
fi
SWITCHES_BEFORE=$(get settings | jexpr "json.dumps({'updateCheck': d['data']['updateCheck'], 'updateAuto': d['data']['updateAuto']})")
check "settings: update switches round-trip" "d['status'] == 'success' and d['data']['updateCheck'] is False and d['data']['updateAuto'] is True" \
    "$(post settings '{"updateCheck": false, "updateAuto": true}')"
check "settings: update switches are stored" "d['data']['updateCheck'] is False and d['data']['updateAuto'] is True" "$(get settings)"
check "update: reports the switches" "d['data']['updateCheck'] is False and d['data']['updateAuto'] is True" "$(get update)"
check "settings: a switch must be a boolean" "d['status'] == 'error' and list(d['errors']) == ['updateCheck']" "$(post settings '{"updateCheck": "maybe"}')"
check "settings: update switches restored" "d['status'] == 'success' and json.dumps({'updateCheck': d['data']['updateCheck'], 'updateAuto': d['data']['updateAuto']}) == '$SWITCHES_BEFORE'" \
    "$(post settings "$SWITCHES_BEFORE")"
check "app/save: errors keyed by field" \
    "d['status'] == 'error' and set(['appRoot', 'env', 'staticPaths']) <= set(d['errors'])" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"appRoot\": \"../etc\", \"env\": \"PORT=1\", \"staticPaths\": [\"bad path\"]}")"
# All of these fail validation in PHP: the application of SITE_ID is not touched.
check "app/save: path mode needs a mount path" "d['status'] == 'error' and list(d['errors']) == ['mountPath']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"mode\": \"path\", \"mountPath\": \"\"}")"
check "app/save: Plesk paths cannot be mounted" "d['status'] == 'error' and list(d['errors']) == ['mountPath']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"mode\": \"path\", \"mountPath\": \"/.well-known\"}")"
check "app/save: mount path without dot segments" "d['status'] == 'error' and list(d['errors']) == ['mountPath']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"mode\": \"path\", \"mountPath\": \"/a/../b\"}")"
check "app/save: invalid static paths" "d['status'] == 'error' and list(d['errors']) == ['staticPaths'] and len(d['errors']['staticPaths']) == 2" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"staticPaths\": [\"/ok\", \"/a b\", \"/x/..\"]}")"
MANY=$(for i in $(seq 1 21); do printf '"/s%d",' "$i"; done)
check "app/save: at most 20 static paths" "d['status'] == 'error' and list(d['errors']) == ['staticPaths']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"staticPaths\": [${MANY%,}]}")"
check "app/save: conflicting mode and listen" "d['status'] == 'error' and list(d['errors']) == ['listen']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"mode\": \"path\", \"mountPath\": \"/api\", \"listen\": \"none\"}")"
check "app/save: invalid mode" "d['status'] == 'error' and list(d['errors']) == ['mode']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"mode\": \"lambda\"}")"
check "app/save: invalid health path" "d['status'] == 'error' and list(d['errors']) == ['healthPath']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/h x\"}")"
check "app/control: invalid op" "d['status'] == 'error'" "$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"explode\"}")"
check "app/save: zeroDowntime must be a boolean" "d['status'] == 'error' and list(d['errors']) == ['zeroDowntime']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": \"maybe\"}")"
check "app/save: readyTimeout below 5 s is refused" "d['status'] == 'error' and list(d['errors']) == ['readyTimeout']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"readyTimeout\": 4}")"
check "app/save: drainSeconds above the server cap is refused" "d['status'] == 'error' and list(d['errors']) == ['drainSeconds'] and '30' in d['errors']['drainSeconds'][0]" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"drainSeconds\": 31}")"
# Health watch (docs/DESIGN.md section 7): needs a health check path; interval 10-3600 s, 1-20 failures.
check "app/save: the health watch needs a health check path" "d['status'] == 'error' and list(d['errors']) == ['healthWatch']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthWatch\": true, \"healthPath\": \"\"}")"
check "app/save: a health watch interval below 10 s is refused" "d['status'] == 'error' and list(d['errors']) == ['healthWatchInterval']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthWatchInterval\": 9}")"
check "app/save: more than 20 failed checks are refused" "d['status'] == 'error' and list(d['errors']) == ['healthWatchFailures']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthWatchFailures\": 21}")"
HP_BEFORE=$(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['healthPath']")
HM_RESTORE=1
check "app/save: health watch on (configuration)" \
    "d['status'] == 'success' and (d['data']['config']['healthWatch'], d['data']['config']['healthWatchInterval'], d['data']['config']['healthWatchFailures']) == (True, 15, 2)" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthWatch\": true, \"healthWatchInterval\": 15, \"healthWatchFailures\": 2}")"
# The helper state and the timer live in the container (this script runs on the development machine).
HW_STATE=$(dock exec "$CONTAINER" python3 -c "import json; s = json.load(open('/var/lib/runway/apps/$SITE_ID.json')); print((s['health_watch'], s['health_interval'], s['health_failures']))" 2>&1)
HW_TIMER=$(dock exec "$CONTAINER" systemctl is-active runway-health.timer 2>&1)
[ "$HW_STATE" = "(True, 15, 2)" ] && [ "$HW_TIMER" = "active" ] \
    && ok "health watch on: helper state and runway-health.timer" || bad "health watch on: state $HW_STATE, timer $HW_TIMER"
check "app/status: health_watch with interval and failures" \
    "isinstance(d['data']['health_watch'], dict) and (d['data']['health_watch']['interval'], d['data']['health_watch']['failures_limit']) == (15, 2)" \
    "$(get "app/status?site_id=$SITE_ID")"
# Every successful save of the built application starts a deployment; the next save must wait for it
# ("A deployment is running for this application" otherwise, on a slow runner).
wait_deploy "$SITE_ID" >/dev/null
check "app/save: health watch off" "d['status'] == 'success' and d['data']['config']['healthWatch'] is False" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthWatch\": false, \"healthPath\": \"$HP_BEFORE\"}")"
wait_deploy "$SITE_ID" >/dev/null
# Expected response content of the health check (docs/DESIGN.md section 7, health_match): needs a
# health check path; text that starts with "{" must be a JSON object; at most 200 characters
# without control characters. These five fail validation in PHP.
check "app/save: the expected response content needs a health check path" "d['status'] == 'error' and list(d['errors']) == ['healthMatch']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthMatch\": \"Healthy\", \"healthPath\": \"\"}")"
check "app/save: an expected content that starts with { must be a JSON object" "d['status'] == 'error' and list(d['errors']) == ['healthMatch'] and 'JSON' in d['errors']['healthMatch'][0]" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthMatch\": \"{status: ok}\"}")"
check "app/save: an expected content longer than 200 characters is refused" "d['status'] == 'error' and list(d['errors']) == ['healthMatch'] and '200' in d['errors']['healthMatch'][0]" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthMatch\": \"$("$PY" -c "print('x' * 201)")\"}")"
check "app/save: a control character in the expected content is refused" "d['status'] == 'error' and list(d['errors']) == ['healthMatch']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthMatch\": \"a\\u0001b\"}")"
check "app/save: the expected content must be text" "d['status'] == 'error' and list(d['errors']) == ['healthMatch']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthMatch\": {\"status\": \"ok\"}}")"
# hm_state EXPR: EXPR on s = the helper state of SITE_ID (inside the container).
hm_state() { dock exec "$CONTAINER" python3 -c "import json; s = json.load(open('/var/lib/runway/apps/$SITE_ID.json')); print($1)" 2>&1; }
# hm_status CODE: health_code of app/status once it is CODE (polled up to 30 s; the save restarts the app).
hm_status() {
    local code=""
    for _ in $(seq 1 15); do
        code=$(get "app/status?site_id=$SITE_ID" | jexpr "d['data'].get('health_code')")
        [ "$code" = "$1" ] && break
        sleep 2
    done
    echo "$code"
}
out=$(post app/save "{\"site_id\": $SITE_ID, \"healthPath\": \"/\", \"healthMatch\": \"  {\\\"status\\\": \\\"ok\\\"}  \"}")
check "app/save: expected response content stored trimmed (configuration)" "d['status'] == 'success' and d['data']['config']['healthMatch'] == '{\"status\": \"ok\"}'" "$out"
check "app: the configuration returns healthMatch" "d['data']['config']['healthMatch'] == '{\"status\": \"ok\"}'" "$(get "app?site_id=$SITE_ID")"
[ "$(hm_state "s['health_match'] == '{\"status\": \"ok\"}' and s['health_path'] == '/'")" = "True" ] \
    && ok "expected response content in the helper state" || bad "helper state: $(hm_state "(s.get('health_path'), s.get('health_match'))")"
wait_deploy "$SITE_ID" >/dev/null
if [ "$CONFIGURED" = "True" ] && [ "$(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['service']['active_state']")" = "active" ]; then
    # The Go sample answers "/" with text: a JSON object is expected, so the check fails.
    code=$(hm_status body_not_json)
    [ "$code" = "body_not_json" ] && ok "app/status: a text answer where a JSON object is expected (body_not_json)" || bad "app/status with a JSON expectation: $code"
    out=$(cli --status "$DOMAIN")
    echo "$out" | grep -F 'Health:' | grep -qF '(/, expecting {"status": "ok"})' && ok "CLI --status shows the expected content on the Health line" \
        || bad "CLI --status Health line: $(echo "$out" | grep -F 'Health:')"
    post app/save "{\"site_id\": $SITE_ID, \"healthMatch\": \"Hello from Go\"}" >/dev/null
    wait_deploy "$SITE_ID" >/dev/null
    code=$(hm_status http_match)
    [ "$code" = "http_match" ] && check "app/status: the text is found (http_match, healthy)" \
        "d['data']['health'] == 'healthy' and d['data']['health_detail'] == 'HTTP 200 from /, expected content found' and d['data']['health_match'] == 'Hello from Go'" \
        "$(get "app/status?site_id=$SITE_ID")" || bad "app/status with a text expectation: $code"
else
    skip "app/status with an expected content: the application of $DOMAIN is not running"
fi
# 200 times U+015F (2 bytes in UTF-8), sent as JSON escapes so the request stays ASCII.
MB200=""
for _ in $(seq 200); do MB200="$MB200\\u015f"; done
check "app/save: 200 characters (2 bytes each in UTF-8) are accepted" "d['status'] == 'success' and len(d['data']['config']['healthMatch']) == 200" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"healthMatch\": \"$MB200\"}")"
[ "$(hm_state "len(s['health_match'])")" = "200" ] && ok "the helper counts the same 200 characters" || bad "helper state of 200 characters: $(hm_state "len(s['health_match'])")"
wait_deploy "$SITE_ID" >/dev/null
out=$(post app/save "{\"site_id\": $SITE_ID, \"healthMatch\": \"\", \"healthPath\": \"$HP_BEFORE\"}")
check "app/save: expected response content cleared" "d['status'] == 'success' and d['data']['config']['healthMatch'] == ''" "$out"
# Restored: nothing left for cleanup (which tries again when this save failed).
if [ "$(echo "$out" | jexpr "d['status']")" = "success" ]; then HM_RESTORE=""; fi
[ "$(hm_state "s['health_match']")" = "" ] && ok "helper state without the expected content" || bad "helper state after clearing: $(hm_state "s['health_match']")"
wait_deploy "$SITE_ID" >/dev/null
check "app: zero-downtime may be turned on by an administrator; caps of the timeouts" \
    "d['status'] == 'success' and d['data']['zeroDowntimeAllowed'] is True and d['data']['zeroDowntimeCaps'] == {'ready': 120, 'drain': 30} and 'zeroDowntime' in d['data']['config']" \
    "$(get "app?site_id=$SITE_ID")"
ZD_BEFORE=$(get settings | jexpr "json.dumps({'zeroDowntimeCustomers': d['data']['zeroDowntimeCustomers'], 'zeroDowntimeMaxReady': d['data']['zeroDowntimeMaxReady'], 'zeroDowntimeMaxDrain': d['data']['zeroDowntimeMaxDrain']})")
check "settings: zero-downtime defaults (customers off, caps 120 and 30)" "d['data']['zeroDowntimeCustomers'] is False and d['data']['zeroDowntimeMaxReady'] == 120 and d['data']['zeroDowntimeMaxDrain'] == 30" "$(get settings)"
check "settings: zero-downtime settings round-trip" "d['status'] == 'success' and d['data']['zeroDowntimeCustomers'] is True and d['data']['zeroDowntimeMaxReady'] == 300 and d['data']['zeroDowntimeMaxDrain'] == 60" \
    "$(post settings '{"zeroDowntimeCustomers": true, "zeroDowntimeMaxReady": 300, "zeroDowntimeMaxDrain": 60}')"
check "settings: zeroDowntimeMaxReady above 900 is refused" "d['status'] == 'error' and list(d['errors']) == ['zeroDowntimeMaxReady']" "$(post settings '{"zeroDowntimeMaxReady": 901}')"
check "settings: zero-downtime settings restored" "d['status'] == 'success'" "$(post settings "$ZD_BEFORE")"
check "app/save: LD_PRELOAD is refused with a hint to the start command" "d['status'] == 'error' and list(d['errors']) == ['env'] and 'start command' in d['errors']['env'][0]" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"env\": \"LD_PRELOAD=/var/www/vhosts/x/evil.so\"}")"
check "app/save: LD_AUDIT, GCONV_PATH and GLIBC_TUNABLES are refused" "d['status'] == 'error' and len(d['errors']['env']) == 3" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"env\": \"LD_AUDIT=/x\\nGCONV_PATH=/x\\nGLIBC_TUNABLES=glibc.malloc.check=3\"}")"
check "app/save: env must be text (an object never wipes the variables)" "d['status'] == 'error' and list(d['errors']) == ['env']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"env\": {}}")"
LONG_BUILD=$("$PY" -c "print('echo ' + (chr(92) + chr(34)) * 1400)")
LONG_START=$("$PY" -c "print('./app ' + (chr(92) + chr(34)) * 900)")
check "app/save: a configuration too long for Plesk's domain setting is refused" "d['status'] == 'error' and 'too long together' in str(d['errors'])" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"buildCmd\": \"$LONG_BUILD\", \"startCmd\": \"$LONG_START\"}")"
MANYLONG=$(for i in $(seq 1 20); do printf '"/static-path-number-%02d-with-a-rather-long-name-for-the-total-limit",' "$i"; done)
check "app/save: static paths are limited in total length" "d['status'] == 'error' and list(d['errors']) == ['staticPaths']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"staticPaths\": [${MANYLONG%,}]}")"
check "app/sample: unknown runtime" "d['status'] == 'error' and list(d['errors']) == ['runtime']" \
    "$(post app/sample "{\"site_id\": $SITE_ID, \"runtime\": \"cobol\"}")"
check "app/sample: invalid listen mode" "d['status'] == 'error' and list(d['errors']) == ['listen']" \
    "$(post app/sample "{\"site_id\": $SITE_ID, \"runtime\": \"go\", \"listen\": \"udp\"}")"
if [ "$CONFIGURED" = "True" ]; then
    check "app/fetch: only https URLs" "d['status'] == 'error' and list(d['errors']) == ['url']" \
        "$(post app/fetch "{\"site_id\": $SITE_ID, \"url\": \"file:///etc/passwd\"}")"
    dock exec "$CONTAINER" rm -f /etc/runway/allow-insecure-fetch
    check "app/fetch: http:// is refused (https only)" "d['status'] == 'error' and list(d['errors']) == ['url'] and 'https://' in d['errors']['url'][0]" \
        "$(post app/fetch "{\"site_id\": $SITE_ID, \"url\": \"http://example.com/app\"}")"
    check "app/fetch: invalid checksum" "d['status'] == 'error' and list(d['errors']) == ['sha256']" \
        "$(post app/fetch "{\"site_id\": $SITE_ID, \"url\": \"https://example.com/app\", \"sha256\": \"abc\"}")"
else
    skip "app/fetch validation: $DOMAIN has no application (run with RUNWAY_SMOKE_DEPLOY=1)"
fi

echo "== document root of $DOMAIN (Plesk's setting: api/app domain.documentRoot, api/app/save documentRoot)"
APP=$(get "app?site_id=$SITE_ID")
HOME_DIR=$(echo "$APP" | jexpr "d['data']['domain']['home']")
SYSUSER=$(echo "$APP" | jexpr "d['data']['domain']['sysuser']")
DR_CURRENT=$(echo "$APP" | jexpr "d['data']['domain']['documentRoot']")
# Restored by cleanup from here on: also the refused attempts below must not leave a changed
# document root behind, should a regression let one through (writing the same value is harmless).
DR_MAIN_BEFORE=$DR_CURRENT
check "app: an administrator may change the document root; suggestions for every runtime" \
    "d['data']['documentRootAllowed'] is True and sorted(d['data']['documentRootSuggestions']) == $KEYS and all(isinstance(v, list) for v in d['data']['documentRootSuggestions'].values())" "$APP"
[ "$(docroot_info "$DOMAIN")" = "$HOME_DIR/$DR_CURRENT" ] && ok "api/app reports Plesk's document root of $DOMAIN ($DR_CURRENT)" \
    || bad "document root: Plesk $(docroot_info "$DOMAIN"), api/app $DR_CURRENT"
dock exec "$CONTAINER" runuser -u "$SYSUSER" -- sh -c "ln -sfn /etc '$HOME_DIR/runway-smoke-out' && touch '$HOME_DIR/runway-smoke-file'"
# dr_refused NAME JSON-VALUE [TEXT]: app/save with only documentRoot is a field error (TEXT in the message).
dr_refused() {
    check "app/save: documentRoot $1 is refused (field error)" \
        "d['status'] == 'error' and list(d['errors']) == ['documentRoot'] and '${3:-}' in d['errors']['documentRoot'][0]" \
        "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": $2}")"
}
dr_refused "with a .. segment" '"apps/../httpdocs"'
dr_refused "with a segment that starts with -" '"apps/-x"' '"-"'
dr_refused "behind a symbolic link that leads outside the home directory" '"runway-smoke-out"' 'outside'
dr_refused "below a symbolic link that leads outside the home directory" '"runway-smoke-out/new"' 'outside'
dr_refused "that is a file" '"runway-smoke-file"' 'not a folder'
dr_refused "with a control character" '"http\u0001docs"'
dr_refused "with a line feed inside" '"apps/runway\nsmoke"'
dr_refused "with a backslash" '"apps\\x"'
dr_refused "of 256 characters" "\"$("$PY" -c "print('a' * 256)")\"" '255'
dr_refused "that is not text" '5'
check "app/save: an invalid document root and an invalid application root are reported together" \
    "d['status'] == 'error' and set(d['errors']) == set(['appRoot', 'documentRoot'])" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"appRoot\": \"../etc\", \"documentRoot\": \"-x\"}")"
[ "$(docroot_info "$DOMAIN")" = "$HOME_DIR/$DR_CURRENT" ] && ok "refused document roots change nothing" || bad "document root after refused values: $(docroot_info "$DOMAIN")"
check "app/save: the unchanged document root (with slashes) is accepted and leaves the application alone" \
    "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_CURRENT' and d['data']['documentRootChanged'] is False and d['data']['job'] is None and d['data']['build'] is False" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"/$DR_CURRENT/\"}")"
check "app/save: surrounding blanks and line breaks are trimmed (the unchanged value with a line feed)" \
    "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_CURRENT' and d['data']['documentRootChanged'] is False" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \" $DR_CURRENT\\n\"}")"
check "app/save: a full path inside the home directory counts relative to it (unchanged)" \
    "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_CURRENT' and d['data']['documentRootChanged'] is False" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$HOME_DIR/$DR_CURRENT\"}")"
# A path that passes Runway's checks but that Plesk refuses (a folder below a file): a field error,
# and the configuration sent along is not saved.
if [ "$CONFIGURED" = "True" ]; then
    HP_DR=$(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['healthPath']")
    out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"runway-smoke-file/sub\", \"healthPath\": \"/runway-smoke-dr\"}")
    check "app/save: a document root that Plesk refuses is a field error with Plesk's message" \
        "d['status'] == 'error' and list(d['errors']) == ['documentRoot'] and 'Plesk' in d['errors']['documentRoot'][0]" "$out"
    [ "$(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['healthPath']")" = "$HP_DR" ] && [ "$(docroot_info "$DOMAIN")" = "$HOME_DIR/$DR_CURRENT" ] \
        && ok "Plesk refusing the document root saves nothing else" || bad "after Plesk refused: healthPath $(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['healthPath']"), document root $(docroot_info "$DOMAIN")"
else
    skip "Plesk refusing a document root together with a setting: $DOMAIN has no application (run with RUNWAY_SMOKE_DEPLOY=1)"
fi
dock exec "$CONTAINER" rm -f "$HOME_DIR/runway-smoke-out" "$HOME_DIR/runway-smoke-file"
# A folder inside the application root that does not exist yet: Plesk creates it.
DR_TARGET=$APP_ROOT/runway-smoke-docroot
dock exec "$CONTAINER" rm -rf "$HOME_DIR/$DR_TARGET"
RUNNING=False
if [ "$CONFIGURED" = "True" ]; then
    for _ in $(seq 1 15); do
        RUNNING=$(get "app/status?site_id=$SITE_ID" | jexpr "d['data'].get('listener') == 'ok' and d['data']['service']['active_state'] == 'active'")
        [ "$RUNNING" = "True" ] && break
        sleep 2
    done
fi
if [ "$RUNNING" = "True" ]; then
    # Document root and static path in one save: the document root changes first, then the
    # configuration is applied (the application restarts).
    SP_BEFORE=$(get "app?site_id=$SITE_ID" | jexpr "json.dumps(d['data']['config']['staticPaths'])")
    out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_TARGET\", \"staticPaths\": [\"/media\"]}")
    check "app/save: document root $DR_TARGET and the static path /media in one save" \
        "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_TARGET' and d['data']['documentRootChanged'] is True and d['data']['config']['staticPaths'] == ['/media'] and '$DR_TARGET' in d['data']['message']" "$out"
    wait_deploy "$SITE_ID" >/dev/null
else
    out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_TARGET\"}")
    check "app/save: only the document root (the application is left alone)" \
        "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_TARGET' and d['data']['documentRootChanged'] is True and d['data']['job'] is None and d['data']['build'] is False" "$out"
fi
[ "$(docroot_info "$DOMAIN")" = "$HOME_DIR/$DR_TARGET" ] && ok "Plesk stores the new document root of $DOMAIN" || bad "Plesk's document root of $DOMAIN: $(docroot_info "$DOMAIN")"
[ "$(dock exec "$CONTAINER" stat -c '%U:%G %a' "$HOME_DIR/$DR_TARGET" 2>&1)" = "$SYSUSER:psaserv 750" ] && ok "Plesk created the missing folder ($SYSUSER:psaserv 0750)" \
    || bad "the new document root folder: $(dock exec "$CONTAINER" stat -c '%U:%G %a' "$HOME_DIR/$DR_TARGET" 2>&1)"
check "app: domain.documentRoot follows Plesk" "d['data']['domain']['documentRoot'] == '$DR_TARGET' and [r['path'] for r in d['data']['documentRoots'] if r['own']] == ['$DR_TARGET']" "$(get "app?site_id=$SITE_ID")"
if [ "$CONFIGURED" = "True" ]; then
    cli --status "$DOMAIN" | grep -q "^Document root: *$DR_TARGET\$" && ok "CLI --status shows the document root" || bad "CLI --status Document root: $(cli --status "$DOMAIN" | grep -i 'document root')"
else
    skip "CLI --status document root: $DOMAIN has no application (run with RUNWAY_SMOKE_DEPLOY=1)"
fi
if [ "$RUNNING" = "True" ]; then
    NGINX_CONF=/var/www/vhosts/system/$DOMAIN/conf/nginx.conf
    wait_conf -qF "root \"$HOME_DIR/$DR_TARGET\";" "$NGINX_CONF" >/dev/null
    dock exec "$CONTAINER" grep -qF "root \"$HOME_DIR/$DR_TARGET\";" "$NGINX_CONF" && dock exec "$CONTAINER" grep -q '# Runway: reverse proxy of the site' "$NGINX_CONF" \
        && ok "nginx: the new root and the Runway snippet after Plesk regenerated the configuration" || bad "nginx configuration: $(dock exec "$CONTAINER" grep -n 'root "\|Runway' "$NGINX_CONF")"
    # The exclusion of /media comes with the regeneration after app-apply (task manager, delayed):
    # wait for it, then give the answer a few seconds as well.
    wait_conf -qF '|(media)(/|$))' "$NGINX_CONF" >/dev/null
    dock exec "$CONTAINER" runuser -u "$SYSUSER" -- sh -c "umask 022; mkdir -p '$HOME_DIR/$DR_TARGET/media' && echo runway-smoke-static > '$HOME_DIR/$DR_TARGET/media/smoke.txt'"
    body=$(wait_body "$DOMAIN" /media/smoke.txt runway-smoke-static)
    [ "$body" = "runway-smoke-static" ] && ok "nginx serves the static path /media from $DR_TARGET/media" || bad "/media/smoke.txt answered: $(echo "$body" | head -c 200)"
    https_get "$DOMAIN" /runway-smoke-page | grep -q 'Hello from Go' && ok "every other path still reaches the application" || bad "/runway-smoke-page: $(https_get "$DOMAIN" /runway-smoke-page | head -c 200)"
else
    skip "static path from the new document root: the application of $DOMAIN is not running (run with RUNWAY_SMOKE_DEPLOY=1)"
fi
if [ -n "$SP_BEFORE" ]; then
    out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_MAIN_BEFORE\", \"staticPaths\": $SP_BEFORE}")
    wait_deploy "$SITE_ID" >/dev/null
else
    out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_MAIN_BEFORE\"}")
fi
if [ "$(echo "$out" | jexpr "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_MAIN_BEFORE'")" = "True" ] \
        && [ "$(docroot_info "$DOMAIN")" = "$HOME_DIR/$DR_MAIN_BEFORE" ]; then
    ok "document root of $DOMAIN restored ($DR_MAIN_BEFORE)"
    DR_MAIN_BEFORE=""
    SP_BEFORE=""
else
    bad "restoring the document root of $DOMAIN: $out"
fi
dock exec "$CONTAINER" rm -rf "$HOME_DIR/$DR_TARGET"

echo "== CLI (plesk ext runway)"
out=$(cli --help)
echo "$out" | grep -q -- '--install-toolchain' && ! echo "$out" | grep -q '\[\[cli' && ok "CLI --help lists the commands with descriptions" || bad "CLI --help: $out"
out=$(cli --list); code=$?
if [ "$CONFIGURED" = "True" ]; then
    [ $code -eq 0 ] && echo "$out" | grep -q "^DOMAIN " && echo "$out" | grep -q "^$DOMAIN " && ok "CLI --list" || bad "CLI --list ($code): $out"
else
    [ $code -eq 0 ] && ok "CLI --list (no application configured)" || bad "CLI --list ($code): $out"
fi
out=$(cli --status "$DOMAIN"); code=$?
if [ "$CONFIGURED" = "True" ]; then
    [ $code -eq 0 ] && echo "$out" | grep -q "^Domain: *$DOMAIN (#$SITE_ID)" && echo "$out" | grep -q '^State:' && ok "CLI --status" || bad "CLI --status ($code): $out"
else
    [ $code -eq 0 ] && echo "$out" | grep -q "^Domain: *$DOMAIN (#$SITE_ID)" && ok "CLI --status (not configured)" || bad "CLI --status ($code): $out"
fi
out=$(cli --status "$SITE_ID"); code=$?
[ $code -eq 0 ] && echo "$out" | grep -q "^Domain: *$DOMAIN" && ok "CLI --status by domain id" || bad "CLI --status id ($code): $out"
out=$(cli --status no-such-domain.invalid); code=$?
[ $code -eq 2 ] && echo "$out" | grep -q 'was not found' && ok "CLI: unknown domain exits with 2" || bad "CLI unknown domain ($code): $out"
out=$(cli --status); code=$?
[ $code -eq 2 ] && echo "$out" | grep -q 'Usage: plesk ext runway --status <domain>' && ok "CLI: missing argument exits with 2" || bad "CLI missing argument ($code): $out"
out=$(cli --install-toolchain cobol 1.0); code=$?
[ $code -eq 2 ] && echo "$out" | grep -q 'Unknown runtime' && ok "CLI: unknown runtime exits with 2" || bad "CLI unknown runtime ($code): $out"
out=$(cli --toolchains); code=$?
[ $code -eq 0 ] && echo "$out" | grep -q '^Go (go, managed)' && ok "CLI --toolchains" || bad "CLI --toolchains ($code): $out"
out=$(cli --check-update); code=$?
if echo "$out" | grep -q 'rate limit'; then
    skip "CLI --check-update: GitHub API rate limit reached"
else
    [ $code -eq 0 ] && echo "$out" | grep -q '^Installed:' && echo "$out" | grep -q '^Available:' && ok "CLI --check-update" || bad "CLI --check-update ($code): $out"
fi
out=$(cli --update now); code=$?
[ $code -eq 2 ] && echo "$out" | grep -q 'Usage: plesk ext runway --update \[-no-wait\]' && ok "CLI --update takes no argument (exit 2)" || bad "CLI --update argument ($code): $out"

echo "== navigation and the icon of a domain row (hooks/CustomButtons.php)"
# The panel pages carry the navigation and the rows of the domain list as JSON: the navigation
# entry is "extNavButton_runway_<n>", a row button "extensionButton_<place>_<n>_runway".
row_icon() { # row_icon PAGE SITE_ID: 0 when the page has Runway's row icon (header.svg) for the domain
    curl -s -b "$JAR" "$PANEL$1" | grep -o '"extensionButton_[0-9]*_[0-9]*_runway"[^}]*' | grep 'header\.svg' | grep -q "site_id=$2\""
}
POWER_USER=$(dock exec "$CONTAINER" plesk db -Ne "select val from misc where param = 'power_user_panel'" | tr -d '\r')
if [ "$POWER_USER" = "true" ]; then
    skip "Service Provider view: the server uses the Power User view"
else
    curl -s -b "$JAR" "$PANEL/admin/domain/list" | grep -q 'extNavButton_runway_[0-9]' && ok "Service Provider view: Runway in the navigation" \
        || bad "Service Provider view: no Runway entry in the navigation of /admin/domain/list"
    # A subscription's page carries the tabs of the hosting panel ("navigationTabs"), where Plesk
    # also renders PLACE_HOSTING_PANEL_TABS: the customer navigation must not become a tab there.
    SUBSCRIPTION_ID=$(dock exec "$CONTAINER" plesk db -Ne "select id from Subscriptions where object_type = 'domain' and object_id = $SITE_ID" | tr -d '\r')
    SUB_PAGE=$(curl -s -L -b "$JAR" "$PANEL/admin/subscription/overview/id/$SUBSCRIPTION_ID")
    if ! echo "$SUB_PAGE" | grep -q '"navigationTabs":\[{'; then
        bad "subscription page of $DOMAIN: no tabs found"
    else
        echo "$SUB_PAGE" | grep -q '"title":"Runway","href":"[^"]*runway' && bad "subscription page of $DOMAIN: a Runway tab (the customer navigation)" \
            || ok "subscription page: no Runway tab for the administrator"
        echo "$SUB_PAGE" | grep -q 'extNavButton_runway_[0-9]' && ok "subscription page: Runway stays in the Service Provider navigation" \
            || bad "subscription page: no Runway entry in the navigation"
    fi
    if [ "$(get "app?site_id=$SITE_ID" | jexpr "d['data']['configured'] and d['data']['config']['enabled']")" = "True" ]; then
        row_icon /admin/domain/list "$SITE_ID" && ok "domain list: Runway's icon in the row of $DOMAIN (enabled application)" || bad "domain list: no Runway icon for $DOMAIN"
    else
        skip "domain list icon: the application of $DOMAIN is not enabled (run with RUNWAY_SMOKE_DEPLOY=1)"
    fi
    # The Power User view has its own navigation (PLACE_HOSTING_PANEL_NAVIGATION); turned on for
    # this check only (cleanup turns it off again when the test stops early).
    POWER_USER_RESTORE=1
    dock exec "$CONTAINER" plesk bin poweruser --on >/dev/null 2>&1
fi
# -L: an administrator without own subscriptions is redirected to /smb/web/setup. The navigation
# of the Power User view links "My Profile" to /smb/my-profile (JSON: "\/smb\/my-profile").
NAV_PAGE=$(curl -s -L -b "$JAR" "$PANEL/smb/web/view")
echo "$NAV_PAGE" | grep -Eq 'smb\\?/my-profile' && [ "$(echo "$NAV_PAGE" | grep -o 'extNavButton_runway_[0-9]*' | sort -u | wc -l)" -eq 1 ] \
    && ok "Power User view: Runway in the navigation, once" \
    || bad "Power User view: Runway entries in the navigation of /smb/web/view: $(echo "$NAV_PAGE" | grep -o 'extNavButton_runway_[0-9]*' | sort -u | tr '\n' ' ')"
echo "$NAV_PAGE" | grep -q '"title":"Runway","href":"[^"]*runway' && bad "Power User view: a Runway tab (the customer navigation)" \
    || ok "Power User view: no Runway tab"
if [ -n "$POWER_USER_RESTORE" ]; then
    dock exec "$CONTAINER" plesk bin poweruser --off >/dev/null 2>&1
    POWER_USER_RESTORE=""
fi

if [ "${RUNWAY_SMOKE_SUB:-1}" = "1" ]; then
    echo "== scratch subdomain $SUB_DOMAIN"
    if ! dock exec "$CONTAINER" plesk bin subdomain --info "$SUB" -domain "$DOMAIN" >/dev/null 2>&1; then
        dock exec "$CONTAINER" plesk bin subdomain --create "$SUB" -domain "$DOMAIN" -www-root "/$SUB" >/dev/null 2>&1 && CREATED_SUB=1
    fi
    SUB_ID=$(get overview | jexpr "[a['domainId'] for a in d['data']['apps'] if a['domain'] == '$SUB_DOMAIN'][0]")
    case "$SUB_ID" in ''|*[!0-9]*) bad "subdomain $SUB_DOMAIN is not available: $SUB_ID"; SUB_ID="" ;; *) ok "subdomain $SUB_DOMAIN (#$SUB_ID)" ;; esac
fi

if [ -n "$SUB_ID" ]; then
    post app/remove "{\"site_id\": $SUB_ID}" >/dev/null
    out=$(post app/save "{\"site_id\": $SUB_ID, \"enabled\": false, \"runtime\": \"binary\", \"appRoot\": \"apps/$SUB_DOMAIN\", \"startCmd\": \"./app\"}")
    check "app/save: configure a disabled binary app" "d['status'] == 'success' and d['data']['config']['runtime'] == 'binary' and d['data']['config']['buildCmd'] == ''" "$out"
    check "app/save: a prebuilt binary never keeps a build command" "d['status'] == 'success' and d['data']['config']['buildCmd'] == ''" \
        "$(post app/save "{\"site_id\": $SUB_ID, \"runtime\": \"binary\", \"buildCmd\": \"go build -o bin/app ./cmd/server\"}")"
    if [ "$POWER_USER" != "true" ]; then
        row_icon /admin/domain/list "$SUB_ID" && bad "domain list: Runway icon for the disabled application of $SUB_DOMAIN" \
            || ok "domain list: no Runway icon for a disabled application"
    fi

    echo "== application root in a document root (warning, never an error)"
    SUB_DOCROOT=$(get "app?site_id=$SUB_ID" | jexpr "d['data']['domain']['documentRoot']")
    check "app: the subdomain's own document root ($SUB_DOCROOT) and the one of $DOMAIN" \
        "d['data']['domain']['documentRoot'] not in (None, '', 'httpdocs') and ('$DOMAIN', 'httpdocs', False) in [(r['domain'], r['path'], r['own']) for r in d['data']['documentRoots']]" \
        "$(get "app?site_id=$SUB_ID")"
    check "app/save: an application root inside the document root is saved" "d['status'] == 'success' and d['data']['config']['appRoot'] == '$SUB_DOCROOT/app'" \
        "$(post app/save "{\"site_id\": $SUB_ID, \"appRoot\": \"$SUB_DOCROOT/app\"}")"
    out=$(cli --status "$SUB_DOMAIN")
    echo "$out" | grep -q "^Warning: *the app root is inside the document root of $SUB_DOMAIN ($SUB_DOCROOT)" && ok "CLI --status warns about it" || bad "CLI --status warning: $out"
    post app/save "{\"site_id\": $SUB_ID, \"appRoot\": \"httpdocs\"}" >/dev/null
    cli --status "$SUB_DOMAIN" | grep -q "^Warning: *the app root is inside the document root of $DOMAIN (httpdocs)" && ok "CLI --status: the document root of another domain of the subscription counts too" \
        || bad "CLI --status warning for httpdocs: $(cli --status "$SUB_DOMAIN")"
    post app/save "{\"site_id\": $SUB_ID, \"appRoot\": \"apps/$SUB_DOMAIN\"}" >/dev/null
    cli --status "$SUB_DOMAIN" | grep -q '^Warning:' && bad "CLI --status warns although apps/$SUB_DOMAIN is outside the document roots" || ok "CLI --status: no warning outside the document roots"
    check "app: no appRootDocumentRoot outside the document roots" "d['data']['appRootDocumentRoot'] is None" "$(get "app?site_id=$SUB_ID")"
    # A symbolic link that puts the application root into a document root counts as well: the
    # helper resolves the links as the system user (app-page, app-inspect: document_root).
    SUB_HOME=$(get "app?site_id=$SUB_ID" | jexpr "d['data']['domain']['home']")
    SUB_USER=$(get "app?site_id=$SUB_ID" | jexpr "d['data']['domain']['sysuser']")
    dock exec "$CONTAINER" runuser -u "$SUB_USER" -- ln -sfn ../httpdocs "$SUB_HOME/apps/runway-smoke-link"
    post app/save "{\"site_id\": $SUB_ID, \"appRoot\": \"apps/runway-smoke-link/runway-smoke-api\"}" >/dev/null
    check "app: appRootDocumentRoot follows a link into the document root of $DOMAIN" \
        "d['data']['appRootDocumentRoot'] == {'domain': '$DOMAIN', 'path': 'httpdocs', 'own': False}" "$(get "app?site_id=$SUB_ID")"
    cli --status "$SUB_DOMAIN" | grep -q "^Warning: *the app root is inside the document root of $DOMAIN (httpdocs)" \
        && ok "CLI --status: a link into a document root counts too" || bad "CLI --status warning for a link: $(cli --status "$SUB_DOMAIN")"
    post app/save "{\"site_id\": $SUB_ID, \"appRoot\": \"apps/$SUB_DOMAIN\"}" >/dev/null
    dock exec "$CONTAINER" sh -c "rm -f '$SUB_HOME/apps/runway-smoke-link'; rmdir '$SUB_HOME/httpdocs/runway-smoke-api' 2>/dev/null; true"

    MAX_APPS_BEFORE=$(get settings | jexpr "d['data']['maxAppsPerSubscription']")
    if [ "$(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['enabled']")" = "True" ]; then
        post settings '{"maxAppsPerSubscription": 1}' >/dev/null
        check "maxAppsPerSubscription blocks enabling a second app" "d['status'] == 'error' and list(d['errors']) == ['enabled']" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"enabled\": true}")"
        post settings "{\"maxAppsPerSubscription\": $MAX_APPS_BEFORE}" >/dev/null
    else
        skip "maxAppsPerSubscription: the app of $DOMAIN is not enabled"
    fi

    echo "== sample (helper app-sample)"
    GO_INSTALLED=$(get "app?site_id=$SUB_ID" | jexpr "[t['id'] for t in d['data']['toolchains']['go']]")
    out=$(post app/sample "{\"site_id\": $SUB_ID, \"runtime\": \"go\", \"listen\": \"tcp\", \"force\": true}")
    check_or_helper "app/sample writes the Go sample and points the config at it" \
        "d['status'] == 'success' and len(d['data']['written']) > 0 and d['data']['config']['runtime'] == 'go' and d['data']['config']['startCmd'] != '' and d['data']['config']['enabled'] is False and (d['data']['config']['toolchain'] in $GO_INSTALLED or $GO_INSTALLED == [])" \
        "$out" "Unknown command: app-sample"
    if [ "$(echo "$out" | jexpr "d['status']")" = "success" ]; then
        check "app/sample refuses a non-empty application root without force (field force)" "d['status'] == 'error' and list(d['errors']) == ['force'] and 'not empty' in d['errors']['force'][0]" \
            "$(post app/sample "{\"site_id\": $SUB_ID, \"runtime\": \"go\", \"listen\": \"tcp\"}")"
    fi
    if [ "$(get "app?site_id=$SUB_ID" | jexpr "len(d['data']['toolchains']['python']) > 0")" = "True" ]; then
        check "app/sample: the message counts a single file" "d['status'] == 'success' and 'one file' in d['data']['message']" \
            "$(post app/sample "{\"site_id\": $SUB_ID, \"runtime\": \"python\", \"listen\": \"tcp\", \"force\": true}")"
    else
        skip "app/sample single-file message: no Python toolchain"
    fi
    check "app/fetch: invalid file name" "d['status'] == 'error' and list(d['errors']) == ['filename']" \
        "$(post app/fetch "{\"site_id\": $SUB_ID, \"url\": \"https://example.com/app\", \"filename\": \"../x\"}")"

    echo "== path mode and static paths (web server configuration)"
    out=$(post app/save "{\"site_id\": $SUB_ID, \"enabled\": true, \"runtime\": \"binary\", \"buildCmd\": \"\", \"startCmd\": \"./app\", \"mode\": \"path\", \"mountPath\": \"api/\", \"staticPaths\": \"/api/static, /assets\"}")
    check "app/save: path mode with static paths" "d['status'] == 'success' and d['data']['config']['mode'] == 'path' and d['data']['config']['mountPath'] == '/api' and d['data']['config']['staticPaths'] == ['/api/static', '/assets']" "$out"
    CONF=/var/www/vhosts/system/$SUB_DOMAIN/conf
    wait_conf -qF 'location ~ ^/api(?!/(static)(/|$))(/|$) {' "$CONF/nginx.conf"
    wait_conf -q 'ProxyPass /api ' "$CONF/httpd.conf"
    dock exec "$CONTAINER" grep -qF 'location ~ ^/api(?!/(static)(/|$))(/|$) {' "$CONF/nginx.conf" && ok "nginx: location for the mount path without the static path" || bad "nginx location: $(dock exec "$CONTAINER" grep -A1 Runway "$CONF/nginx.conf")"
    dock exec "$CONTAINER" sh -c "grep -q 'ProxyPass /api/static !' $CONF/httpd.conf && grep -q 'ProxyPass /api http://127.0.0.1:[0-9]*/api retry=0' $CONF/httpd.conf" && ok "apache: ProxyPass for the mount path, static path excluded" || bad "apache ProxyPass: $(dock exec "$CONTAINER" grep ProxyPass "$CONF/httpd.conf")"
    dock exec "$CONTAINER" nginx -t >/dev/null 2>&1 && ok "nginx -t" || bad "nginx -t: $(dock exec "$CONTAINER" nginx -t 2>&1 | tail -2)"
    dock exec "$CONTAINER" sh -c "grep -A1 '<IfVersion >= 2.4.47>' $CONF/httpd.conf | grep -q 'ProxyPass /api http://127.0.0.1:[0-9]*/api retry=0 upgrade=websocket'" && ok "apache: WebSocket upgrade for Apache 2.4.47+" || bad "apache upgrade=websocket: $(dock exec "$CONTAINER" grep -n 'IfVersion' "$CONF/httpd.conf")"
    dock exec "$CONTAINER" sh -c 'apache2ctl -t 2>&1 || httpd -t 2>&1' | grep -q 'Syntax OK' && ok "apache configuration test" || bad "apachectl -t: $(dock exec "$CONTAINER" sh -c 'apache2ctl -t 2>&1 | tail -3')"
    IP=$(dock exec "$CONTAINER" hostname -I | awk '{print $1}')
    code=$(dock exec "$CONTAINER" curl -s -k -o /dev/null -w '%{http_code}' --resolve "$SUB_DOMAIN:443:$IP" "https://$SUB_DOMAIN/apix")
    [ "$code" = "404" ] && ok "/apix is not proxied (web server answers 404)" || bad "/apix answered HTTP $code"
    out=$(cli --status "$SUB_DOMAIN")
    echo "$out" | grep -q '^Mode: *path /api' && ok "CLI --status shows the path mode" || bad "CLI --status path mode: $out"
    if [ "$(get "app?site_id=$SITE_ID" | jexpr "d['data']['config']['enabled']")" = "True" ]; then
        post settings '{"maxAppsPerSubscription": 1}' >/dev/null
        check "maxAppsPerSubscription does not block saving an enabled app" "d['status'] == 'success' and d['data']['config']['healthPath'] == '/api/health?full=1'" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"healthPath\": \"/api/health?full=1\"}")"
        post settings "{\"maxAppsPerSubscription\": $MAX_APPS_BEFORE}" >/dev/null
    fi

    echo "== fetch (helper app-deploy with fetch)"
    BIN=$(dock exec "$CONTAINER" sh -c "test -x /var/www/vhosts/$DOMAIN/$APP_ROOT/bin/app && echo /var/www/vhosts/$DOMAIN/$APP_ROOT/bin/app")
    if [ -z "$BIN" ]; then
        skip "fetch: no binary at $APP_ROOT/bin/app to serve"
    else
        SHA=$(dock exec "$CONTAINER" sh -c "mkdir -p /root/runway-smoke-www && cp '$BIN' /root/runway-smoke-www/app && sha256sum /root/runway-smoke-www/app | cut -d' ' -f1")
        dock exec -d "$CONTAINER" python3 -m http.server "$FETCH_PORT" --bind 127.0.0.1 --directory /root/runway-smoke-www
        dock exec "$CONTAINER" sh -c 'mkdir -p /etc/runway && touch /etc/runway/allow-insecure-fetch'
        sleep 1
        out=$(post app/fetch "{\"site_id\": $SUB_ID, \"url\": \"http://127.0.0.1:$FETCH_PORT/app\", \"sha256\": \"$SHA\"}")
        if [ "$(echo "$out" | jexpr "d['status'] == 'success' and d['data']['job'] == 'deploy-$SUB_ID'")" = "True" ]; then
            state=$(wait_deploy "$SUB_ID")
            files=$(dock exec "$CONTAINER" sh -c "ls /var/www/vhosts/$DOMAIN/apps/$SUB_DOMAIN/ 2>/dev/null | tr '\n' ' '")
            if [ "$state" = "succeeded" ] && echo "$files" | grep -qw app; then
                ok "app/fetch downloaded the binary (job $state)"
                sleep 2
                code=$(dock exec "$CONTAINER" curl -s -k -o /dev/null -w '%{http_code}' --resolve "$SUB_DOMAIN:443:$IP" "https://$SUB_DOMAIN/api/x")
                [ "$code" = "200" ] && ok "the fetched binary serves /api/x" || bad "/api/x answered HTTP $code"
                post app/control "{\"site_id\": $SUB_ID, \"op\": \"stop\"}" >/dev/null
                check "app/control stop: the application stays stopped (status stopped)" "d['data']['stopped'] is True and d['data']['service']['active_state'] != 'active'" "$(get "app/status?site_id=$SUB_ID")"
                post app/control "{\"site_id\": $SUB_ID, \"op\": \"start\"}" >/dev/null
                sleep 2
                check "app/control start: runs it again" "d['data']['stopped'] is False and d['data']['service']['active_state'] in ('active', 'activating')" "$(get "app/status?site_id=$SUB_ID")"
                out=$(post app/fetch "{\"site_id\": $SUB_ID, \"url\": \"http://127.0.0.1:$FETCH_PORT/app\", \"sha256\": \"$(printf '0%.0s' $(seq 1 64))\"}")
                if [ "$(echo "$out" | jexpr "d['status']")" = "success" ]; then
                    state=$(wait_deploy "$SUB_ID")
                    [ "$state" = "failed" ] && ok "app/fetch: a wrong checksum fails the job" || bad "app/fetch with a wrong checksum: job $state"
                else
                    check "app/fetch: a wrong checksum is refused" "d['status'] == 'error'" "$out"
                fi
            elif grep -q 'Unknown command: app-sample' <<<"$(post app/sample "{\"site_id\": $SUB_ID, \"runtime\": \"go\"}")"; then
                skip "app/fetch: the deployed helper ignores fetch (job $state, files: $files)"
            else
                bad "app/fetch: job $state, files: $files, log: $(get "app/logs?site_id=$SUB_ID&kind=deploy&lines=15" | jexpr "d['data']['log']" | tail -5)"
            fi
        else
            bad "app/fetch: $out"
        fi
    fi

    echo "== document root of the subdomain $SUB_DOMAIN (inside its application root)"
    SUB_DR=$(get "app?site_id=$SUB_ID" | jexpr "d['data']['domain']['documentRoot']")
    SUB_TARGET=apps/$SUB_DOMAIN/public
    SUB_RUNNING=False
    for _ in $(seq 1 15); do
        SUB_RUNNING=$(get "app/status?site_id=$SUB_ID" | jexpr "d['data'].get('listener') == 'ok'")
        [ "$SUB_RUNNING" = "True" ] && break
        sleep 2
    done
    DR_SUB_BEFORE=$SUB_DR
    out=$(post app/save "{\"site_id\": $SUB_ID, \"documentRoot\": \"$SUB_TARGET\"}")
    check "app/save: the subdomain's document root moves into its application root (only the document root: no restart)" \
        "d['status'] == 'success' and d['data']['documentRoot'] == '$SUB_TARGET' and d['data']['documentRootChanged'] is True and d['data']['job'] is None and d['data']['build'] is False" "$out"
    [ "$(docroot_info "$SUB_DOMAIN")" = "$SUB_HOME/$SUB_TARGET" ] && ok "Plesk stores the new document root of $SUB_DOMAIN" || bad "Plesk's document root of $SUB_DOMAIN: $(docroot_info "$SUB_DOMAIN")"
    # Runway created the application root as the system user (0750, group psacln): the web server
    # passes it only with the search permission for others that docroot-access added.
    [ "$(dock exec "$CONTAINER" stat -c %a "$SUB_HOME/apps/$SUB_DOMAIN")" = "751" ] && ok "the application root became searchable for the web server (0751)" \
        || bad "mode of the application root: $(dock exec "$CONTAINER" stat -c '%a %U:%G' "$SUB_HOME/apps/$SUB_DOMAIN")"
    if [ "$SUB_RUNNING" = "True" ]; then
        # Path mode /api with the static path /api/static: /api/static/... comes from the document
        # root, the rest of /api from the application, everything outside /api from the document root.
        dock exec "$CONTAINER" runuser -u "$SUB_USER" -- sh -c "umask 022; mkdir -p '$SUB_HOME/$SUB_TARGET/api/static' && echo runway-smoke-sub > '$SUB_HOME/$SUB_TARGET/api/static/smoke.txt'"
        wait_conf -qF "root \"$SUB_HOME/$SUB_TARGET\";" "$CONF/nginx.conf" >/dev/null
        dock exec "$CONTAINER" grep -qF 'location ~ ^/api(?!/(static)(/|$))(/|$) {' "$CONF/nginx.conf" \
            && ok "nginx: the Runway snippet of $SUB_DOMAIN is still there" || bad "nginx configuration of $SUB_DOMAIN: $(dock exec "$CONTAINER" grep -n 'root "\|Runway' "$CONF/nginx.conf")"
        body=$(wait_body "$SUB_DOMAIN" /api/static/smoke.txt runway-smoke-sub)
        [ "$body" = "runway-smoke-sub" ] && ok "nginx serves the static path /api/static from the new document root" || bad "/api/static/smoke.txt answered: $(echo "$body" | head -c 200)"
        code=$(https_get "$SUB_DOMAIN" /api/x -o /dev/null -w '%{http_code}')
        [ "$code" = "200" ] && ok "/api/x still reaches the application" || bad "/api/x answered HTTP $code"
        # A marker file outside /api proves that the rest of the site comes from the new root (the
        # old root has a default page too, so an HTTP 200 alone would prove nothing).
        dock exec "$CONTAINER" runuser -u "$SUB_USER" -- sh -c "umask 022; echo runway-smoke-root > '$SUB_HOME/$SUB_TARGET/runway-smoke-root.txt'"
        body=$(wait_body "$SUB_DOMAIN" /runway-smoke-root.txt runway-smoke-root)
        [ "$body" = "runway-smoke-root" ] && ok "path mode: the rest of the site comes from the new document root" || bad "/runway-smoke-root.txt answered: $(echo "$body" | head -c 200)"
    else
        skip "static path from the new document root of $SUB_DOMAIN: its application is not running"
    fi
    out=$(post app/save "{\"site_id\": $SUB_ID, \"documentRoot\": \"$DR_SUB_BEFORE\"}")
    if [ "$(echo "$out" | jexpr "d['status'] == 'success' and d['data']['documentRootChanged'] is True")" = "True" ] \
            && [ "$(docroot_info "$SUB_DOMAIN")" = "$SUB_HOME/$DR_SUB_BEFORE" ]; then
        ok "document root of $SUB_DOMAIN restored ($DR_SUB_BEFORE)"
        DR_SUB_BEFORE=""
    else
        bad "restoring the document root of $SUB_DOMAIN: $out"
    fi

    echo "== worker (listen none)"
    out=$(post app/save "{\"site_id\": $SUB_ID, \"listen\": \"none\"}")
    check_or_helper "app/save: listen none makes a worker without web configuration" \
        "d['status'] == 'success' and d['data']['config']['mode'] == 'worker' and d['data']['config']['listen'] == 'none'" \
        "$out" "Invalid listen mode"
    if [ "$(echo "$out" | jexpr "d['status']")" = "success" ]; then
        wait_conf_gone -q 'Runway' "$CONF/nginx.conf" && ok "nginx: no proxy for a worker" || bad "nginx config of a worker still proxies"
        check "overview: a worker has no port and no app URL" "[(a['port'], a['appUrl'], a['mode']) for a in d['data']['apps'] if a['domainId'] == $SUB_ID] == [(None, None, 'worker')]" "$(get overview)"
        check "a worker ignores zero-downtime deployments (never switchable)" "d['status'] == 'success' and d['data']['config']['switchable'] is False and d['data']['job'] is None" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"zeroDowntime\": true}")"
        post app/save "{\"site_id\": $SUB_ID, \"zeroDowntime\": false}" >/dev/null
        # A worker needs no health check path for a kept expected content (no errorHealthMatchPath).
        check "app/save: a worker may keep an expected content without a health check path (no field error)" \
            "d['status'] == 'success' and (d['data']['config']['healthPath'], d['data']['config']['healthMatch']) == ('', 'Healthy')" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"healthPath\": \"\", \"healthMatch\": \"Healthy\"}")"
        check "app/save: a worker keeps a health check path and an expected content" \
            "d['status'] == 'success' and (d['data']['config']['healthPath'], d['data']['config']['healthMatch']) == ('/', 'Healthy')" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"healthPath\": \"/\", \"healthMatch\": \"Healthy\"}")"
        st=$(dock exec "$CONTAINER" python3 -c "import json; s = json.load(open('/var/lib/runway/apps/$SUB_ID.json')); print((s['health_path'], s['health_match']))" 2>&1)
        [ "$st" = "('', '')" ] && ok "a worker's helper state has neither a health path nor an expected content" || bad "worker helper state: $st"
        # The Health line shows what the helper checks, not the values the panel kept for the worker.
        line=$(cli --status "$SUB_DOMAIN" | grep -F 'Health:')
        if [ -n "$line" ] && ! echo "$line" | grep -qF '('; then
            ok "CLI --status: a worker's Health line shows neither the kept path nor the expected content"
        else
            bad "CLI --status Health line of a worker: ${line:-none}"
        fi
        post app/save "{\"site_id\": $SUB_ID, \"healthPath\": \"\", \"healthMatch\": \"\"}" >/dev/null
        check "app/save: mode web gives the worker a listener again" "d['status'] == 'success' and d['data']['config']['listen'] in ('tcp', 'unix') and d['data']['config']['mode'] == 'web'" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"mode\": \"web\", \"listen\": \"none\"}")"
    fi

    check "app/remove of the scratch app" "d['status'] == 'success'" "$(post app/remove "{\"site_id\": $SUB_ID}")"
fi


echo "== $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -eq 0 ]
