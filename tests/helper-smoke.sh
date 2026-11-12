#!/bin/bash
# Regression checks for the root helper. Run INSIDE a Plesk test server as root, e.g.:
#   docker cp tests/helper-smoke.sh runway-plesk:/root/ && docker exec runway-plesk bash /root/helper-smoke.sh
# Requirements: the extension is installed, Go 1.27.4 is installed through Runway (Bun, Python and
# FrankenPHP are installed by this script; it needs network access) and the
# subscription gotest.local (system user gotestuser) exists. Uses domain id 999 (a fake id) so
# it does not interfere with apps configured in the panel. The panel's Reconcile (scheduled every
# 10 minutes and run on domain events) removes helper apps of domains it does not know, so the
# script creates the root-only flag /var/lib/runway/pause-reconcile while it runs (Reconcile
# honours it for at most one hour) and removes it on exit.
# The self-update section checks the built-in updater against a mock release server; with
# RUNWAY_SMOKE_SELF_UPDATE=1 it also upgrades the installed extension to a repackaged
# release+1 (irreversible: Plesk refuses the downgrade afterwards, so only on throw-away servers).
set -u
H=/opt/runway/bin/runway-helper
ID=999
PAUSE_FLAG=/var/lib/runway/pause-reconcile
touch "$PAUSE_FLAG"
# The self-update section starts a mock release server and sets the update test switches.
UPD_PID=""
UPD_DIR=""
cleanup() {
    rm -f "$PAUSE_FLAG" /etc/runway/update-source /etc/runway/allow-insecure-fetch
    [ -n "$UPD_PID" ] && kill "$UPD_PID" 2>/dev/null
    # The update cache holds mock releases (and a recorded failure of a mock version) once the
    # self-update section has started: never leave it behind, also not after an aborted run.
    [ -n "$UPD_DIR" ] && rm -rf "$UPD_DIR" /var/lib/runway/cache/update.json /var/lib/runway/cache/update
}
trap cleanup EXIT
USER_NAME=gotestuser
HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
APP=$HOME_DIR/apps/smoke
GO_VERSION=${GO_VERSION:-1.27.4}
PASS=0
FAIL=0

ok()   { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad()  { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }
call() { echo "$2" | "$H" "$1"; }
field() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d$1)"; }
jexpr() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

base() {
    cat <<EOF
"domain_id": $ID, "domain": "smoke.test", "sysuser": "$USER_NAME", "app_root": "apps/smoke",
"runtime": "go", "toolchain": "$GO_VERSION", "build_cmd": "go build -o bin/app .", "start_cmd": "./bin/app",
"port": 0, "port_range": [29900, 29999], "enabled": true, "auto_deploy": true, "build_timeout": 600, "limits": {}
EOF
}

expect_reject() {
    local name=$1 extra=$2
    local out
    out=$(call app-apply "{$(base), $extra}")
    if [ "$(echo "$out" | field "['ok']")" = "False" ]; then ok "rejects $name"; else bad "accepted $name: $out"; fi
}

wait_job() {
    local job=$1 state=""
    for _ in $(seq 1 100); do
        state=$(call job-status "{\"job\":\"$job\"}" | field "['state']")
        case "$state" in queued|running) sleep 2 ;; *) break ;; esac
    done
    echo "$state"
}

echo "== validation"
expect_reject "newline in start command" '"start_cmd": "./app\nExecStartPre=+/bin/touch /pwned"'
expect_reject "path traversal" '"app_root": "../../../root"'
expect_reject "root system user" '"sysuser": "root"'
expect_reject "reserved env PORT" '"env": {"PORT": "80"}'
expect_reject "newline in env value" '"env": {"A": "x\nB=y"}'
expect_reject "bad env key" '"env": {"A-B": "x"}'
expect_reject "privileged port" '"port": 80'
expect_reject "toolchain traversal" '"toolchain": "1.2/../../etc"'
expect_reject "loader variable LD_PRELOAD" '"env": {"LD_PRELOAD": "/var/www/vhosts/x/evil.so"}'
expect_reject "loader variable LD_AUDIT" '"env": {"LD_AUDIT": "/tmp/a.so"}'
expect_reject "loader variable GCONV_PATH" '"env": {"GCONV_PATH": "/tmp"}'
expect_reject "loader variable GLIBC_TUNABLES" '"env": {"GLIBC_TUNABLES": "glibc.malloc.check=3"}'
call app-apply "{$(base), \"env\": {\"LD_PRELOAD\": \"/tmp/x.so\"}}" | grep -q 'put it in the start command' && ok "loader variables: error tells where to set them" || bad "loader variable message"
[ ! -e /pwned ] && ok "no injected file" || bad "/pwned exists"
call job-status '{"job":"../../etc/passwd"}' | grep -q '"ok": false' && ok "rejects bad job name" || bad "job name"

echo "== contract (docs/DESIGN.md section 7)"
[ "$(call runtimes '{}' | jexpr "[r['key'] for r in d['runtimes']][:2] == ['go', 'rust'] and all('version_re' in r for r in d['runtimes'])")" = "True" ] && ok "runtimes metadata" || bad "runtimes metadata"
[ "$(call toolchains '{}' | jexpr "'$GO_VERSION' in [t['id'] for t in d['runtimes']['go']['installed']] and 'cc' in d['build_deps']")" = "True" ] && ok "toolchains lists Go $GO_VERSION" || bad "toolchains"
[ "$(call releases '{"runtime": "go"}' | jexpr "isinstance(d['available'], list) and 'error' in d")" = "True" ] && ok "releases shape" || bad "releases shape"
call releases '{"runtime": "nope"}' | grep -q '"ok": false' && ok "releases rejects unknown runtime" || bad "releases runtime"
call toolchain-install '{"runtime": "binary", "version": "1"}' | grep -q '"ok": false' && ok "binary has no toolchain" || bad "binary toolchain"
call toolchain-install '{"runtime": "go", "version": "1.2/../../x"}' | grep -q '"ok": false' && ok "rejects bad Go version" || bad "Go version"

echo "== apply + deploy"
mkdir -p "$APP" && cat > "$APP/go.mod" <<'EOF'
module smoke

go 1.22
EOF
cat > "$APP/main.go" <<'EOF'
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
)

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "smoke %s", os.Getenv("SMOKE"))
	})
	if sock := os.Getenv("RUNWAY_SOCKET"); sock != "" {
		ln, err := net.Listen("unix", sock)
		if err != nil {
			panic(err)
		}
		http.Serve(ln, nil)
	}
	http.ListenAndServe(os.Getenv("LISTEN_ADDR"), nil)
}
EOF
chown -R "$USER_NAME":psacln "$HOME_DIR/apps"

out=$(call app-apply "{$(base), \"env\": {\"SMOKE\": \"a \\\"b\\\" \$HOME %h\"}, \"start\": false}")
PORT=$(echo "$out" | field "['port']")
[ "$(echo "$out" | field "['ok']")" = "True" ] && ok "apply (port $PORT)" || bad "apply: $out"
[ "$(stat -c %a /etc/runway/env/$ID.env)" = "600" ] && ok "env file is 0600" || bad "env file mode"
grep -q 'bin/app' /etc/systemd/system/runway-app-$ID.service && bad "start command leaked into unit" || ok "unit has no user text"

call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && ok "build + start" || bad "deploy: $(tail -5 /var/lib/runway/jobs/deploy-$ID.log)"
body=$(curl -s "http://127.0.0.1:$PORT/")
[ "$body" = 'smoke a "b" $HOME %h' ] && ok "env value passed literally" || bad "env value: $body"
[ "$(ps -o user= -p "$(systemctl show -p MainPID --value runway-app-$ID)")" = "$USER_NAME" ] && ok "runs as $USER_NAME" || bad "service user"

echo "== trigger files"
pid1=$(systemctl show -p MainPID --value runway-app-$ID)
runuser -u "$USER_NAME" -- touch "$APP/tmp/restart.txt"
sleep 5
pid2=$(systemctl show -p MainPID --value runway-app-$ID)
[ "$pid1" != "$pid2" ] && [ "$pid2" != "0" ] && ok "restart trigger" || bad "restart trigger ($pid1 -> $pid2)"

