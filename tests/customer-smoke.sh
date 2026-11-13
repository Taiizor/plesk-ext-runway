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
# The document root (Plesk's setting) needs Plesk's own "Hosting settings management" permission
# (manage_phosting) as well: checked without it and, granted for the check, with it; both the
# permission and the document root are restored (cleanup restores the document root through
# Plesk's CLI whenever the run stops in between).
# Environment: CONTAINER (runway-plesk), PANEL (http://localhost:18880), CUSTOMER (cust1),
# DOMAIN (gotest.local), SITE_ID (1), PYTHON.
set -u
CONTAINER=${CONTAINER:-runway-plesk}
PANEL=${PANEL:-http://localhost:18880}
CUSTOMER=${CUSTOMER:-cust1}
DOMAIN=${DOMAIN:-gotest.local}
SITE_ID=${SITE_ID:-1}
PERMISSION=ext_permission_runway_manage_runway_apps
HOSTING_PERMISSION=manage_phosting
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
hosting() { dock exec "$CONTAINER" plesk bin subscription_settings --update "$DOMAIN" -$HOSTING_PERMISSION "$1" >/dev/null; }
# docroot_info DOMAIN: the document root that Plesk stores for a domain (absolute path).
docroot_info() { dock exec "$CONTAINER" plesk bin site --info "$1" 2>/dev/null | sed -n 's/^--WWW-Root--: *//p' | tr -d '\r'; }

BEFORE=$(dock exec "$CONTAINER" plesk bin subscription_settings --info "$DOMAIN" | awk -v p="$PERMISSION" '$1 == p {print $2}' | tr -d '\r')
HOSTING_BEFORE=$(dock exec "$CONTAINER" plesk bin subscription_settings --info "$DOMAIN" | awk -v p="$HOSTING_PERMISSION" '$1 == p {print $2}' | tr -d '\r')
# The document root before the customer changed it: set before the change, cleared after a verified restore.
DR_BEFORE=""
DR_HOME=""
cleanup() {
    if [ -n "$DR_BEFORE" ]; then
        dock exec "$CONTAINER" plesk bin site --update "$DOMAIN" -www-root "/$DR_BEFORE" >/dev/null 2>&1 \
            || echo "cleanup: the document root of $DOMAIN could not be restored to $DR_BEFORE"
    fi
    [ -n "$DR_HOME" ] && dock exec "$CONTAINER" rm -rf "$DR_HOME/apps/$DOMAIN/runway-customer-docroot"
    [ -n "$HOSTING_BEFORE" ] && hosting "$HOSTING_BEFORE"
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
check "app: only the document roots of the customer's webspace" \
    "d['data']['domain']['documentRoot'] == 'httpdocs' and all(r['domain'] == '$DOMAIN' or r['domain'].endswith('.$DOMAIN') for r in d['data']['documentRoots'])" "$APP"
# The customer panel's navigation (PLACE_HOSTING_PANEL_TABS) and the icons of a domain row; the
# page carries both as JSON ("extNavButton_runway_<n>", "extensionButton_<place>_<n>_runway").
WEB=$(curl -s -L -b "$JAR" "$PANEL/smb/web/view")
[ "$(echo "$WEB" | grep -o 'extNavButton_runway_[0-9]*' | sort -u | wc -l)" -eq 1 ] && ok "customer panel: Runway in the navigation, once (permission granted)" \
    || bad "customer panel: Runway entries in the navigation of /smb/web/view: $(echo "$WEB" | grep -o 'extNavButton_runway_[0-9]*' | sort -u | tr '\n' ' ')"
if [ "$(echo "$APP" | jexpr "d['data']['configured'] and d['data']['config']['enabled']")" = "True" ]; then
    echo "$WEB" | grep -o '"extensionButton_[0-9]*_[0-9]*_runway"[^}]*' | grep 'header\.svg' | grep -q "site_id=$SITE_ID\"" \
        && ok "customer panel: Runway's icon in the row of $DOMAIN" || bad "customer panel: no Runway icon for $DOMAIN"
fi
check "zero-downtime deployments: not offered to customers while the server setting is off (default)" \
    "d['status'] == 'success' and d['data']['zeroDowntimeAllowed'] is False" "$(get "app?site_id=$SITE_ID")"
check "a customer cannot turn zero-downtime deployments on (field error)" "d['status'] == 'error' and list(d['errors']) == ['zeroDowntime']" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"zeroDowntime\": true}")"
check "customer cannot change admin-only limits" \
    "d['status'] == 'success' and d['data']['limits'] == $(echo "$APP" | jexpr "json.dumps(d['data']['limits'])")" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"memoryMb\": 1, \"cpuPercent\": 1, \"tasks\": 1}")"

