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
# The sample, fetch, path mode, worker and maxAppsPerSubscription tests use a scratch subdomain
# SUB.DOMAIN (created when missing, deleted at the end unless KEEP_SUB=1), so the application
# of SITE_ID is never modified unless RUNWAY_SMOKE_DEPLOY=1. The fetch test serves a copy of
# the SITE_ID binary ($APP_ROOT/bin/app) with python3 -m http.server inside the container and
# creates the helper's test-only switch /etc/runway/allow-insecure-fetch while it runs.
# RUNWAY_SMOKE_SUB=0 skips everything that needs the subdomain.
#
# Environment: CONTAINER (grt-plesk), PANEL (http://localhost:18880), SITE_ID (1),
# DOMAIN (gotest.local), APP_ROOT (apps/gotest.local), GO_VERSION (1.27.4), SUB (runway-smoke),
# FETCH_PORT (18765), PYTHON.
set -u
CONTAINER=${CONTAINER:-grt-plesk}
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
cleanup() {
    if [ -n "$MAX_APPS_BEFORE" ]; then post settings "{\"maxAppsPerSubscription\": $MAX_APPS_BEFORE}" >/dev/null; fi
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
APP=$(get "app?site_id=$SITE_ID")
check "app" "d['status'] == 'success' and d['data']['domain']['id'] == $SITE_ID and 'config' in d['data'] and d['data']['config']['mode'] in ('web', 'path', 'worker')" "$APP"
check "app: defaults and toolchains for every runtime" "sorted(d['data']['defaults']) == $KEYS and sorted(d['data']['toolchains']) == $KEYS and all('start_cmd' in v for v in d['data']['defaults'].values())" "$APP"
check "app/status" "d['status'] == 'success' and 'service' in d['data']" "$(get "app/status?site_id=$SITE_ID")"
check "app/logs" "d['status'] == 'success' and d['data']['kind'] == 'deploy'" "$(get "app/logs?site_id=$SITE_ID&kind=deploy&lines=20")"
check "unknown domain is rejected" "d['status'] == 'error'" "$(get 'app?site_id=999999')"

echo "== mutations and validation"
check "POST without CSRF token is rejected" "d.get('status') != 'success'" \
    "$(curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' -d '{"portMin": 20000}' "$API/settings")"
check "GET on a mutation is rejected" "d['status'] == 'error'" "$(get toolchain)"
check "GET on app/sample is rejected" "d['status'] == 'error'" "$(get "app/sample?site_id=$SITE_ID")"
check "settings: errors keyed by field" "d['status'] == 'error' and 'portMax' in d['errors']" "$(post settings '{"portMin": 30000, "portMax": 29000}')"
check "toolchain: unknown runtime" "d['status'] == 'error' and 'runtime' in d['errors']" "$(post toolchain '{"runtime": "cobol", "op": "install", "version": "1"}')"
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

    echo "== worker (listen none)"
    out=$(post app/save "{\"site_id\": $SUB_ID, \"listen\": \"none\"}")
    check_or_helper "app/save: listen none makes a worker without web configuration" \
        "d['status'] == 'success' and d['data']['config']['mode'] == 'worker' and d['data']['config']['listen'] == 'none'" \
        "$out" "Invalid listen mode"
    if [ "$(echo "$out" | jexpr "d['status']")" = "success" ]; then
        wait_conf_gone -q 'Runway' "$CONF/nginx.conf" && ok "nginx: no proxy for a worker" || bad "nginx config of a worker still proxies"
        check "overview: a worker has no port and no app URL" "[(a['port'], a['appUrl'], a['mode']) for a in d['data']['apps'] if a['domainId'] == $SUB_ID] == [(None, None, 'worker')]" "$(get overview)"
        check "app/save: mode web gives the worker a listener again" "d['status'] == 'success' and d['data']['config']['listen'] in ('tcp', 'unix') and d['data']['config']['mode'] == 'web'" \
            "$(post app/save "{\"site_id\": $SUB_ID, \"mode\": \"web\", \"listen\": \"none\"}")"
    fi

    check "app/remove of the scratch app" "d['status'] == 'success'" "$(post app/remove "{\"site_id\": $SUB_ID}")"
fi


echo "== $PASS passed, $FAIL failed, $SKIP skipped"
[ "$FAIL" -eq 0 ]