echo "== hijack detection (TCP)"
systemctl stop runway-app-$ID
runuser -u nobody -- python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', $PORT)); s.listen(); time.sleep(20)" &
SQUAT=$!
sleep 2
st=$(call app-status "{\"domain_id\": $ID}" | field "['listener']")
[ "$st" = "foreign" ] && ok "foreign listener detected" || bad "listener state: $st"
call app-deploy "{\"domain_id\": $ID, \"build\": false}" >/dev/null
[ "$(wait_job deploy-$ID)" = "failed" ] && ok "deploy refuses a hijacked port" || bad "deploy did not fail on hijack"
kill $SQUAT 2>/dev/null; wait $SQUAT 2>/dev/null
grep -q "SocketBindAllow=tcp:$PORT" /etc/systemd/system/runway-app-$ID.service && ok "SocketBindAllow in unit" || echo "SKIP  SocketBindAllow (systemd < 249)"

echo "== unix socket mode"
out=$(call app-apply "{$(base), \"listen\": \"unix\", \"build_cmd\": \"\"}")
[ "$(echo "$out" | field "['ok']")" = "True" ] && ok "apply unix mode" || bad "apply unix: $out"
SOCK=/run/runway/$ID/app.sock
for _ in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done
[ "$(stat -c '%U:%G %a' /run/runway/$ID)" = "$USER_NAME:psaserv 2750" ] && ok "socket dir owner/mode" || bad "socket dir: $(stat -c '%U:%G %a' /run/runway/$ID)"
[ "$(call app-status "{\"domain_id\": $ID}" | field "['listener']")" = "ok" ] && ok "socket listener ok" || bad "socket listener"
[ "$(runuser -u nginx -- curl -s --unix-socket $SOCK http://x/)" = 'smoke a "b" $HOME %h' ] && ok "nginx user can connect" || bad "nginx cannot connect"
runuser -u nobody -- curl -s --max-time 3 --unix-socket $SOCK http://x/ >/dev/null 2>&1 && bad "other users can connect" || ok "other users cannot connect"

echo "== no root-privileged unit lines, socket directory, tmpfiles (security review C0, C7)"
priv=$(grep -lE '^[[:space:]]*Exec[A-Za-z]*[[:space:]]*=[[:space:]]*[-@:+!]*[+!]' /etc/systemd/system/runway-*.service 2>/dev/null)
[ -z "$priv" ] && ok "no rendered unit has an Exec line with a + or ! prefix" || bad "root Exec lines in: $priv"
[ "$(grep -v '^#' /etc/tmpfiles.d/runway-$ID.conf 2>/dev/null)" = "d /run/runway/$ID 2750 $USER_NAME psaserv -" ] && ok "tmpfiles entry for the socket directory" || bad "tmpfiles entry: $(cat /etc/tmpfiles.d/runway-$ID.conf 2>&1)"
grep -q '^d /run/runway 0755 root root -' /etc/tmpfiles.d/runway.conf && ok "tmpfiles entry for /run/runway" || bad "tmpfiles base: $(cat /etc/tmpfiles.d/runway.conf 2>&1)"
grep -qE '^(PORT|HOST|LISTEN_ADDR)=' /etc/runway/env/$ID.env && bad "unix mode exports PORT/HOST/LISTEN_ADDR" || ok "unix mode exports no PORT/HOST/LISTEN_ADDR"
grep -q "^RUNWAY_SOCKET=\"$SOCK\"" /etc/runway/env/$ID.env && grep -q '^RUNWAY_LISTEN="unix"' /etc/runway/env/$ID.env && ok "unix mode exports RUNWAY_SOCKET and RUNWAY_LISTEN=unix" || bad "unix env: $(grep RUNWAY_ /etc/runway/env/$ID.env)"
systemctl stop runway-app-$ID
rm -rf /run/runway/$ID
call app-action "{\"domain_id\": $ID, \"action\": \"start\"}" >/dev/null
for _ in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done
[ "$(stat -c '%U:%G %a' /run/runway/$ID 2>&1)" = "$USER_NAME:psaserv 2750" ] && [ "$(call app-status "{\"domain_id\": $ID}" | field "['listener']")" = "ok" ] && ok "start recreates a removed socket directory (root, not the unit)" || bad "after removing /run/runway/$ID: $(stat -c '%U:%G %a' /run/runway/$ID 2>&1)"
systemctl stop runway-app-$ID
rm -rf /run/runway/$ID
systemd-tmpfiles --create /etc/tmpfiles.d/runway-$ID.conf
[ "$(stat -c '%U:%G %a' /run/runway/$ID 2>&1)" = "$USER_NAME:psaserv 2750" ] && ok "systemd-tmpfiles recreates the socket directory (boot)" || bad "tmpfiles create: $(stat -c '%U:%G %a' /run/runway/$ID 2>&1)"
systemctl start runway-app-$ID
for _ in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done

echo "== tampered socket path (security review E1)"
runuser -u "$USER_NAME" -- ln -sfn /run/runway/elsewhere/app.sock "$SOCK"
st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(d['listener'], d['tampered'], d['stopped'])")
[ "$st" = "('tampered', True, True)" ] && ok "a symlinked socket path is reported as tampered" || bad "tampered status: $st"
[ ! -L "$SOCK" ] && ok "the symbolic link was removed" || bad "symlink still there"
[ "$(systemctl is-active runway-app-$ID)" != "active" ] && [ "$(systemctl is-enabled runway-app-$ID)" = "disabled" ] && ok "the service was stopped and disabled" || bad "service after tampering: $(systemctl is-active runway-app-$ID) $(systemctl is-enabled runway-app-$ID)"
journalctl -u runway-app-$ID --no-pager -n 20 | grep -q 'socket path was tampered' && ok "the application log explains the stop" || bad "no journal note"
runuser -u "$USER_NAME" -- ln -sfn /run/runway/elsewhere/app.sock "$SOCK"
call apps-list '{}' >/dev/null
[ ! -L "$SOCK" ] && ok "apps-list (scheduled reconcile) removes a re-created link" || bad "apps-list left the link"
call app-action "{\"domain_id\": $ID, \"action\": \"start\"}" >/dev/null
for _ in $(seq 1 20); do [ -S "$SOCK" ] && break; sleep 1; done
st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(d['listener'], d['tampered'], d['stopped'])")
[ "$st" = "('ok', False, False)" ] && ok "Start clears the tampered flag and runs the app again" || bad "after start: $st"

echo "== stop persists (security review C42)"
call app-action "{\"domain_id\": $ID, \"action\": \"stop\"}" >/dev/null
[ "$(systemctl is-active runway-app-$ID)" != "active" ] && [ "$(systemctl is-enabled runway-app-$ID)" = "disabled" ] && [ "$(call app-status "{\"domain_id\": $ID}" | field "['stopped']")" = "True" ] && ok "stop disables the service and remembers it" || bad "stop: $(systemctl is-enabled runway-app-$ID)"
call app-deploy "{\"domain_id\": $ID, \"build\": false}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && grep -q 'it was not started' /var/lib/runway/jobs/deploy-$ID.log && [ "$(systemctl is-active runway-app-$ID)" != "active" ] && ok "a deployment keeps a stopped app stopped" || bad "deploy of a stopped app: $(tail -3 /var/lib/runway/jobs/deploy-$ID.log)"
[ "$(call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d['title_key'], d['title'])")" = "('deploy_restart_skipped', 'Restart skipped (application stopped)')" ] && ok "the restart of a stopped app is titled 'Restart skipped'" || bad "title: $(call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d.get('title_key'), d.get('title'))")"
call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d['title_key'], d['title'])")" = "('deploy_build_only', 'Build (application stopped)')" ] && [ "$(systemctl is-active runway-app-$ID)" != "active" ] && ok "a build of a stopped app is titled 'Build (application stopped)'" || bad "build title: $(call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d.get('title_key'), d.get('title'))")"
call app-apply "{$(base), \"listen\": \"unix\", \"build_cmd\": \"\"}" >/dev/null
sleep 2
[ "$(systemctl is-active runway-app-$ID)" != "active" ] && ok "re-applying (reconcile) keeps it stopped" || bad "app-apply started a stopped app"
call app-deploy "{\"domain_id\": $ID, \"build\": false, \"start\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(systemctl is-active runway-app-$ID)" = "active" ] && [ "$(call app-status "{\"domain_id\": $ID}" | field "['stopped']")" = "False" ] && [ "$(call job-status "{\"job\": \"deploy-$ID\"}" | field "['title_key']")" = "deploy_restart" ] && ok "Build & restart (start: true) starts it again" || bad "deploy with start: $(tail -3 /var/lib/runway/jobs/deploy-$ID.log)"
grep -q "^TimeoutStartSec=1500$" /etc/systemd/system/runway-deploy-$ID.service && ok "deploy unit timeout covers fetch + build (C10)" || bad "TimeoutStartSec: $(grep TimeoutStartSec /etc/systemd/system/runway-deploy-$ID.service)"
grep -q '^After=network-online.target mariadb.service mysql.service postgresql.service$' /etc/systemd/system/runway-app-$ID.service && ok "app unit starts after local databases (C41)" || bad "After= line"

echo "== bounded inspection of huge application roots (security review C1)"
runuser -u "$USER_NAME" -- bash -c "mkdir -p '$HOME_DIR/apps/smoke-many' && cd '$HOME_DIR/apps/smoke-many' && seq 1 20000 | xargs touch"
t0=$(date +%s)
st=$(call app-inspect "{\"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-many\"}" | jexpr "(d['ok'], d['entry_count'], d['more'], len(d['entries']))")
[ "$st" = "(True, 10000, True, 80)" ] && [ $(( $(date +%s) - t0 )) -lt 30 ] && ok "20000 files: counted up to 10000, 80 names, within the deadline" || bad "inspect of 20000 files: $st"
rm -rf "$HOME_DIR/apps/smoke-many"

echo "== app-page"
[ "$(call app-page "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke\", \"runtime\": \"go\"}" | jexpr "d['defaults']['go']['start_cmd'] == './bin/app' and d['inspect']['go']['module'] == 'smoke' and 'go' in d['toolchains']")" = "True" ] && ok "app-page defaults + inspect" || bad "app-page"

echo "== symlink safety"
runuser -u "$USER_NAME" -- ln -sfn /root "$HOME_DIR/apps/evil"
call app-inspect "{\"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/evil\"}" | grep -q '"ok": false' && ok "cannot inspect /root via symlink" || bad "symlink inspect"
rm -f "$HOME_DIR/apps/evil"

echo "== adapter metadata (docs/DESIGN.md section 5.1)"
[ "$(call runtimes '{}' | jexpr "sorted(r['key'] for r in d['runtimes']) == sorted(['go','rust','bun','java','dotnet','python','ruby','php','binary']) and all(set(['key','label','toolchain','version_re','hint','docs_url','default_listen','supports_build','install_help','detected_only']) <= set(r) for r in d['runtimes'])")" = "True" ] && ok "all runtimes with full metadata" || bad "runtime metadata"
[ "$(call runtimes '{}' | jexpr "dict((r['key'], r['toolchain']) for r in d['runtimes']) == {'go':'managed','rust':'managed','bun':'managed','java':'managed','dotnet':'managed','python':'managed','ruby':'detected','php':'detected','binary':'none'}")" = "True" ] && ok "toolchain kinds" || bad "toolchain kinds"
for rt in bun java dotnet python php; do
    re=$(call runtimes '{}' | jexpr "[r['version_re'] for r in d['runtimes'] if r['key'] == '$rt'][0]")
    res=$(call releases "{\"runtime\": \"$rt\"}" | RE="$re" python3 -c "
import json, os, re, sys
d = json.load(sys.stdin)
ids = [a['id'] for a in d['available']]
if d['error']:
    print('error: ' + d['error'])
elif ids and all(re.match(os.environ['RE'], i) for i in ids):
    print('ok %d, newest %s' % (len(ids), ids[0]))
else:
    print('bad ids %s' % ids[:5])")
    case "$res" in ok*) ok "$rt release list parsed ($res)" ;; error:*) echo "SKIP  $rt release list ($res)" ;; *) bad "$rt release list: $res" ;; esac
