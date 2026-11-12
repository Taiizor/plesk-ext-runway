#!/bin/bash
# Customer access checks of the JSON API (docs/DESIGN.md sections 4 and 6). Runs on the
# development machine against the local Plesk test container: logs in as the customer CUSTOMER
# (owner of DOMAIN) with a one-time login link and checks what the customer can do with and
# without the "Runway applications management" permission of the subscription.
#
#   bash tests/customer-smoke.sh
#
# The permission is granted for the checks and restored to its previous value at the end. The
# application of DOMAIN is only read and restarted (app/control restart), never reconfigured.
# Environment: CONTAINER (runway-plesk), PANEL (http://localhost:18880), CUSTOMER (cust1),
# DOMAIN (gotest.local), SITE_ID (1), PYTHON.
set -u
CONTAINER=${CONTAINER:-runway-plesk}
PANEL=${PANEL:-http://localhost:18880}
CUSTOMER=${CUSTOMER:-cust1}
DOMAIN=${DOMAIN:-gotest.local}
SITE_ID=${SITE_ID:-1}
PERMISSION=ext_permission_runway_manage_runway_apps
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
check() {
    if [ "$(echo "$3" | jexpr "$2")" = "True" ]; then ok "$1"; else bad "$1: $(echo "$3" | head -c 300)"; fi
}
permission() { dock exec "$CONTAINER" plesk bin subscription_settings --update "$DOMAIN" -$PERMISSION "$1" >/dev/null; }

BEFORE=$(dock exec "$CONTAINER" plesk bin subscription_settings --info "$DOMAIN" | awk -v p="$PERMISSION" '$1 == p {print $2}' | tr -d '\r')
cleanup() {
    [ -n "$BEFORE" ] && permission "$BEFORE"
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "== login as $CUSTOMER (permission granted)"
permission true
LINK=$(dock exec "$CONTAINER" plesk bin admin --get-login-link -user "$CUSTOMER" -relative-url | tr -d '\r')
curl -s -c "$JAR" -b "$JAR" -L "$PANEL$LINK" -o /dev/null
PAGE=$(curl -s -c "$JAR" -b "$JAR" "$PANEL/modules/runway/index.php/domain?site_id=$SITE_ID")
TOKEN=$(echo "$PAGE" | grep -o 'id="forgery_protection_token" content="[^"]*"' | sed 's/.*content="//;s/"$//')
[ -n "$TOKEN" ] && echo "$PAGE" | grep -q '<div id="runway"></div>' && ok "customer opens the domain page" || { bad "customer login / domain page"; exit 1; }

check "context: not an administrator" "d['status'] == 'success' and d['data']['isAdmin'] is False" "$(get context)"
check "overview: only the customer's domains, no server facts" \
    "d['status'] == 'success' and d['data']['server'] is None and $SITE_ID in [a['domainId'] for a in d['data']['apps']] and all(a['domain'] == '$DOMAIN' or a['domain'].endswith('.$DOMAIN') for a in d['data']['apps'])" \
    "$(get overview)"
APP=$(get "app?site_id=$SITE_ID")
check "app: readable with the permission, no limits editing, no usage lists" \
    "d['status'] == 'success' and d['data']['isAdmin'] is False and all(not isinstance(t, dict) or 'in_use' not in t for v in d['data']['toolchains'].values() for t in v)" "$APP"
for path in toolchains settings "job?job=admin" update; do
    check "admin endpoint $path is refused" "d['status'] == 'error'" "$(get "$path")"
done
check "POST update/check is refused (access denied)" "d['status'] == 'error' and 'denied' in str(d['errors']).lower()" "$(post update/check '{}')"
check "POST update/install is refused (access denied)" "d['status'] == 'error' and 'denied' in str(d['errors']).lower()" "$(post update/install '{"version": "9.9.9-1"}')"
check "POST settings is refused" "d['status'] == 'error'" "$(post settings '{"portMin": 20000}')"
check "POST toolchain is refused" "d['status'] == 'error'" "$(post toolchain '{"runtime": "go", "op": "remove", "version": "1.27.4"}')"
check "POST build-deps is refused" "d['status'] == 'error'" "$(post build-deps '{}')"
check "unknown site id is refused" "d['status'] == 'error'" "$(get 'app?site_id=999999')"
if [ "$(echo "$APP" | jexpr "d['data']['configured'] and d['data']['config']['enabled']")" = "True" ]; then
    check "app/control restart works with the permission" "d['status'] == 'success'" \
        "$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\"}")"
    sleep 2
    post app/control "{\"site_id\": $SITE_ID, \"op\": \"stop\"}" >/dev/null
    check "app/control stop: the customer sees it stopped" "d['status'] == 'success' and d['data']['stopped'] is True" "$(get "app/status?site_id=$SITE_ID")"
    check "overview: stopped state for the customer" "[a['state'] for a in d['data']['apps'] if a['domainId'] == $SITE_ID] == ['stopped']" "$(get overview)"
    post app/control "{\"site_id\": $SITE_ID, \"op\": \"start\"}" >/dev/null
    for _ in $(seq 1 15); do
        [ "$(get "app/status?site_id=$SITE_ID" | jexpr "d['data'].get('listener')")" = "ok" ] && break
        sleep 2
    done
    check "app/control start: running again" "d['status'] == 'success' and d['data']['stopped'] is False and d['data'].get('listener') in ('ok', 'worker')" "$(get "app/status?site_id=$SITE_ID")"
fi
check "overview: application links come from appUrl" "all('appUrl' in a for a in d['data']['apps'])" "$(get overview)"
check "zero-downtime deployments: not offered to customers while the server setting is off (default)" \
    "d['status'] == 'success' and d['data']['zeroDowntimeAllowed'] is False" "$(get "app?site_id=$SITE_ID")"
check "a customer cannot turn zero-downtime deployments on (field error)" "d['status'] == 'error' and list(d['errors']) == ['zeroDowntime']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": true}")"
check "customer cannot change admin-only limits" \
    "d['status'] == 'success' and d['data']['limits'] == $(echo "$APP" | jexpr "json.dumps(d['data']['limits'])")" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"memoryMb\": 1, \"cpuPercent\": 1, \"tasks\": 1}")"

echo "== permission revoked"
permission false
check "app: access denied without the permission" "d['status'] == 'error' and 'denied' in str(d['errors']).lower()" "$(get "app?site_id=$SITE_ID")"
check "app/control: access denied without the permission" "d['status'] == 'error'" \
    "$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\"}")"
check "overview: the domain is no longer listed" "d['status'] == 'success' and $SITE_ID not in [a['domainId'] for a in d['data']['apps']]" "$(get overview)"

echo "== $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
