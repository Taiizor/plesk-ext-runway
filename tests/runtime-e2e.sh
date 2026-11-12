#!/bin/bash
# End-to-end runtime matrix through the panel API and nginx (HTTPS). Runs on the development
# machine against the local Plesk test container, like tests/api-smoke.sh:
#
#   bash tests/runtime-e2e.sh                         # every runtime, tcp and unix
#   RUNTIMES="go python" LISTENS="unix" bash tests/runtime-e2e.sh
#   RUNWAY_E2E_RUNTIMES=go bash tests/runtime-e2e.sh  # same as RUNTIMES (CI runs the Go part)
#
# For each runtime and listen mode it writes the sample app (api/app/sample, force), enables it
# with health path "/" (api/app/save), waits for the build (api/app/status), then checks the
# response of https://DOMAIN/ through nginx, the listener and health fields of app/status and
# the deploy/app logs. Unix mode is skipped where the runtime cannot use it (helper metadata
# unix_toolchain_re, e.g. PHP without FrankenPHP). At the end it prints the matrix and restores
# the previous configuration of the domain (the samples live in APP_ROOT, not in the domain's
# own application directory). With FEATURES=1 (default) it then checks path mode, static paths,
# trigger files, worker mode, suspension of the subscription, the CLI (including Stop
# persistence) with the Go sample, zero-downtime deployments (tcp and unix: a request loop inside
# the container counts every non-2xx answer of nginx while the setting is turned on, during Build &
# restart and Restart, and while it is turned off), and a WebSocket handshake through nginx and
# through Apache (ProxyPass upgrade=websocket). RUNWAY_E2E_OCTANE_ROOT=<path in the subscription> additionally
# runs a prepared Laravel project with Octane (composer create-project laravel/laravel + composer
# require laravel/octane + php artisan octane:install --server=frankenphp) with the suggested
# commands in tcp and unix mode (needs a FrankenPHP toolchain).
#
# Needs the toolchains of the tested runtimes (installed through Runway, Ruby from Plesk or the
# system). Environment: CONTAINER (runway-plesk), PANEL (http://localhost:18880), SITE_ID (1),
# DOMAIN (gotest.local), APP_ROOT (apps/runway-e2e), RUNTIMES, LISTENS (tcp unix),
# BUILD_WAIT (seconds per build, 1200), NGINX_IP (the container's address), PYTHON.
set -u
CONTAINER=${CONTAINER:-runway-plesk}
PANEL=${PANEL:-http://localhost:18880}
SITE_ID=${SITE_ID:-1}
DOMAIN=${DOMAIN:-gotest.local}
APP_ROOT=${APP_ROOT:-apps/runway-e2e}
RUNTIMES=${RUNWAY_E2E_RUNTIMES:-${RUNTIMES:-go rust bun python php java dotnet ruby}}
LISTENS=${LISTENS:-tcp unix}
BUILD_WAIT=${BUILD_WAIT:-1200}
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    for candidate in python3 python; do
        if "$candidate" -c 'import json' >/dev/null 2>&1; then PY=$candidate; break; fi
    done
fi
API=$PANEL/modules/runway/index.php/api
WORK=$(mktemp -d)
JAR=$WORK/cookies
PASS=0
FAIL=0
MATRIX=""
SAVED=""
PHP_TCP_TOOLCHAIN=""

dock() { MSYS_NO_PATHCONV=1 docker "$@"; }
ok()   { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }
jexpr() { "$PY" -c "import json,sys
try:
    d = json.load(sys.stdin)
    print($1)
except Exception as exc:
    print('ERROR', exc)"; }
get()  { curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' "$API/$1"; }
post() { curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' -H "X-Forgery-Protection-Token: $TOKEN" \
              -H 'Content-Type: application/json' -d "$2" "$API/$1"; }
row()  { MATRIX="$MATRIX$(printf '%-8s %-5s %-22s %-8s %-9s %s' "$1" "$2" "$3" "$4" "$5" "$6")"$'\n'; }

# wait_deploy [SINCE]: waits for the deploy job queued at or after the epoch SINCE (default: any).
wait_deploy() {
    local state="" since=${1:-0} deadline=$(( $(date +%s) + BUILD_WAIT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        state=$(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['deploy']['state'] if (d['data']['deploy'].get('queued_epoch') or 0) >= $since else 'old'")
        case "$state" in queued|running|old) sleep 3 ;; *) break ;; esac
    done
    echo "$state"
}

# wait_listener: for applications without a build command (no deploy job): waits until the
# service listens, prints "started" or "no-listener".
wait_listener() {
    local i
    for i in $(seq 1 30); do
        if [ "$(get "app/status?site_id=$SITE_ID" | jexpr "d['data'].get('listener')")" = "ok" ]; then
            echo started
            return
        fi
        sleep 2
    done
    echo no-listener
}

# Request loop inside the container through nginx (HTTPS to the container's address, Host =
# the domain): loop_start, then loop_result prints "<ok> <failed> <first failures>".
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
    dock exec "$CONTAINER" rm -f /root/runway-e2e-loop.out /root/runway-e2e-loop.stop
    echo "$LOOP_PY" | dock exec -i "$CONTAINER" sh -c 'cat > /root/runway-e2e-loop.py'
    dock exec "$CONTAINER" python3 /root/runway-e2e-loop.py "$DOMAIN" /root/runway-e2e-loop.out /root/runway-e2e-loop.stop &
    LOOP_PID=$!
    sleep 2
}
loop_result() {
    dock exec "$CONTAINER" touch /root/runway-e2e-loop.stop
    wait "$LOOP_PID" 2>/dev/null
    LOOP_PID=""
    dock exec "$CONTAINER" cat /root/runway-e2e-loop.out 2>/dev/null
    dock exec "$CONTAINER" rm -f /root/runway-e2e-loop.py /root/runway-e2e-loop.out /root/runway-e2e-loop.stop
}

restore() {
    if [ -n "$SAVED" ]; then
        echo "== restoring the previous configuration of $DOMAIN"
        post app/save "$SAVED" | jexpr "d['status']"
        post app/control "{\"site_id\": $SITE_ID, \"op\": \"deploy\"}" >/dev/null
        echo "deploy: $(wait_deploy)"
    fi
    rm -rf "$WORK"
}
trap restore EXIT

echo "== login"
LINK=$(dock exec "$CONTAINER" plesk bin admin --get-login-link -relative-url | tr -d '\r')
curl -s -c "$JAR" -b "$JAR" -L "$PANEL$LINK" -o /dev/null
PAGE=$(curl -s -c "$JAR" -b "$JAR" "$PANEL/modules/runway/index.php/overview")
TOKEN=$(echo "$PAGE" | grep -o 'id="forgery_protection_token" content="[^"]*"' | sed 's/.*content="//;s/"$//')
[ -n "$TOKEN" ] && ok "panel login" || { bad "login failed"; exit 1; }
IP=${NGINX_IP:-$(dock exec "$CONTAINER" hostname -I | awk '{print $1}')}
HOME_DIR=$(dock exec "$CONTAINER" plesk db -Ne "select s.home from sys_users s join hosting h on h.sys_user_id = s.id where h.dom_id = $SITE_ID" | tr -d '\r')
[ -n "$HOME_DIR" ] || HOME_DIR=/var/www/vhosts/$DOMAIN

APP=$(get "app?site_id=$SITE_ID")
SAVED=$(echo "$APP" | jexpr "json.dumps(dict([('site_id', $SITE_ID)] + [(k, v) for k, v in d['data']['config'].items() if k in ('enabled', 'runtime', 'toolchain', 'appRoot', 'listen', 'mode', 'mountPath', 'staticPaths', 'healthPath', 'buildCmd', 'startCmd', 'autoDeploy')]))")
case "$SAVED" in ERROR*) bad "cannot read the configuration: $APP"; SAVED=""; exit 1 ;; esac
UNIX_RE=$(get context | jexpr "json.dumps(dict((r['key'], r.get('unix_toolchain_re') or '') for r in d['data']['runtimes']))")
check_save=$(post app/save "{\"site_id\": $SITE_ID, \"enabled\": false, \"appRoot\": \"$APP_ROOT\", \"healthPath\": \"/\"}")
[ "$(echo "$check_save" | jexpr "d['status']")" = "success" ] && ok "switched $DOMAIN to $APP_ROOT (disabled)" || { bad "save: $check_save"; exit 1; }

run_case() {
    local rt=$1 listen=$2 out toolchain state body st health listener logs started built
    # A clean application root for every case (the helper recreates it as the system user).
    dock exec "$CONTAINER" rm -rf "$HOME_DIR/$APP_ROOT"
    out=$(post app/sample "{\"site_id\": $SITE_ID, \"runtime\": \"$rt\", \"listen\": \"$listen\", \"force\": true}")
    if [ "$(echo "$out" | jexpr "d['status'] == 'success' and d['data']['config']['runtime'] == '$rt' and d['data']['config']['listen'] == '$listen'")" != "True" ]; then
        bad "$rt $listen: sample: $(echo "$out" | head -c 300)"
        row "$rt" "$listen" "-" "sample" "-" "$(echo "$out" | jexpr "d.get('errors')" | head -c 80)"
        return
    fi
    toolchain=$(echo "$out" | jexpr "d['data']['config']['toolchain'] or '-'")
    if [ "$rt" = "php" ] && [ "$listen" = "tcp" ] && [ -z "$PHP_TCP_TOOLCHAIN" ]; then PHP_TCP_TOOLCHAIN=$toolchain; fi
    started=$(( $(date +%s) - 5 ))
    # The sample endpoint already builds an enabled application; the first case enables it.
    # Without a build command (e.g. PHP) there is no deploy job: the service is restarted directly.
    built=$(echo "$out" | jexpr "d['data']['build']")
    if [ "$(echo "$out" | jexpr "d['data']['config']['enabled']")" != "True" ]; then
        out=$(post app/save "{\"site_id\": $SITE_ID, \"enabled\": true}")
        [ "$(echo "$out" | jexpr "d['status']")" = "success" ] || bad "$rt $listen: enable: $(echo "$out" | head -c 300)"
        built=$(echo "$out" | jexpr "d['data']['build']")
    fi
    if [ "$built" = "True" ]; then
        state=$(wait_deploy "$started")
    else
        state=$(wait_listener)
    fi
    if [ "$state" != "succeeded" ] && [ "$state" != "started" ]; then
        bad "$rt $listen ($toolchain): deploy $state: $(get "app/logs?site_id=$SITE_ID&kind=deploy&lines=15" | jexpr "d['data']['log']" | tail -n 6)"
        row "$rt" "$listen" "$toolchain" "$state" "-" "build/start failed"
        return
    fi
    # curl inside the container: its address is not reachable from Docker Desktop hosts.
    body=$(dock exec "$CONTAINER" curl -sk --max-time 15 --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/" | head -c 200 | tr -d '\r' | head -n 1)
    st=$(get "app/status?site_id=$SITE_ID")
    listener=$(echo "$st" | jexpr "d['data'].get('listener')")
    health=$(echo "$st" | jexpr "d['data'].get('health')")
    logs=True
    if [ "$built" = "True" ]; then
        logs=$(get "app/logs?site_id=$SITE_ID&kind=deploy&lines=50" | jexpr "'Deployment succeeded' in d['data']['log']")
    fi
    if echo "$body" | grep -qi "runway" && [ "$listener" = "ok" ] && [ "$health" = "healthy" ] && [ "$logs" = "True" ]; then
        ok "$rt $listen ($toolchain): $body"
    else
        bad "$rt $listen ($toolchain): body=[$body] listener=$listener health=$health deploy-log=$logs"
    fi
    [ "$(get "app/logs?site_id=$SITE_ID&kind=app&lines=20" | jexpr "d['status'] == 'success' and isinstance(d['data']['log'], str)")" = "True" ] \
        || bad "$rt $listen: app log"
    row "$rt" "$listen" "$toolchain" "$state" "$health" "$body ($(( $(date +%s) - started - 5 ))s)"
}

for rt in $RUNTIMES; do
    for listen in $LISTENS; do
        re=$(echo "$UNIX_RE" | jexpr "d.get('$rt', '')")
        if [ "$listen" = "unix" ] && [ -n "$re" ] && [ "$re" != "None" ]; then
            if ! get "app?site_id=$SITE_ID" | jexpr "any(__import__('re').match(r'$re', t['id']) for t in d['data']['toolchains']['$rt'])" | grep -q True; then
                echo "SKIP  $rt unix: no toolchain matches $re"
                row "$rt" "$listen" "-" "skipped" "-" "no toolchain for unix sockets"
                continue
            fi
        fi
        echo "== $rt ($listen)"
        run_case "$rt" "$listen"
    done
    # PHP: tcp once more with the other kind of toolchain (Plesk PHP with php -S, or FrankenPHP),
    # whichever the first tcp case did not use; the sample keeps the configured toolchain.
    if [ "$rt" = "php" ] && [ -n "$PHP_TCP_TOOLCHAIN" ]; then
        other=$(get "app?site_id=$SITE_ID" | jexpr "([t['id'] for t in d['data']['toolchains']['php'] if t['id'].split('-')[0] != '$PHP_TCP_TOOLCHAIN'.split('-')[0]] or [''])[0]")
        if [ -n "$other" ]; then
            echo "== php (tcp, $other)"
            post app/save "{\"site_id\": $SITE_ID, \"enabled\": false, \"runtime\": \"php\", \"toolchain\": \"$other\", \"listen\": \"tcp\"}" >/dev/null
            run_case php tcp
        fi
    fi
done

# --- Features through nginx with the Go sample: path mode, static paths, trigger files, worker,
# suspension, CLI. FEATURES=0 skips them.
status_field() { get "app/status?site_id=$SITE_ID" | jexpr "$1"; }
fetch_url() { dock exec "$CONTAINER" curl -sk --max-time 15 --resolve "$DOMAIN:443:$IP" "https://$DOMAIN$1" | tr -d '\r' | head -c 300; }
save_wait() { # save_wait JSON: saves, waits for the build when one was started
    local out since=$(( $(date +%s) - 5 ))
    out=$(post app/save "{\"site_id\": $SITE_ID, $1}")
    if [ "$(echo "$out" | jexpr "d['status']")" != "success" ]; then echo "save failed: $out"; return; fi
    if [ "$(echo "$out" | jexpr "d['data']['build']")" = "True" ]; then wait_deploy "$since"; else sleep 3; echo saved; fi
}
if [ "${FEATURES:-1}" = "1" ] && echo " $RUNTIMES " | grep -q ' go '; then
    echo "== features (Go sample on $DOMAIN)"
    dock exec "$CONTAINER" rm -rf "$HOME_DIR/$APP_ROOT"
    since=$(( $(date +%s) - 5 ))
    out=$(post app/sample "{\"site_id\": $SITE_ID, \"runtime\": \"go\", \"listen\": \"tcp\", \"force\": true}")
    # An enabled application is built by the sample endpoint itself.
    [ "$(echo "$out" | jexpr "d['data']['build']")" = "True" ] && wait_deploy "$since" >/dev/null
    state=$(save_wait '"enabled": true, "mode": "web", "staticPaths": []')
    [ "$state" = "succeeded" ] || [ "$state" = "saved" ] || bad "features: go sample: $state"
    SYSUSER=$(get "app?site_id=$SITE_ID" | jexpr "d['data']['domain']['sysuser']")
    as_user() { dock exec -u "$SYSUSER" "$CONTAINER" sh -c "$1"; }
    as_user "mkdir -p '$HOME_DIR/httpdocs/api/static' '$HOME_DIR/httpdocs/assets' && echo static-ok > '$HOME_DIR/httpdocs/api/static/s.txt' && echo asset-ok > '$HOME_DIR/httpdocs/assets/a.txt'"

    state=$(save_wait '"mode": "path", "mountPath": "/api", "staticPaths": ["/api/static"]')
    body=$(fetch_url /api/hello); root=$(fetch_url /); static=$(fetch_url /api/static/s.txt)
    if echo "$body" | grep -q "Hello from Go" && ! echo "$root" | grep -q "Hello from Go" && [ "$static" = "static-ok" ]; then
        ok "path mode: /api proxied, / from the document root, /api/static excluded"
    else
        bad "path mode ($state): /api=[$body] /=[$(echo "$root" | head -c 60)] static=[$static]"
    fi
    row go path tcp "$state" "-" "/api -> app, / -> docroot, /api/static -> docroot"

    state=$(save_wait '"mode": "web", "mountPath": "", "staticPaths": ["/assets"]')
    body=$(fetch_url /); asset=$(fetch_url /assets/a.txt)
    if echo "$body" | grep -q "Hello from Go" && [ "$asset" = "asset-ok" ]; then
        ok "web mode with a static path: / proxied, /assets from the document root"
    else
        bad "static path ($state): /=[$body] /assets=[$asset]"
    fi
    row go web+static tcp "$state" "-" "/ -> app, /assets -> docroot"

    started_at=$(status_field "d['data']['service']['started_at']")
    sleep 2
    as_user "mkdir -p '$HOME_DIR/$APP_ROOT/tmp' && touch '$HOME_DIR/$APP_ROOT/tmp/restart.txt'"
    restarted=""
    for _ in $(seq 1 20); do
        now=$(status_field "d['data']['service']['started_at']")
        if [ -n "$now" ] && [ "$now" != "$started_at" ] && [ "$(status_field "d['data'].get('listener')")" = "ok" ]; then restarted=1; break; fi
        sleep 2
    done
    [ -n "$restarted" ] && ok "trigger tmp/restart.txt restarts the service" || bad "tmp/restart.txt: started_at stayed $started_at"
    since=$(( $(date +%s) - 2 ))
    as_user "touch '$HOME_DIR/$APP_ROOT/tmp/deploy.txt'"
    state=$(wait_deploy "$since")
    source=$(status_field "d['data']['deploy'].get('source')")
    [ "$state" = "succeeded" ] && [ "$source" = "trigger file" ] && ok "trigger tmp/deploy.txt builds and restarts" || bad "tmp/deploy.txt: $state ($source)"
    row go triggers tcp "$state" "-" "restart.txt + deploy.txt"

    state=$(save_wait '"mode": "worker", "listen": "none"')
    conf=$(dock exec "$CONTAINER" grep -c Runway "/var/www/vhosts/system/$DOMAIN/conf/nginx.conf")
    st=$(get "app/status?site_id=$SITE_ID")
    if [ "$(echo "$st" | jexpr "d['data']['service']['active_state'] == 'active' and d['data'].get('listener') in ('worker', None)")" = "True" ] && [ "$conf" = "0" ] \
            && ! fetch_url / | grep -q "Hello from Go"; then
        ok "worker: service runs, no nginx snippet, the site is served from the document root"
    else
        bad "worker ($state): nginx snippets=$conf status=$(echo "$st" | jexpr "(d['data']['service']['active_state'], d['data'].get('listener'))")"
    fi
    row go worker none "$state" "-" "service active, no proxy"
    state=$(save_wait '"mode": "web", "listen": "tcp"')

    echo "== suspend / activate the subscription"
    dock exec "$CONTAINER" plesk bin subscription --webspace-off "$DOMAIN" >/dev/null
    stopped=""
    for _ in $(seq 1 30); do
        if [ "$(status_field "d['data'].get('suspended') is True and d['data']['service']['active_state'] != 'active'")" = "True" ]; then stopped=1; break; fi
        sleep 2
    done
    [ -n "$stopped" ] && ok "suspending the subscription stops the service" || bad "suspend: $(status_field "(d['data'].get('suspended'), d['data']['service']['active_state'])")"
    dock exec "$CONTAINER" plesk bin subscription --webspace-on "$DOMAIN" >/dev/null
    running=""
    for _ in $(seq 1 30); do
        if [ "$(status_field "d['data'].get('suspended') is False and d['data']['service']['active_state'] == 'active' and d['data'].get('listener') == 'ok'")" = "True" ]; then running=1; break; fi
        sleep 2
    done
    [ -n "$running" ] && fetch_url / | grep -q "Hello from Go" && ok "activating the subscription starts the service again" || bad "activate: $(status_field "(d['data'].get('suspended'), d['data']['service']['active_state'])")"
    row go suspend tcp "$([ -n "$stopped" ] && [ -n "$running" ] && echo ok || echo failed)" "-" "webspace-off stops, webspace-on starts"

    echo "== CLI"
    cli() { dock exec "$CONTAINER" plesk ext runway "$@" 2>&1; }
    out=$(cli --list); echo "$out" | grep -q "^$DOMAIN " && ok "CLI --list" || bad "CLI --list: $out"
    out=$(cli --status "$DOMAIN"); echo "$out" | grep -q "^Runtime: *go" && ok "CLI --status" || bad "CLI --status: $out"
    out=$(cli --restart "$DOMAIN"); code=$?
    [ $code -eq 0 ] && ok "CLI --restart" || bad "CLI --restart ($code): $out"
    out=$(cli --deploy "$DOMAIN"); code=$?
    [ $code -eq 0 ] && echo "$out" | grep -q "succeeded" && ok "CLI --deploy" || bad "CLI --deploy ($code): $out"
    as_user "rm -rf '$HOME_DIR/httpdocs/api' '$HOME_DIR/httpdocs/assets'"

    echo "== Stop persists (CLI)"
    cli --stop "$DOMAIN" >/dev/null
    out=$(cli --deploy "$DOMAIN"); code=$?
    st=$(status_field "(d['data']['stopped'], d['data']['service']['active_state'])")
    [ $code -eq 0 ] && [ "$st" = "(True, 'inactive')" ] && get "app/logs?site_id=$SITE_ID&kind=deploy&lines=20" | jexpr "'it was not started' in d['data']['log']" | grep -q True \
        && ok "a CLI deploy builds a stopped application but keeps it stopped" || bad "deploy of a stopped app ($code): $st $out"
    cli --status "$DOMAIN" | grep -q '^Stopped:' && ok "CLI --status shows that it stays stopped" || bad "CLI --status: $(cli --status "$DOMAIN")"
    cli --start "$DOMAIN" >/dev/null
    running=""
    for _ in $(seq 1 15); do
        [ "$(status_field "d['data'].get('listener')")" = "ok" ] && running=1 && break
        sleep 2
    done
    [ -n "$running" ] && fetch_url / | grep -q "Hello from Go" && ok "CLI --start runs it again" || bad "start after stop: $(status_field "(d['data']['stopped'], d['data']['service']['active_state'])")"
    row go stop tcp "$([ -n "$running" ] && echo ok || echo failed)" "-" "--stop, --deploy keeps it stopped, --start"

    echo "== zero-downtime deployments (Go sample, tcp and unix)"
    for listen in tcp unix; do
        dock exec "$CONTAINER" rm -rf "$HOME_DIR/$APP_ROOT"
        since=$(( $(date +%s) - 5 ))
        out=$(post app/sample "{\"site_id\": $SITE_ID, \"runtime\": \"go\", \"listen\": \"$listen\", \"force\": true}")
        [ "$(echo "$out" | jexpr "d['data']['build']")" = "True" ] && wait_deploy "$since" >/dev/null
        state=$(save_wait '"enabled": true, "mode": "web", "staticPaths": [], "healthPath": "/", "zeroDowntime": false')
        for _ in $(seq 1 15); do [ "$(status_field "d['data'].get('listener')")" = "ok" ] && break; sleep 2; done
        loop_start
        since=$(( $(date +%s) - 2 ))
        out=$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": true, \"readyTimeout\": 60, \"drainSeconds\": 2}")
        on=$(wait_deploy "$since")
        slot_on=$(status_field "d['data'].get('slot')")
        since=$(( $(date +%s) - 2 ))
        post app/control "{\"site_id\": $SITE_ID, \"op\": \"deploy\"}" >/dev/null
        deployed=$(wait_deploy "$since")
        slot_deploy=$(status_field "d['data'].get('slot')")
        since=$(( $(date +%s) - 2 ))
        post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\"}" >/dev/null
        restarted=$(wait_deploy "$since")
        slot_restart=$(status_field "d['data'].get('slot')")
        since=$(( $(date +%s) - 2 ))
        post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": false}" >/dev/null
        off=$(wait_deploy "$since")
        slot_off=$(status_field "d['data'].get('slot')")
        result=$(loop_result)
        n_bad=$(echo "$result" | awk '{print $2}')
        n_ok=$(echo "$result" | awk '{print $1}')
        if [ "$on/$deployed/$restarted/$off" = "succeeded/succeeded/succeeded/succeeded" ] && [ "$slot_on" = "b" ] && [ "$slot_deploy" = "a" ] \
                && [ "$slot_restart" = "b" ] && [ -z "$slot_off" ] && [ "${n_bad:-1}" = "0" ] && [ "${n_ok:-0}" -gt 20 ]; then
            ok "zero-downtime $listen: on, Build & restart, Restart, off: $n_ok requests through nginx, none failed"
        else
            bad "zero-downtime $listen: jobs $on/$deployed/$restarted/$off, slots $slot_on/$slot_deploy/$slot_restart/$slot_off, loop: $result"
        fi
        row go zd "$listen" "$restarted" "-" "${n_ok:-0} requests, ${n_bad:-?} failed"
    done

    echo "== WebSockets through nginx and Apache"
    # A minimal backend that answers the WebSocket handshake with 101 only when the Upgrade header
    # reaches it (mod_proxy_http drops it unless ProxyPass has upgrade=websocket).
    WS_PY=$(cat <<'PYEOF'
#!/usr/bin/env python3
import base64, hashlib, os
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers.get("Sec-WebSocket-Key", "") + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
            self.end_headers()
            self.close_connection = True
            return
        body = b"no upgrade header\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
PYEOF
)
    dock exec "$CONTAINER" rm -rf "$HOME_DIR/$APP_ROOT"
    as_user "mkdir -p '$HOME_DIR/$APP_ROOT' && echo '$(printf '%s\n' "$WS_PY" | base64 | tr -d '\n')' | base64 -d > '$HOME_DIR/$APP_ROOT/ws.py' && chmod 750 '$HOME_DIR/$APP_ROOT/ws.py'"
    state=$(save_wait '"enabled": true, "runtime": "binary", "listen": "tcp", "mode": "web", "staticPaths": [], "buildCmd": "", "startCmd": "./ws.py", "healthPath": "/"')
    sleep 2
    ws() { dock exec "$CONTAINER" curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
        -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' "$@"; }
    code=$(ws -k --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/ws")
    [ "$code" = "101" ] && ok "WebSocket handshake through nginx" || bad "nginx WebSocket: HTTP $code ($state)"
    # Plesk runs Apache behind nginx on 127.0.0.1:7080/7081 (proxy mode): ask its HTTPS vhost
    # directly (the plain HTTP vhost may redirect to HTTPS).
    code=$(ws -k --resolve "$DOMAIN:7081:127.0.0.1" "https://$DOMAIN:7081/ws")
    [ "$code" = "101" ] && ok "WebSocket handshake through Apache (upgrade=websocket)" || bad "Apache WebSocket: HTTP $code"
    row binary websocket tcp "$state" "-" "101 through nginx and Apache"
fi

if [ -n "${RUNWAY_E2E_OCTANE_ROOT:-}" ]; then
    FP_TC=$(get "app?site_id=$SITE_ID" | jexpr "([t['id'] for t in d['data']['toolchains']['php'] if t['id'].startswith('frankenphp-')] or [''])[0]")
    for listen in tcp unix; do
        echo "== Laravel Octane ($listen, $RUNWAY_E2E_OCTANE_ROOT)"
        if [ -z "$FP_TC" ]; then bad "Octane: no FrankenPHP toolchain"; break; fi
        post app/save "{\"site_id\": $SITE_ID, \"enabled\": false, \"runtime\": \"php\", \"toolchain\": \"$FP_TC\", \"appRoot\": \"$RUNWAY_E2E_OCTANE_ROOT\", \"listen\": \"$listen\", \"mode\": \"web\", \"staticPaths\": [], \"healthPath\": \"/up\"}" >/dev/null
        defaults=$(get "app?site_id=$SITE_ID" | jexpr "json.dumps(d['data']['defaults']['php']['variants']['$listen|$FP_TC'])")
        start=$(echo "$defaults" | jexpr "d['start_cmd']")
        body=$(echo "$defaults" | jexpr "json.dumps({'site_id': $SITE_ID, 'enabled': True, 'buildCmd': d['build_cmd'], 'startCmd': d['start_cmd']})")
        since=$(( $(date +%s) - 5 ))
        post app/save "$body" >/dev/null
        state=$(wait_deploy "$since")
        sleep 3
        st=$(get "app/status?site_id=$SITE_ID" | jexpr "(d['data'].get('listener'), d['data'].get('health'))")
        code=$(dock exec "$CONTAINER" curl -sk -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/up")
        caddy=$(dock exec "$CONTAINER" sh -c "grep -c '^.admin off' '$HOME_DIR/$RUNWAY_E2E_OCTANE_ROOT/.runway/Caddyfile'")
        if [ "$state" = "succeeded" ] && [ "$st" = "('ok', 'healthy')" ] && [ "$code" = "200" ] && [ "$caddy" = "1" ] && echo "$start" | grep -q 'octane:frankenphp --caddyfile=.runway/Caddyfile'; then
            ok "Octane $listen: /up 200 through nginx, admin endpoint off"
        else
            bad "Octane $listen: deploy=$state status=$st /up=$code caddy=$caddy start=$start"
        fi
        if [ "$listen" = tcp ]; then
            port=$(get "app/status?site_id=$SITE_ID" | jexpr "d['data']['port']")
            dock exec "$CONTAINER" sh -c "ss -ltn | grep -q '127.0.0.1:$port ' && ! ss -ltn | grep -qE '(\*|0.0.0.0|\[::\]):$port '" \
                && ok "Octane tcp listens on 127.0.0.1:$port only" || bad "Octane listener: $(dock exec "$CONTAINER" sh -c "ss -ltn | grep $port")"
        fi
        row php "$listen" "$FP_TC" "$state" "-" "Laravel Octane /up $code"
    done
fi

post app/save "{\"site_id\": $SITE_ID, \"enabled\": false}" >/dev/null
dock exec "$CONTAINER" rm -rf "$HOME_DIR/$APP_ROOT"
echo
printf '%-8s %-5s %-22s %-8s %-9s %s\n' RUNTIME LISTEN TOOLCHAIN DEPLOY HEALTH RESPONSE
printf '%s' "$MATRIX"
echo "== $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