done
[ "$(call releases '{"runtime": "ruby"}' | jexpr "d['available'] == [] and d['install_help'] != ''")" = "True" ] && ok "ruby is detected (install help, no downloads)" || bad "ruby releases"
call toolchain-install '{"runtime": "php", "version": "plesk-8.4"}' | grep -q '"ok": false' && ok "Plesk PHP cannot be installed by Runway" || bad "php plesk install"
call toolchain-install '{"runtime": "java", "version": "21; rm -rf /"}' | grep -q '"ok": false' && ok "rejects bad Java version" || bad "Java version"
call toolchain-remove '{"runtime": "ruby", "version": "system"}' | grep -q '"ok": false' && ok "detected Ruby cannot be removed" || bad "ruby remove"

echo "== toolchain installs (bun, python, frankenphp)"
FP=$(call releases '{"runtime": "php"}' | jexpr "(d['available'] or [{'id': 'frankenphp-1.13.5'}])[0]['id']")
for spec in "bun latest" "python 3.13" "php $FP"; do
    set -- $spec
    call toolchain-install "{\"runtime\": \"$1\", \"version\": \"$2\"}" >/dev/null
    [ "$(wait_job admin)" = "succeeded" ] && ok "install $1 $2" || bad "install $1 $2: $(tail -3 /var/lib/runway/jobs/admin.log)"
done
PY=$(call toolchains '{}' | jexpr "([t['id'] for t in d['runtimes']['python']['installed'] if t['id'].startswith('3.13.')] or ['3.13'])[0]")
[ -z "$(find /opt/runway \( ! -uid 0 -o ! -gid 0 -o -perm -o+w \) ! -type l | head -1)" ] && ok "toolchains are root-owned, not world-writable" || bad "toolchain ownership: $(find /opt/runway \( ! -uid 0 -o -perm -o+w \) ! -type l | head -3)"

echo "== validation of listen/mode/paths"
expect_reject "listen udp" '"listen": "udp"'
expect_reject "path mode without mount path" '"mode": "path", "mount_path": ""'
expect_reject "static path traversal" '"static_paths": ["/a/../b"]'
expect_reject "too many static paths" "\"static_paths\": [$(seq -s, -f '"/p%g"' 1 21)]"
expect_reject "health path with space" '"health_path": "/a b"'
expect_reject "bun toolchain injection" '"runtime": "bun", "toolchain": "latest/../../x"'

# sample_app <runtime> <toolchain> <listen>: app-sample, app-apply with the sample's defaults, build + restart, request
sample_app() {
    local rt=$1 tc=$2 listen=$3 root=apps/smoke-$1 out payload body st
    rm -rf "${HOME_DIR:?}/$root"
    out=$(call app-sample "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"$root\", \"runtime\": \"$rt\", \"listen\": \"$listen\", \"toolchain\": \"$tc\"}")
    [ "$(echo "$out" | field "['ok']")" = "True" ] || { bad "$rt sample ($listen): $out"; return 1; }
    payload=$(echo "$out" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(json.dumps({'domain_id': $ID, 'domain': 'smoke.test', 'sysuser': '$USER_NAME', 'app_root': '$root', 'runtime': '$rt',
    'toolchain': '$tc', 'listen': '$listen', 'build_cmd': d['defaults']['build_cmd'], 'start_cmd': d['defaults']['start_cmd'],
    'port': 0, 'port_range': [29900, 29999], 'enabled': True, 'auto_deploy': False, 'build_timeout': 900, 'limits': {},
    'health_path': '/health', 'start': False}))")
    out=$(call app-apply "$payload")
    [ "$(echo "$out" | field "['ok']")" = "True" ] || { bad "$rt apply ($listen): $out"; return 1; }
    PORT=$(echo "$out" | field "['port']")
    call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
    [ "$(wait_job deploy-$ID)" = "succeeded" ] || { bad "$rt $tc deploy ($listen): $(tail -4 /var/lib/runway/jobs/deploy-$ID.log)"; return 1; }
    if [ "$listen" = unix ]; then body=$(curl -s --max-time 5 --unix-socket /run/runway/$ID/app.sock http://x/)
    else body=$(curl -s --max-time 5 "http://127.0.0.1:$PORT/"); fi
    st=$(call app-status "{\"domain_id\": $ID}" | jexpr "d['listener'] + ' ' + d['health']")
    case "$body" in
        "Hello from"*) [ "$st" = "ok healthy" ] && ok "$rt $tc sample, $listen: ${body% on Runway*} ($st)" || bad "$rt $tc ($listen) status: $st" ;;
        *) bad "$rt $tc sample ($listen) answered: $body" ;;
    esac
}