echo "== document root (Plesk's permission \"Hosting settings management\")"
hosting false
APP=$(get "app?site_id=$SITE_ID")
DR_CURRENT=$(echo "$APP" | jexpr "d['data']['domain']['documentRoot']")
DR_HOME=$(echo "$APP" | jexpr "d['data']['domain']['home']")
# Restored by cleanup from here on: the refused attempts below must not leave a changed document
# root behind either, should a regression let one through (writing the same value is harmless).
DR_BEFORE=$DR_CURRENT
check "app: without the hosting settings permission the document root is read-only" \
    "d['status'] == 'success' and d['data']['documentRootAllowed'] is False and d['data']['domain']['documentRoot'] == 'httpdocs'" "$APP"
check "app/save: a customer without the hosting settings permission cannot change the document root (field error)" \
    "d['status'] == 'error' and list(d['errors']) == ['documentRoot'] and 'hosting settings' in d['errors']['documentRoot'][0]" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"apps/$DOMAIN/runway-customer-docroot\"}")"
check "app/save: the unchanged document root is not a change (accepted without the permission)" \
    "d['status'] == 'success' and d['data']['documentRoot'] == '$DR_CURRENT' and d['data']['documentRootChanged'] is False" \
    "$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_CURRENT\"}")"
check "app/save with a document root for an unknown domain is refused" "d['status'] == 'error'" \
    "$(post app/save "{\"site_id\": 999999, \"documentRoot\": \"httpdocs\"}")"
[ "$(docroot_info "$DOMAIN")" = "$DR_HOME/$DR_CURRENT" ] && ok "the document root is unchanged" || bad "document root: $(docroot_info "$DOMAIN")"
hosting true
check "app: with the hosting settings permission the document root is editable" "d['data']['documentRootAllowed'] is True" "$(get "app?site_id=$SITE_ID")"
out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"apps/$DOMAIN/runway-customer-docroot\"}")
check "app/save: with the permission the customer changes the document root (the application is left alone)" \
    "d['status'] == 'success' and d['data']['documentRoot'] == 'apps/$DOMAIN/runway-customer-docroot' and d['data']['documentRootChanged'] is True and d['data']['job'] is None" "$out"
[ "$(docroot_info "$DOMAIN")" = "$DR_HOME/apps/$DOMAIN/runway-customer-docroot" ] && ok "Plesk stores the customer's document root" || bad "document root: $(docroot_info "$DOMAIN")"
out=$(post app/save "{\"site_id\": $SITE_ID, \"documentRoot\": \"$DR_BEFORE\"}")
if [ "$(echo "$out" | jexpr "d['status'] == 'success'")" = "True" ] && [ "$(docroot_info "$DOMAIN")" = "$DR_HOME/$DR_BEFORE" ]; then
    ok "document root restored by the customer ($DR_BEFORE)"
    DR_BEFORE=""
else
    bad "restoring the document root: $out"
fi
dock exec "$CONTAINER" rm -rf "$DR_HOME/apps/$DOMAIN/runway-customer-docroot"
hosting "${HOSTING_BEFORE:-false}"

echo "== permission revoked"
permission false
check "app: access denied without the permission" "d['status'] == 'error' and 'denied' in str(d['errors']).lower()" "$(get "app?site_id=$SITE_ID")"
check "app/control: access denied without the permission" "d['status'] == 'error'" \
    "$(post app/control "{\"site_id\": $SITE_ID, \"op\": \"restart\"}")"
check "overview: the domain is no longer listed" "d['status'] == 'success' and $SITE_ID not in [a['domainId'] for a in d['data']['apps']]" "$(get overview)"
WEB=$(curl -s -L -b "$JAR" "$PANEL/smb/web/view")
if ! echo "$WEB" | grep -q '"headerCustomButtons"'; then
    bad "customer panel: /smb/web/view did not load the domain list"
else
    echo "$WEB" | grep -q 'extNavButton_runway_[0-9]' && bad "customer panel: Runway in the navigation without the permission" \
        || ok "customer panel: no Runway entry in the navigation without the permission"
    echo "$WEB" | grep -o '"extensionButton_[0-9]*_[0-9]*_runway"[^}]*' | grep -q 'header\.svg' && bad "customer panel: Runway icon without the permission" \
        || ok "customer panel: no Runway icon in the domain list without the permission"
fi

echo "== $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