echo "== sample apps (app-sample + deploy, tcp and unix)"
sample_app bun latest tcp
sample_app bun latest unix
sample_app python "$PY" tcp
sample_app python "$PY" unix
grep -q "^VIRTUAL_ENV=\"$HOME_DIR/apps/smoke-python/.venv\"" /etc/runway/env/$ID.env && grep -q '^UV_PYTHON_DOWNLOADS="never"' /etc/runway/env/$ID.env && ok "python env (VIRTUAL_ENV, uv settings)" || bad "python env file"
sample_app php "$FP" tcp
sample_app php "$FP" unix
sample_app php plesk-8.4 tcp
# The plesk/plesk image ships no Ruby: the system Ruby sample runs only where one is installed.
if [ -x /usr/bin/ruby ]; then sample_app ruby system tcp; else echo "SKIP  ruby sample (no system Ruby installed)"; fi
for rt in java dotnet; do
    # Large toolchains: tested when installed (toolchain-install {"runtime": "java", "version": "21"} / {"runtime": "dotnet", "version": "10.0"}).
    tc=$(call toolchains '{}' | jexpr "([t['id'] for t in d['runtimes']['$rt']['installed']] or [''])[0]")
    if [ -n "$tc" ]; then sample_app $rt "$tc" tcp; sample_app $rt "$tc" unix; else echo "SKIP  $rt samples (no toolchain installed)"; fi
done
sample_app go "$GO_VERSION" unix
call toolchain-remove "{\"runtime\": \"go\", \"version\": \"$GO_VERSION\"}" | grep -q 'used by' && ok "toolchain in use cannot be removed" || bad "removed a toolchain in use"
call app-sample "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-go\", \"runtime\": \"go\", \"listen\": \"tcp\"}" | grep -q 'not empty' && ok "sample refuses a non-empty app root" || bad "sample overwrote files"
[ "$(call app-sample "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-go\", \"runtime\": \"go\", \"listen\": \"tcp\", \"force\": true}" | field "['ok']")" = "True" ] && ok "sample overwrites with force" || bad "sample force"
[ "$(stat -c %U "$HOME_DIR/apps/smoke-go/main.go")" = "$USER_NAME" ] && ok "sample files belong to $USER_NAME" || bad "sample file owner"
[ "$(call app-page "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-python\", \"runtime\": \"python\", \"listen\": \"unix\"}" | jexpr "d['inspect']['python'] is not None and d['defaults']['python']['start_cmd'] == '.venv/bin/python app.py' and d['defaults']['bun']['start_cmd'].startswith('bun run') and set(d['toolchains']) >= set(['bun', 'python', 'php', 'ruby'])")" = "True" ] && ok "app-page detects python and returns defaults" || bad "app-page python"

echo "== project-aware defaults (security review C13, C14, C16, C17, C39, Octane C2)"
# page_default ROOT RUNTIME LISTEN TOOLCHAIN EXPR: app-page of a prepared directory, EXPR on d = defaults[RUNTIME]
page_default() {
    call app-page "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"$1\", \"runtime\": \"$2\", \"listen\": \"$3\", \"toolchain\": \"$4\"}" \
        | python3 -c "import json,sys; d=json.load(sys.stdin)['defaults']['$2']; print($5)"
}
as_user() { runuser -u "$USER_NAME" -- bash -c "$1"; }
as_user "mkdir -p '$HOME_DIR/apps/smoke-def/java' '$HOME_DIR/apps/smoke-def/rust' '$HOME_DIR/apps/smoke-def/rack' '$HOME_DIR/apps/smoke-def/rails/bin' '$HOME_DIR/apps/smoke-def/puma/config' '$HOME_DIR/apps/smoke-def/octane'"
as_user "cd '$HOME_DIR/apps/smoke-def' && printf 'package demo;\npublic class App { public static void main(String[] a) {} }\n' > java/App.java \
    && printf '[package]\nname = \"myservice\"\n[[bin]]\nname = \"server\"\npath = \"src/main.rs\"\n' > rust/Cargo.toml \
    && printf 'source \"https://rubygems.org\"\ngem \"rack\"\ngem \"rackup\"\n' > rack/Gemfile && echo 'run ->(e) { [200, {}, [\"x\"]] }' > rack/config.ru \
    && printf 'source \"https://rubygems.org\"\ngem \"rails\"\n' > rails/Gemfile && touch rails/bin/rails rails/config.ru \
    && printf 'source \"https://rubygems.org\"\ngem \"puma\"\n' > puma/Gemfile && touch puma/config.ru puma/config/puma.rb \
    && printf '{\"require\": {\"laravel/framework\": \"^13.0\", \"laravel/octane\": \"^2.24\"}}' > octane/composer.json && touch octane/artisan"
[ "$(page_default apps/smoke-def/java java tcp "" "(d['build_cmd'], d['start_cmd'])")" = "('javac -d build App.java', 'java -XX:MaxRAMPercentage=75 -cp build demo.App')" ] && ok "Java: any top-level .java with a main method is detected" || bad "java defaults: $(page_default apps/smoke-def/java java tcp "" "d['start_cmd']")"
[ "$(page_default apps/smoke-def/rust rust tcp "" "d['start_cmd']")" = "./target/release/server" ] && ok "Rust: the [[bin]] of src/main.rs names the binary" || bad "rust defaults: $(page_default apps/smoke-def/rust rust tcp "" "d['start_cmd']")"
# Without an installed Ruby the page answers with the generic variant ("unix|") only.
[ "$(page_default apps/smoke-def/rack ruby unix system "(d['start_cmd'].startswith('bundle exec rackup'), d['variants'].get('unix|system', d['variants']['unix|'])['unix_supported'])")" = "(True, False)" ] && ok "Ruby: rackup is TCP only (unix_supported false)" || bad "rackup defaults: $(page_default apps/smoke-def/rack ruby unix system "d['variants']")"
[ "$(page_default apps/smoke-def/rails ruby tcp system "d['build_cmd'].endswith('bundle install && SECRET_KEY_BASE_DUMMY=1 bundle exec rails assets:precompile')")" = "True" ] && ok "Ruby: Rails assets through bundle exec" || bad "rails defaults: $(page_default apps/smoke-def/rails ruby tcp system "d['build_cmd']")"
[ "$(page_default apps/smoke-def/puma ruby unix system "d['start_cmd']")" = "bundle exec puma -C config/puma.rb -e production" ] && ok "Ruby: config/puma.rb decides the bind (no -b)" || bad "puma defaults: $(page_default apps/smoke-def/puma ruby unix system "d['start_cmd']")"
[ "$(page_default apps/smoke-def/octane php tcp "$FP" "d['variants']['tcp|$FP']['start_cmd']")" = 'php artisan octane:frankenphp --caddyfile=.runway/Caddyfile --port=$PORT --admin-port=$PORT' ] && ok "PHP: Laravel Octane uses Runway's Caddyfile" || bad "octane defaults: $(page_default apps/smoke-def/octane php tcp "$FP" "d['variants']")"
out=$(call app-apply "$(python3 -c "import json; print(json.dumps({'domain_id': $ID, 'domain': 'smoke.test', 'sysuser': '$USER_NAME', 'app_root': 'apps/smoke-def/octane', 'runtime': 'php', 'toolchain': '$FP', 'listen': 'tcp', 'build_cmd': '', 'start_cmd': 'php artisan octane:frankenphp --caddyfile=.runway/Caddyfile --port=\$PORT --admin-port=\$PORT', 'port_range': [29900, 29999], 'enabled': True, 'auto_deploy': False, 'build_timeout': 600, 'limits': {}}))")")
CADDY=$HOME_DIR/apps/smoke-def/octane/.runway/Caddyfile
grep -q '^	admin off$' "$CADDY" && grep -q '^http://:{$PORT} {$' "$CADDY" && grep -q '^	bind 127.0.0.1$' "$CADDY" && [ "$(stat -c %U "$CADDY")" = "$USER_NAME" ] && ok "Octane Caddyfile: admin off, bound to 127.0.0.1:\$PORT, written as $USER_NAME" || bad "Octane Caddyfile: $out $(head -25 "$CADDY" 2>&1)"
call app-apply "{$(base), \"enabled\": false}" >/dev/null
rm -rf "$HOME_DIR/apps/smoke-def"

echo "== system Ruby: Bundler and gems (security review C4, C11)"
if [ -x /usr/bin/ruby ]; then
    as_user "printf 'source \"https://rubygems.org\"\ngem \"rack\"\n' > '$HOME_DIR/apps/smoke-ruby/Gemfile'"
    payload=$(python3 -c "import json; print(json.dumps({'domain_id': $ID, 'domain': 'smoke.test', 'sysuser': '$USER_NAME', 'app_root': 'apps/smoke-ruby', 'runtime': 'ruby', 'toolchain': 'system', 'listen': 'tcp', 'build_cmd': 'bundle install', 'start_cmd': 'ruby app.rb', 'port_range': [29900, 29999], 'enabled': True, 'auto_deploy': False, 'build_timeout': 600, 'limits': {}, 'health_path': '/', 'start': False}))")
    call app-apply "$payload" >/dev/null
    grep -q '^GEM_PATH=' /etc/runway/env/$ID.env && bad "GEM_PATH hides the bundled gems" || ok "no GEM_PATH (RubyGems keeps the bundled gems)"
    call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
    [ "$(wait_job deploy-$ID)" = "succeeded" ] && grep -q 'Bundle complete' /var/lib/runway/jobs/deploy-$ID.log && ok "system Ruby: bundle install works (versioned Bundler on PATH)" || bad "system Ruby bundle: $(tail -4 /var/lib/runway/jobs/deploy-$ID.log)"
else
    echo "SKIP  system Ruby (not installed)"
fi

echo "== toolchain channels (security review C3)"
JAVA_BUILD=$(call toolchains '{}' | jexpr "([t['id'] for t in d['runtimes']['java']['installed']] or [''])[0]")
if [ -n "$JAVA_BUILD" ]; then
    MAJOR=${JAVA_BUILD%%[.+]*}
    call app-apply "{$(base), \"runtime\": \"java\", \"toolchain\": \"$MAJOR\", \"enabled\": false, \"build_cmd\": \"\", \"start_cmd\": \"java -version\"}" >/dev/null
    call toolchain-remove "{\"runtime\": \"java\", \"version\": \"$JAVA_BUILD\"}" | grep -q 'used by' && ok "a build that the channel id $MAJOR may use cannot be removed" || bad "removed Java $JAVA_BUILD used through $MAJOR"
    call app-apply "{$(base), \"enabled\": false}" >/dev/null
else
    echo "SKIP  Java channel check (no Java toolchain)"
fi

echo "== trigger file touched during a deployment (security review C9)"
call app-apply "{$(base), \"build_cmd\": \"echo round >> rounds.txt && sleep 6 && go build -o bin/app .\", \"start\": false}" >/dev/null
as_user "rm -f '$APP/rounds.txt'; mkdir -p '$APP/tmp'"
sleep 1
as_user "touch '$APP/tmp/deploy.txt'"
sleep 3
as_user "touch '$APP/tmp/deploy.txt'"
for _ in $(seq 1 60); do
    sleep 2
    [ "$(systemctl is-active runway-deploy-$ID.service)" = "inactive" ] && [ "$(wc -l < "$APP/rounds.txt" 2>/dev/null)" -ge 2 ] && break
done
[ "$(wc -l < "$APP/rounds.txt" 2>/dev/null)" = "2" ] && ok "a touch during the build runs a second round" || bad "rounds after two touches: $(cat "$APP/rounds.txt" 2>&1)"

echo "== start limit recovery (security review C41)"
call app-apply "{$(base), \"build_cmd\": \"\", \"start_cmd\": \"exit 1\"}" >/dev/null
for _ in $(seq 1 40); do
    sleep 2
    [ "$(systemctl show -p ActiveState --value runway-app-$ID)" = "failed" ] && break
done
[ "$(call apps-list '{}' | jexpr "[a['start_limit_hit'] for a in d['apps'] if a['domain_id'] == $ID][0]")" = "True" ] && ok "apps-list reports that systemd gave up (Reconcile restarts such apps)" || bad "start limit: $(systemctl show -p ActiveState,Result,NRestarts runway-app-$ID | xargs)"
call app-action "{\"domain_id\": $ID, \"action\": \"recover\"}" >/dev/null
sleep 1
[ "$(systemctl show -p ActiveState --value runway-app-$ID)" != "failed" ] && ok "recover resets the start limit and starts it again" || bad "recover did not restart it"
call app-action "{\"domain_id\": $ID, \"action\": \"stop\"}" >/dev/null
call app-action "{\"domain_id\": $ID, \"action\": \"recover\"}" | grep -q 'is stopped' && ok "recover never starts a stopped application" || bad "recover started a stopped app"
call app-apply "{$(base), \"build_cmd\": \"\", \"enabled\": false, \"resume\": true}" >/dev/null

echo "== a stopped deployment says why (security review C10)"
call app-apply "{$(base), \"build_cmd\": \"sleep 60\", \"start\": false}" >/dev/null
call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
for _ in $(seq 1 20); do [ "$(call job-status "{\"job\": \"deploy-$ID\"}" | field "['state']")" = "running" ] && break; sleep 1; done
sleep 2
systemctl stop runway-deploy-$ID.service
st=$(call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d['state'], 'was stopped' in (d.get('message') or ''))")
[ "$st" = "('failed', True)" ] && grep -q 'ERROR: The deployment was stopped' /var/lib/runway/jobs/deploy-$ID.log && ok "SIGTERM marks the deployment failed with the reason" || bad "stopped deployment: $st $(tail -2 /var/lib/runway/jobs/deploy-$ID.log)"
call app-apply "{$(base), \"enabled\": false}" >/dev/null

echo "== upgrade of an old state (security review C0, C43)"
OLD=997
python3 - "$USER_NAME" "$HOME_DIR" <<'PYEOF'
import json, sys
user, home = sys.argv[1], sys.argv[2]
state = {"version": 1, "domain_id": 997, "domain": "old.test", "sysuser": user, "app_root": "apps/smoke",
         "app_dir": home + "/apps/smoke", "runtime": "go", "toolchain": "", "build_cmd": "", "start_cmd": "./bin/app",
         "env": {"LD_PRELOAD": "/tmp/evil.so", "KEEP": "1"}, "port": 29997, "port_range": [29900, 29999],
         "enabled": False, "suspended": False, "auto_deploy": False, "build_timeout": 600, "limits": {},
         "build_limits": {}, "listen": "unix", "mode": "web", "mount_path": "", "static_paths": [], "health_path": ""}
with open("/var/lib/runway/apps/997.json", "w") as fh:
    json.dump(state, fh)
PYEOF
chmod 600 /var/lib/runway/apps/$OLD.json
printf '[Service]\nUser=%s\nEnvironmentFile=/etc/runway/env/%s.env\nExecStartPre=+/usr/bin/install -d -o %s -g psaserv -m 2750 /run/runway/%s\nExecStart=/bin/bash -c ${RUNWAY_START_CMD}\n' "$USER_NAME" $OLD "$USER_NAME" $OLD > /etc/systemd/system/runway-app-$OLD.service
out=$(call reapply-all '{}')
echo "$out" | grep -q "#$OLD: removed LD_PRELOAD" && ok "reapply-all drops a stored LD_PRELOAD and reports it" || bad "reapply-all: $out"
grep -q '^ExecStartPre=+' /etc/systemd/system/runway-app-$OLD.service && bad "old root Exec line kept" || ok "the old unit was re-rendered without root Exec lines"
grep -q '^KEEP="1"' /etc/runway/env/$OLD.env && ! grep -q 'LD_PRELOAD' /etc/runway/env/$OLD.env && ok "other variables are kept" || bad "env after upgrade: $(cat /etc/runway/env/$OLD.env)"
[ "$(stat -c '%U:%G %a' /run/runway/$OLD 2>&1)" = "$USER_NAME:psaserv 2750" ] && [ -f /etc/tmpfiles.d/runway-$OLD.conf ] && ok "upgrade prepares the socket directory and its tmpfiles entry" || bad "socket dir after upgrade: $(stat -c '%U:%G %a' /run/runway/$OLD 2>&1)"
call app-remove "{\"domain_id\": $OLD}" >/dev/null
[ ! -e /etc/tmpfiles.d/runway-$OLD.conf ] && [ ! -e /run/runway/$OLD ] && ok "app-remove deletes the tmpfiles entry and the socket directory" || bad "leftovers of #$OLD"

echo "== worker mode and path mode"
out=$(call app-apply "{$(base), \"listen\": \"none\", \"mode\": \"web\", \"build_cmd\": \"\", \"start_cmd\": \"exec sleep 600\", \"health_path\": \"/x\"}")
[ "$(echo "$out" | field "['state']['mode']")" = "worker" ] && ok "listen none is a worker" || bad "worker apply: $out"
call app-deploy "{\"domain_id\": $ID, \"build\": false}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && ok "worker deploy without listener check" || bad "worker deploy: $(tail -3 /var/lib/runway/jobs/deploy-$ID.log)"
st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(d['listen_mode'], d['mode'], d['listener'], d['health_path'], d['service']['sub_state'])")
[ "$st" = "('none', 'worker', 'worker', '', 'running')" ] && ok "worker status fields" || bad "worker status: $st"
grep -q '^RUNWAY_LISTEN="none"' /etc/runway/env/$ID.env && ok "RUNWAY_LISTEN=none in env file" || bad "RUNWAY_LISTEN"
out=$(call app-apply "{$(base), \"mode\": \"path\", \"mount_path\": \"/api\", \"static_paths\": [\"/assets\", \"/img/x\", \"/assets\"], \"start\": false}")
st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(d['mode'], d['mount_path'], d['static_paths'], d['health'])")
[ "$st" = "('path', '/api', ['/assets', '/img/x'], 'unknown')" ] && ok "path mode status fields" || bad "path mode: $st $out"

echo "== fetch mode"
SRV=/root/runway-fetch-srv
rm -rf $SRV && mkdir -p $SRV/pkg/static
sample_app binary "" tcp
cp "$HOME_DIR/apps/smoke-binary/app" $SRV/app && rm -f "$HOME_DIR/apps/smoke-binary/app"
echo "hello static" > $SRV/pkg/static/hello.txt && tar -czf $SRV/bundle.tar.gz -C $SRV/pkg static
SUM=$(sha256sum $SRV/app | cut -d' ' -f1)
touch /etc/runway/allow-insecure-fetch
python3 -m http.server 18999 --bind 127.0.0.1 --directory $SRV >/dev/null 2>&1 &
HTTPD=$!
sleep 1
call app-deploy "{\"domain_id\": $ID, \"fetch\": {\"url\": \"http://127.0.0.1:18999/app\", \"sha256\": \"$(printf '0%.0s' $(seq 64))\"}}" >/dev/null
[ "$(wait_job deploy-$ID)" = "failed" ] && grep -q 'SHA-256 mismatch' /var/lib/runway/jobs/deploy-$ID.log && [ ! -e "$HOME_DIR/apps/smoke-binary/app" ] && ok "fetch rejects a wrong checksum" || bad "fetch checksum: $(tail -3 /var/lib/runway/jobs/deploy-$ID.log)"
call app-deploy "{\"domain_id\": $ID, \"fetch\": {\"url\": \"http://127.0.0.1:18999/app\", \"sha256\": \"$SUM\", \"extract\": false}}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(stat -c '%U %a' "$HOME_DIR/apps/smoke-binary/app")" = "$USER_NAME 750" ] && ok "fetch saves ./app as $USER_NAME (0750)" || bad "fetch binary: $(tail -4 /var/lib/runway/jobs/deploy-$ID.log)"
case "$(curl -s --max-time 5 "http://127.0.0.1:$PORT/")" in "Hello from"*) ok "fetched binary serves after restart" ;; *) bad "fetched binary does not answer" ;; esac
call app-deploy "{\"domain_id\": $ID, \"fetch\": {\"url\": \"http://127.0.0.1:18999/bundle.tar.gz\", \"extract\": true}}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(stat -c %U "$HOME_DIR/apps/smoke-binary/static/hello.txt" 2>/dev/null)" = "$USER_NAME" ] && ok "fetch extracts a .tar.gz as $USER_NAME" || bad "fetch extract: $(tail -4 /var/lib/runway/jobs/deploy-$ID.log)"
rm -f /etc/runway/allow-insecure-fetch
call app-deploy "{\"domain_id\": $ID, \"fetch\": {\"url\": \"http://127.0.0.1:18999/app\"}}" | grep -q 'Only https' && ok "fetch refuses http:// URLs" || bad "fetch accepted http://"
call app-deploy "{\"domain_id\": $ID, \"fetch\": {\"url\": \"https://127.0.0.1:8443/\"}}" >/dev/null
[ "$(wait_job deploy-$ID)" = "failed" ] && grep -q 'non-public address' /var/lib/runway/jobs/deploy-$ID.log && ok "fetch refuses loopback addresses" || bad "fetch loopback: $(tail -2 /var/lib/runway/jobs/deploy-$ID.log)"
kill $HTTPD 2>/dev/null; wait $HTTPD 2>/dev/null
rm -rf $SRV

echo "== reconcile pause flag"
[ "$(call apps-list '{}' | field "['reconcile_paused']")" = "True" ] && ok "apps-list reports the reconcile pause" || bad "reconcile pause not reported"
touch -d '2 hours ago' "$PAUSE_FLAG"
[ "$(call apps-list '{}' | field "['reconcile_paused']")" = "False" ] && ok "a stale pause flag is ignored" || bad "stale pause flag honoured"
touch "$PAUSE_FLAG"

echo "== self-update (built-in updater against a mock release source)"
# A mock "GitHub" on a free local port serves one release per scenario under
# /<scenario>/releases/latest (+ /<scenario>/download/<tag>/{runway-X.Y.Z-R.zip,SHA256SUMS});
# a file <path>.redirect makes it answer <path> with a 302 to the URL in that file.
# The test switches /etc/runway/update-source (the API URL) and allow-insecure-fetch (http://)
# point the helper at it; a new source URL starts with an empty cache, so each scenario is
# checked once. RUNWAY_SMOKE_SELF_UPDATE=1 also upgrades the installed extension for real.
META=/usr/local/psa/admin/plib/modules/runway/meta.xml
UPD_CACHE=/var/lib/runway/cache/update.json
UPD_SOURCE_FLAG=/etc/runway/update-source
UPD_DIR=$(mktemp -d /root/runway-update-XXXXXX)
mkdir -p "$UPD_DIR/www"
UPD_PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
UPD_URL=http://127.0.0.1:$UPD_PORT
INSTALLED=$(python3 -c "import sys, xml.etree.ElementTree as E; r = E.parse(sys.argv[1]).getroot(); print('%s-%s' % (r.findtext('version').strip(), r.findtext('release').strip()))" "$META")
IFS=.- read -r V_MAJ V_MIN V_PATCH V_REL <<< "$INSTALLED"
NEWER=$V_MAJ.$V_MIN.$((V_PATCH + 1))

expect() { # expect NAME EXPR JSON: EXPR on d = the decoded JSON
    if [ "$(echo "$3" | jexpr "$2" 2>/dev/null)" = "True" ]; then ok "$1"; else bad "$1: $(echo "$3" | head -c 500)"; fi
}
upd_source() { echo "$UPD_URL/$1/releases/latest" > "$UPD_SOURCE_FLAG"; }
cat > "$UPD_DIR/server.py" <<'PYEOF'
import http.server, os, sys

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        redirect = self.translate_path(self.path) + ".redirect"
        if os.path.isfile(redirect):
            with open(redirect) as fh:
                location = fh.read().strip()
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        http.server.SimpleHTTPRequestHandler.do_GET(self)

    def log_message(self, *args):
        pass

os.chdir(sys.argv[2])
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
PYEOF
start_mock() {
    python3 "$UPD_DIR/server.py" "$UPD_PORT" "$UPD_DIR/www" >/dev/null 2>&1 &
    UPD_PID=$!
    for _ in $(seq 1 25); do curl -s -o /dev/null "$UPD_URL/" && return 0; sleep 0.2; done
    return 1
}
# mock_release SCENARIO TAG VERSION RELEASE [draft] [pre] [badsum] [evil] [dotdot] [nosums] [redirect] [zip=PATH]
# evil: the zip URL is on another host; dotdot: below the source, but with ".." segments that
# leave the release's directory; redirect: SHA256SUMS answers with a relative 302 (followed),
# the zip with a 302 to ftp:// (refused).
mock_release() {
    python3 - "$UPD_DIR/www" "$UPD_URL" "$@" <<'PYEOF'
import hashlib, json, os, shutil, sys, zipfile
root, origin, name, tag, version, release = sys.argv[1:7]
flags = sys.argv[7:]
base = os.path.join(root, name)
download = os.path.join(base, "download", tag)
os.makedirs(download, exist_ok=True)
os.makedirs(os.path.join(base, "releases"), exist_ok=True)
zip_name = "runway-%s-%s.zip" % (version, release)
package = os.path.join(download, zip_name)
source = [flag[4:] for flag in flags if flag.startswith("zip=")]
if source:
    shutil.copyfile(source[0], package)
else:
    meta = ('<?xml version="1.0" encoding="utf-8"?>\n<module>\n    <id>runway</id>\n'
            '    <version>%s</version>\n    <release>%s</release>\n</module>\n' % (version, release))
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("meta.xml", meta)
with open(package, "rb") as fh:
    data = fh.read()
digest = "0" * 64 if "badsum" in flags else hashlib.sha256(data).hexdigest()
sums = os.path.join(download, "SHA256SUMS")
with open(sums + (".real" if "redirect" in flags else ""), "w") as fh:
    fh.write("%s  %s\n%s  runway.zip\n" % (digest, zip_name, digest))
if "redirect" in flags:
    with open(sums + ".redirect", "w") as fh:
        fh.write("/%s/download/%s/SHA256SUMS.real\n" % (name, tag))
    with open(package + ".redirect", "w") as fh:
        fh.write("ftp://127.0.0.1:9/%s\n" % zip_name)
url = "%s/%s/download/%s/" % (origin, name, tag)
zip_url = url + zip_name
if "evil" in flags:
    zip_url = "https://example.com/" + zip_name
elif "dotdot" in flags:
    zip_url = "%s../../../elsewhere/download/%s/%s" % (url, tag, zip_name)
assets = [{"name": zip_name, "size": len(data), "browser_download_url": zip_url},
          {"name": "runway.zip", "size": len(data), "browser_download_url": url + "runway.zip"}]
if "nosums" not in flags:
    assets.append({"name": "SHA256SUMS", "size": 200, "browser_download_url": url + "SHA256SUMS"})
release_json = {"tag_name": tag, "draft": "draft" in flags, "prerelease": "pre" in flags,
                "html_url": "%s/%s/releases/tag/%s" % (origin, name, tag), "published_at": "2026-11-12T10:00:00Z",
                "body": "Release notes the helper does not keep", "assets": assets}
with open(os.path.join(base, "releases", "latest"), "w") as fh:
    json.dump(release_json, fh)
PYEOF
}

start_mock || bad "mock release server on port $UPD_PORT"
rm -f "$UPD_CACHE"
expect "update-status reads the installed version from meta.xml ($INSTALLED)" \
    "d['ok'] and d['installed'] == '$INSTALLED' and d['latest'] is None and d['update_source'] is None" "$(call update-status '{}')"
upd_source none
call update-check '{"force": true}' | grep -q 'not a valid https URL' && ok "update source: http:// only with the insecure test switch" || bad "http:// update source accepted"
touch /etc/runway/allow-insecure-fetch
[ "$(call info '{}' | field "['update_source']")" = "$UPD_URL/none/releases/latest" ] && ok "info reports the update source" || bad "info: update_source"
chmod 0666 "$UPD_SOURCE_FLAG"
[ "$(call info '{}' | field "['update_source']")" = "None" ] && ok "a group/world-writable update source is ignored" || bad "writable update source honoured"
chmod 0644 "$UPD_SOURCE_FLAG"
expect "HTTP 404: no release published, no error" \
    "d['ok'] and d['checked'] is True and d['latest'] is None and d['error'] is None and d['available'] is False" "$(call update-check '{"force": true}')"

mock_release newer "v$NEWER" "$NEWER" 1
upd_source newer
expect "a newer release is detected ($NEWER-1)" \
    "d['checked'] is True and d['available'] is True and d['latest']['full'] == '$NEWER-1' and d['latest']['tag'] == 'v$NEWER' and d['latest']['html_url'].startswith('$UPD_URL/') and d['error'] is None" \
    "$(call update-check '{"force": true}')"
grep -q 'Release notes' "$UPD_CACHE" && bad "the cache keeps the release notes" || ok "the release notes are not cached"
[ "$(stat -c '%U %a' "$UPD_CACHE")" = "root 600" ] && ok "update cache is root 0600" || bad "update cache mode: $(stat -c '%U %a' "$UPD_CACHE")"
expect "a forced check within a minute answers from the cache" "d['checked'] is False and d['latest']['full'] == '$NEWER-1'" "$(call update-check '{"force": true}')"
expect "a scheduled check within 12 hours answers from the cache" "d['checked'] is False and d['available'] is True" "$(call update-check '{}')"
# Age the cache, so any check would use the network, then stop the mock: a network attempt of
# update-status would show up as an error or a new checked_at.
CHECKED_AT=$(python3 - "$UPD_CACHE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    cache = json.load(fh)
cache["checked_epoch"] = 0
with open(sys.argv[1], "w") as fh:
    json.dump(cache, fh)
print(cache["checked_at"])
PYEOF
)
kill "$UPD_PID" 2>/dev/null; wait "$UPD_PID" 2>/dev/null
expect "update-status needs no network" \
    "d['ok'] and d['available'] is True and d['latest']['full'] == '$NEWER-1' and d['error'] is None and d['checked_at'] == '$CHECKED_AT'" \
    "$(call update-status '{}')"
start_mock || bad "mock release server restarted"
call update-install "{\"version\": \"$NEWER-2\"}" | grep -q 'is not the available update' && ok "update-install refuses a version that is not the available one" || bad "update-install accepted $NEWER-2"
call update-install '{"version": "latest"}' | grep -q 'Invalid version' && ok "update-install validates the version" || bad "update-install version validation"

mock_release draft "v$NEWER" "$NEWER" 1 draft
upd_source draft
expect "a draft release is ignored" "d['latest'] is None and d['available'] is False and d['error'] is None" "$(call update-check '{"force": true}')"
call update-install "{\"version\": \"$NEWER-1\"}" | grep -q 'No newer Runway release' && ok "update-install refuses without an available update" || bad "update-install without an available update"
mock_release pre "v$NEWER" "$NEWER" 1 pre
upd_source pre
expect "a prerelease is ignored" "d['latest'] is None and d['available'] is False and d['error'] is None" "$(call update-check '{"force": true}')"
mock_release evil "v$NEWER" "$NEWER" 1 evil
upd_source evil
expect "an asset URL outside the source is rejected" "d['latest'] is None and 'unexpected download URL' in d['error']" "$(call update-check '{"force": true}')"
mock_release dotdot "v$NEWER" "$NEWER" 1 dotdot
upd_source dotdot
expect "an asset URL with '..' segments is rejected" "d['latest'] is None and 'unexpected download URL' in d['error']" "$(call update-check '{"force": true}')"
mock_release nosums "v$NEWER" "$NEWER" 1 nosums
upd_source nosums
expect "a release without SHA256SUMS is rejected" "d['latest'] is None and 'SHA256SUMS' in d['error']" "$(call update-check '{"force": true}')"
mock_release mismatch "v$NEWER-3" "$NEWER" 1
upd_source mismatch
expect "a package that does not match the tag is rejected" "d['latest'] is None and 'matches its tag' in d['error']" "$(call update-check '{"force": true}')"

mock_release same "v$INSTALLED" "$V_MAJ.$V_MIN.$V_PATCH" "$V_REL"
upd_source same
expect "the installed version is not offered" "d['latest']['full'] == '$INSTALLED' and d['available'] is False" "$(call update-check '{"force": true}')"
call update-install "{\"version\": \"$INSTALLED\"}" | grep -q 'is not newer' && ok "update-install refuses the installed version" || bad "update-install accepted $INSTALLED"
mock_release older "v0.9.0" 0.9.0 1
upd_source older
expect "an older release is not offered" "d['latest']['full'] == '0.9.0-1' and d['available'] is False" "$(call update-check '{"force": true}')"
call update-install '{"version": "0.9.0-1"}' | grep -q 'is not newer' && ok "update-install refuses a downgrade" || bad "update-install accepted a downgrade"

mock_release badsum "v$NEWER" "$NEWER" 1 badsum
upd_source badsum
out=$(call update-check '{"force": true, "auto_install": true}')
expect "auto_install starts the self-update job" "d['started'] is True and d['job']['title_key'] == 'self_update' and d['job']['title_params'] == {'version': '$NEWER-1'}" "$out"
state=$(wait_job admin)
[ "$state" = "failed" ] && grep -q 'Checksum mismatch' /var/lib/runway/jobs/admin.log && ok "a wrong checksum fails the self-update job" || bad "self-update with a wrong checksum: $state: $(tail -n 3 /var/lib/runway/jobs/admin.log)"
expect "the failed update leaves $INSTALLED installed and is recorded" \
    "d['installed'] == '$INSTALLED' and d['last_failed_version'] == '$NEWER-1' and d['available'] is True" "$(call update-status '{}')"
grep -q "<version>$V_MAJ.$V_MIN.$V_PATCH</version>" "$META" && grep -q "<release>$V_REL</release>" "$META" && ok "Plesk's meta.xml is unchanged" || bad "meta.xml changed"
[ ! -e /var/lib/runway/cache/update ] && ok "the downloads were removed" || bad "downloads left in /var/lib/runway/cache/update"
expect "auto_install waits 24 hours before it retries a failed version" "d['started'] is False and 'auto_skipped' in d" "$(call update-check '{"auto_install": true}')"
mock_release redirect "v$NEWER" "$NEWER" 1 redirect
upd_source redirect
expect "the redirect release is offered" "d['available'] is True and d['latest']['full'] == '$NEWER-1'" "$(call update-check '{"force": true}')"
call update-install "{\"version\": \"$NEWER-1\"}" >/dev/null
state=$(wait_job admin)
[ "$state" = "failed" ] && grep -q 'redirected to a URL that is not https://' /var/lib/runway/jobs/admin.log && ok "a redirect to ftp:// fails the self-update job" || bad "self-update with an ftp:// redirect: $state: $(tail -n 3 /var/lib/runway/jobs/admin.log)"
# Only SHA256SUMS (reached through a relative http:// redirect) can have been downloaded.
grep -q '\] Downloaded ' /var/lib/runway/jobs/admin.log && ok "an allowed redirect (SHA256SUMS) is followed" || bad "SHA256SUMS redirect: $(tail -n 5 /var/lib/runway/jobs/admin.log)"
grep -q "<release>$V_REL</release>" "$META" && ok "the refused redirect leaves meta.xml unchanged" || bad "meta.xml changed after the refused redirect"

if [ "${RUNWAY_SMOKE_SELF_UPDATE:-0}" = "1" ]; then
    # Irreversible: the container keeps the repackaged release (Plesk refuses downgrades).
    TARGET=$V_MAJ.$V_MIN.$V_PATCH-$((V_REL + 1))
    echo "== self-update: real upgrade $INSTALLED -> $TARGET (RUNWAY_SMOKE_SELF_UPDATE=1)"
    mkdir -p "$UPD_DIR/pack"
    plesk bin extension --pack runway -destination "$UPD_DIR/pack" >/dev/null
    PACKED=$(ls "$UPD_DIR"/pack/*.zip 2>/dev/null | head -n 1)
    # release+1 in meta.xml and a changed (functionally identical) helper, so the upgrade really
    # replaces /opt/runway/bin/runway-helper, the file the running self-update job was started from.
    MARKER="# smoke release $((V_REL + 1))"
    python3 - "$PACKED" "$UPD_DIR/repacked.zip" "$((V_REL + 1))" "$MARKER" <<'PYEOF'
import re, sys, zipfile
source, dest, release, marker = sys.argv[1:5]
changed = set()
with zipfile.ZipFile(source) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
    for info in zin.infolist():
        data = zin.read(info)
        if info.filename == "meta.xml":
            data = re.sub(rb"<release>\s*\d+\s*</release>", b"<release>" + release.encode() + b"</release>", data, count=1)
            changed.add("meta")
        elif info.filename == "sbin/runway-helper":
            data = data.rstrip(b"\n") + b"\n" + marker.encode() + b"\n"
            changed.add("helper")
        zout.writestr(info, data)
sys.exit(0 if changed == {"meta", "helper"} else 1)
PYEOF
    [ $? -eq 0 ] && [ -s "$UPD_DIR/repacked.zip" ] && ok "repackaged the installed extension as $TARGET (with a changed helper)" || bad "repackaging failed (pack: ${PACKED:-none})"
    HELPER_BEFORE=$(sha256sum /opt/runway/bin/runway-helper | cut -d' ' -f1)
    mock_release real "v$TARGET" "$V_MAJ.$V_MIN.$V_PATCH" "$((V_REL + 1))" "zip=$UPD_DIR/repacked.zip"
    upd_source real
    expect "the repackaged release is offered" "d['available'] is True and d['latest']['full'] == '$TARGET'" "$(call update-check '{"force": true}')"
    case "$(curl -s --max-time 5 "http://127.0.0.1:$PORT/")" in "Hello from"*) ok "the application answers before the upgrade" ;; *) bad "the application does not answer before the upgrade" ;; esac
    expect "update-install starts the self-update job" "d['ok'] and d['job'] == 'admin' and d['version'] == '$TARGET'" "$(call update-install "{\"version\": \"$TARGET\"}")"
    state=""
    for _ in $(seq 1 450); do
        state=$(call job-status '{"job": "admin"}' | field "['state']" 2>/dev/null)
        case "$state" in queued|running|"") sleep 2 ;; *) break ;; esac
    done
    [ "$state" = "succeeded" ] && ok "the self-update job succeeded" || bad "self-update job: $state: $(tail -n 25 /var/lib/runway/jobs/admin.log)"
    grep -q "<release>$((V_REL + 1))</release>" "$META" && ok "Plesk's meta.xml shows release $((V_REL + 1))" || bad "meta.xml: $(grep -E '<(version|release)>' "$META" | tr -d ' ')"
    plesk bin extension --list | grep -q '^runway ' && ok "plesk bin extension --list lists runway" || bad "runway missing from plesk bin extension --list"
    expect "update-status: $TARGET installed, nothing newer" "d['installed'] == '$TARGET' and d['available'] is False and d['job']['state'] == 'succeeded'" "$(call update-status '{}')"
    [ "$(sha256sum /opt/runway/bin/runway-helper | cut -d' ' -f1)" != "$HELPER_BEFORE" ] && [ "$(tail -n 1 /opt/runway/bin/runway-helper)" = "$MARKER" ] && ok "the upgrade replaced the helper copy the job ran from, and the job survived" || bad "/opt/runway/bin/runway-helper was not replaced by the upgrade"
    cmp -s /opt/runway/bin/runway-helper /usr/local/psa/admin/sbin/modules/runway/runway-helper && ok "the helper copy matches the upgraded helper" || bad "/opt/runway/bin/runway-helper differs from the upgraded helper"
    grep -q 'is installed' /var/lib/runway/jobs/admin.log && grep -q 'successfully' /var/lib/runway/jobs/admin.log && ok "the job log shows the plesk output and the result" || bad "self-update log: $(tail -n 5 /var/lib/runway/jobs/admin.log)"
    case "$(curl -s --max-time 5 "http://127.0.0.1:$PORT/")" in "Hello from"*) ok "the application kept running" ;; *) bad "the application does not answer after the upgrade" ;; esac
    JAR=$UPD_DIR/cookies
    LINK=$(plesk bin admin --get-login-link -relative-url | tr -d '\r')
    curl -s -c "$JAR" -b "$JAR" -L "http://localhost:8880$LINK" -o /dev/null
    expect "the panel API of the new version answers" "d['status'] == 'success' and d['data']['installed'] == '$TARGET' and d['data']['available'] is False" \
        "$(curl -s -b "$JAR" -H 'X-Requested-With: XMLHttpRequest' "http://localhost:8880/modules/runway/index.php/api/update")"
    out=$(plesk ext runway --check-update 2>&1); code=$?
    [ $code -eq 0 ] && echo "$out" | grep -q "^Installed: *$TARGET" && ok "CLI --check-update of the new version" || bad "CLI --check-update ($code): $out"
    out=$(plesk ext runway --update 2>&1); code=$?
    [ $code -eq 0 ] && echo "$out" | grep -q "is up to date" && ok "CLI --update: nothing newer" || bad "CLI --update ($code): $out"
fi
kill "$UPD_PID" 2>/dev/null; wait "$UPD_PID" 2>/dev/null
UPD_PID=""
rm -f "$UPD_SOURCE_FLAG" "$UPD_CACHE" /etc/runway/allow-insecure-fetch
rm -rf "$UPD_DIR"
expect "without the test switch the source is GitHub again" "d['update_source'] is None and d['latest'] is None" "$(call update-status '{}')"

echo "== cleanup"
call app-remove "{\"domain_id\": $ID}" >/dev/null
[ ! -e /etc/systemd/system/runway-app-$ID.service ] && ok "units removed" || bad "units left"
rm -rf "$APP" "$HOME_DIR"/apps/smoke-*
rm -f /etc/runway/allow-insecure-fetch

echo "== $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
