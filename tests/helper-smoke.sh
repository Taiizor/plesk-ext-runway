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
# The zero-downtime section runs request loops through an nginx test server on 127.0.0.1:18990
# and 18991 during switches (a fake generated configuration of smoke.test carries the marker);
# with /root/runway-helper-1.0.0 (copied by .github/scripts/plesk-e2e.sh) it also compares the
# files of applications without the setting with those of the 1.0.0 helper.
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
    rm -f "$PAUSE_FLAG" /etc/runway/update-source /etc/runway/allow-insecure-fetch /var/lib/runway/test-switch-fault
    # The zero-downtime section's nginx test server and fake generated configuration.
    if [ -e /etc/nginx/conf.d/zz-runway-smoke-zd.conf ]; then
        rm -f /etc/nginx/conf.d/zz-runway-smoke-zd.conf
        systemctl reload nginx >/dev/null 2>&1
    fi
    rm -rf /var/www/vhosts/system/smoke.test
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
	"syscall"
	"time"
)

// Files mapped by /map stay mapped while the application runs.
var mapped [][]byte

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "smoke %s", os.Getenv("SMOKE"))
	})
	// Health check path of the health watch tests: 503 while the file "unhealthy" exists.
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if _, err := os.Stat("unhealthy"); err == nil {
			http.Error(w, "unhealthy", http.StatusServiceUnavailable)
			return
		}
		fmt.Fprint(w, "ok")
	})
	// Health check path of the expected response content tests (health_match): JSON by default,
	// {"status": "down", ...} while the file "body-down" exists, text while "body-text" exists, a
	// raw chunked answer in three pieces while "body-chunked" exists (net/http answers an HTTP/1.0
	// request without chunks), one byte every 200 ms for 10 s while "body-slow" exists, and 503
	// with the text "Healthy" while "unhealthy" exists.
	http.HandleFunc("/state", func(w http.ResponseWriter, r *http.Request) {
		if _, err := os.Stat("unhealthy"); err == nil {
			http.Error(w, "Healthy", http.StatusServiceUnavailable)
			return
		}
		if _, err := os.Stat("body-text"); err == nil {
			fmt.Fprint(w, "Service is Healthy")
			return
		}
		if _, err := os.Stat("body-slow"); err == nil {
			w.WriteHeader(http.StatusOK)
			for i := 0; i < 50; i++ {
				fmt.Fprint(w, " ")
				w.(http.Flusher).Flush()
				time.Sleep(200 * time.Millisecond)
			}
			return
		}
		if _, err := os.Stat("body-chunked"); err == nil {
			conn, buf, err := w.(http.Hijacker).Hijack()
			if err != nil {
				return
			}
			defer conn.Close()
			buf.WriteString("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n")
			for _, part := range []string{`{"status":`, ` "ok", `, `"n": 1}`} {
				fmt.Fprintf(buf, "%x\r\n%s\r\n", len(part), part)
				buf.Flush()
				time.Sleep(50 * time.Millisecond)
			}
			buf.WriteString("0\r\n\r\n")
			buf.Flush()
			return
		}
		status := "ok"
		if _, err := os.Stat("body-down"); err == nil {
			status = "down"
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status": "%s", "n": 1, "db": {"up": true, "ms": 3}}`, status)
	})
	// A file served from the application root: its page cache is charged to the service.
	http.HandleFunc("/blob", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "blob.bin")
	})
	// The same file mapped into memory and read (like a database file of bbolt or SQLite): mapped
	// file pages are the application's working set.
	http.HandleFunc("/map", func(w http.ResponseWriter, r *http.Request) {
		f, err := os.Open("blob.bin")
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer f.Close()
		st, err := f.Stat()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		data, err := syscall.Mmap(int(f.Fd()), 0, int(st.Size()), syscall.PROT_READ, syscall.MAP_SHARED)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		sum := 0
		for i := 0; i < len(data); i += 4096 {
			sum += int(data[i])
		}
		mapped = append(mapped, data)
		fmt.Fprintf(w, "mapped %d %d", len(data), sum)
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

echo "== memory: the application's own memory and the file cache (docs/DESIGN.md section 7)"
mem_ok() { # mem_ok JSON-OF-A-UNIT: memory_used_bytes + memory_cache_bytes = memory_bytes (MemoryCurrent)
    jexpr "d['memory_bytes'] is not None and d['memory_used_bytes'] is not None and d['memory_used_bytes'] + (d['memory_cache_bytes'] or 0) == d['memory_bytes']"
}
[ "$(call app-status "{\"domain_id\": $ID}" | jexpr "json.dumps(d['service'])" | mem_ok)" = "True" ] \
    && ok "app-status: memory_used_bytes + memory_cache_bytes = memory_bytes" || bad "app-status memory: $(call app-status "{\"domain_id\": $ID}" | jexpr "d['service']")"
if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
    # A 48 MiB file written as the user and dropped from the page cache (posix_fadvise), so that
    # serving it charges its pages to the application's cgroup, not to this shell's.
    runuser -u "$USER_NAME" -- python3 -c "
import os
with open('$APP/blob.bin', 'wb') as fh:
    fh.write(os.urandom(48 << 20))
    fh.flush()
    os.fsync(fh.fileno())
    os.posix_fadvise(fh.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)"
    size=$(curl -s -o /dev/null -w '%{size_download}' "http://127.0.0.1:$PORT/blob")
    st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(lambda s: s['memory_cache_bytes'] >= 40 << 20 and s['memory_used_bytes'] < s['memory_bytes'] - (40 << 20))(d['service'])")
    [ "$size" = "$((48 << 20))" ] && [ "$st" = "True" ] && ok "a served 48 MiB file counts as file cache, not as the application's memory" \
        || bad "file cache after serving $size bytes: $(call app-status "{\"domain_id\": $ID}" | jexpr "d['service']")"
    [ "$(call apps-list '{}' | jexpr "[a['memory_cache_bytes'] >= 40 << 20 and a['memory_used_bytes'] + a['memory_cache_bytes'] == a['memory_bytes'] for a in d['apps'] if a['domain_id'] == $ID][0]")" = "True" ] \
        && ok "apps-list: memory_used_bytes and memory_cache_bytes" || bad "apps-list memory: $(call apps-list '{}' | jexpr "[a for a in d['apps'] if a['domain_id'] == $ID]")"
    # Mapping the cached file moves its pages from the file cache to the application's memory
    # (memory.stat file_mapped). The kernel updates the statistics of a cgroup in batches: retry.
    before=$(call app-status "{\"domain_id\": $ID}" | jexpr "d['service']['memory_cache_bytes']")
    mapped=$(curl -s "http://127.0.0.1:$PORT/map")
    st=False
    for _ in 1 2 3 4 5; do
        st=$(call app-status "{\"domain_id\": $ID}" | jexpr "(lambda s: s['memory_used_bytes'] >= 40 << 20 and s['memory_cache_bytes'] <= $before - (40 << 20))(d['service'])")
        [ "$st" = "True" ] && break
        sleep 1
    done
    [ "$st" = "True" ] && ok "a mapped file counts as the application's memory, not as file cache" \
        || bad "file cache after mapping ($mapped, cache before: $before): $(call app-status "{\"domain_id\": $ID}" | jexpr "d['service']")"
    rm -f "$APP/blob.bin"
else
    echo "SKIP  file cache of a service (cgroup v1: no /sys/fs/cgroup/cgroup.controllers)"
fi

echo "== limits: MemoryPressureWatch=off with a memory or CPU limit on systemd 254+ (docs/DESIGN.md section 7)"
SYSTEMD_VERSION=$(systemctl --version | head -1 | awk '{print $2}')
apply_limits() { # apply_limits LIMITS_JSON: the sample again (same variables) with these limits, restarted
    local before pid
    before=$(systemctl show -p MainPID --value runway-app-$ID)
    call app-apply "{$(base | sed "s/\"limits\": {}/\"limits\": $1/"), \"env\": {\"SMOKE\": \"a \\\"b\\\" \$HOME %h\"}, \"restart\": true}" >/dev/null
    # app-apply restarts without waiting: wait for the new process and its answer.
    for _ in $(seq 1 40); do
        pid=$(systemctl show -p MainPID --value runway-app-$ID)
        if [ "$pid" != "0" ] && [ "$pid" != "$before" ] && [ "$(curl -s "http://127.0.0.1:$PORT/")" = 'smoke a "b" $HOME %h' ]; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}
# The bind mount of memory.pressure that systemd 254+ adds to the read-only cgroup tree: the second
# cgroup2 mount that hides the unit's limits from .NET.
pressure_mounts() { awk '$5 ~ /memory\.pressure$/' "/proc/$(systemctl show -p MainPID --value runway-app-$ID)/mountinfo" | wc -l; }
if apply_limits '{"memory_mb": 512, "cpu_percent": 150}'; then
    if [ "${SYSTEMD_VERSION:-0}" -ge 254 ] 2>/dev/null; then
        grep -qx 'MemoryPressureWatch=off' /etc/systemd/system/runway-app-$ID.service && [ "$(pressure_mounts)" = "0" ] \
            && ok "memory and CPU limit: MemoryPressureWatch=off, no memory.pressure mount in the service (systemd $SYSTEMD_VERSION)" \
            || bad "memory and CPU limit on systemd $SYSTEMD_VERSION: $(grep -c MemoryPressureWatch /etc/systemd/system/runway-app-$ID.service) line(s), $(pressure_mounts) memory.pressure mount(s)"
    else
        grep -q 'MemoryPressureWatch' /etc/systemd/system/runway-app-$ID.service && bad "MemoryPressureWatch on systemd $SYSTEMD_VERSION" \
            || ok "memory and CPU limit on systemd $SYSTEMD_VERSION: no MemoryPressureWatch line (unknown before 254)"
    fi
else
    bad "the sample with memory and CPU limits does not answer"
fi
apply_limits '{"tasks": 512}' && ! grep -q 'MemoryPressureWatch' /etc/systemd/system/runway-app-$ID.service \
    && ok "a task limit alone keeps the unit without MemoryPressureWatch" || bad "task limit: $(grep MemoryPressureWatch /etc/systemd/system/runway-app-$ID.service)"
apply_limits '{}' && ! grep -q 'MemoryPressureWatch' /etc/systemd/system/runway-app-$ID.service \
    && ok "without limits the unit has no MemoryPressureWatch line" || bad "unit without limits: $(grep MemoryPressureWatch /etc/systemd/system/runway-app-$ID.service)"

echo "== health watch (docs/DESIGN.md section 7, health watch)"
watch_apply() { # watch_apply EXTRA_FIELDS: the sample (same variables) with these fields, not restarted
    call app-apply "{$(base), \"env\": {\"SMOKE\": \"a \\\"b\\\" \$HOME %h\"}, \"restart\": false$1}" | field "['ok']"
}
hw() { call app-status "{\"domain_id\": $ID}" | jexpr "$1"; }
main_pid() { systemctl show -p MainPID --value runway-app-$ID; }
wait_new_pid() { # wait_new_pid OLD: a new process answers
    local pid
    for _ in $(seq 1 40); do
        pid=$(main_pid)
        if [ "$pid" != "0" ] && [ "$pid" != "$1" ] && [ "$(curl -s "http://127.0.0.1:$PORT/")" = 'smoke a "b" $HOME %h' ]; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}
rm -f "$APP/unhealthy"
[ "$(watch_apply ', "health_watch": true')" = "True" ] && [ "$(hw "d['health_watch']")" = "None" ] \
    && [ ! -e /etc/systemd/system/runway-health.timer ] \
    && ok "without a health check path the watch stays off (no timer)" || bad "watch without a path: $(hw "d['health_watch']")"
[ "$(watch_apply ', "health_path": "/health", "health_watch": true, "health_interval": 10, "health_failures": 2')" = "True" ] \
    && [ "$(systemctl is-enabled runway-health.timer)" = "enabled" ] && [ "$(systemctl is-active runway-health.timer)" = "active" ] \
    && [ "$(hw "(d['health_watch']['interval'], d['health_watch']['failures_limit'])")" = "(10, 2)" ] \
    && ok "watch on: runway-health.timer enabled and active, interval 10 s, 2 failures" \
    || bad "watch on: timer $(systemctl is-enabled runway-health.timer) $(systemctl is-active runway-health.timer), $(hw "d['health_watch']")"
pid0=$(main_pid)
"$H" _health now >/dev/null
[ "$(main_pid)" = "$pid0" ] && [ "$(hw "(d['health_watch']['result'], d['health_watch']['failures'])")" = "('healthy', 0)" ] \
    && ok "a healthy application is left alone" || bad "healthy: $(hw "d['health_watch']")"
runuser -u "$USER_NAME" -- touch "$APP/unhealthy"
"$H" _health now >/dev/null
[ "$(main_pid)" = "$pid0" ] && [ "$(hw "(d['health_watch']['result'], d['health_watch']['failures'], d['health_watch']['code'])")" = "('unhealthy', 1, 'http')" ] \
    && ok "first failed check (HTTP 503): counted, no restart" || bad "first failure: $(hw "d['health_watch']")"
"$H" _health now >/dev/null
if wait_new_pid "$pid0"; then
    [ "$(hw "(d['health_watch']['restarts_last_hour'], d['health_watch']['restart_params'].get('code'), bool(d['health_watch']['restarted_iso']), d['health_watch']['failures'])")" = "(1, 503, True, 0)" ] \
        && ok "second failed check in a row: restarted in place, reason HTTP 503 on the status" || bad "restart status: $(hw "d['health_watch']")"
else
    bad "no restart after 2 failed checks: $(hw "d['health_watch']")"
fi
[ "$(call app-logs "{\"domain_id\": $ID, \"lines\": 100}" | jexpr "'health watch: restarting the application after 2 failed health checks' in d['log']")" = "True" ] \
    && ok "the application log notes the restart" || bad "application log: $(call app-logs "{\"domain_id\": $ID, \"lines\": 20}" | jexpr "d['log']")"
# A new instance gets HEALTH_WATCH_GRACE (60 s) before its first check; "_health now" skips it.
# After 9 s the interval (10 s, minus 2 s of timer slack) is over, so only the grace holds it back.
pid1=$(main_pid)
sleep 9
"$H" _health >/dev/null
[ "$(main_pid)" = "$pid1" ] && [ "$(hw "d['health_watch']['failures']")" = "0" ] \
    && ok "no check within 60 seconds after a start" || bad "start grace: $(hw "d['health_watch']")"
# At most 3 restarts per hour: with 1 failure per restart the third one is the last.
[ "$(watch_apply ', "health_path": "/health", "health_watch": true, "health_interval": 10, "health_failures": 1')" = "True" ] || bad "apply 1 failure"
for _ in $(seq 1 30); do
    "$H" _health now >/dev/null
    [ "$(hw "d['health_watch']['paused']")" = "True" ] && break
    sleep 1
done
pid2=$(main_pid)
sleep 1
"$H" _health now >/dev/null
[ "$(hw "(d['health_watch']['restarts_last_hour'], d['health_watch']['paused'])")" = "(3, True)" ] && [ "$(main_pid)" = "$pid2" ] \
    && ok "after 3 restarts within an hour: paused, no further restart" || bad "restart limit: $(hw "d['health_watch']")"
[ "$(call app-logs "{\"domain_id\": $ID, \"lines\": 100}" | jexpr "'but no restart' in d['log']")" = "True" ] \
    && ok "the application log notes the pause" || bad "pause not in the application log"
rm -f "$APP/unhealthy"
for _ in $(seq 1 20); do
    "$H" _health now >/dev/null
    [ "$(hw "(d['health_watch']['result'], d['health_watch']['paused'])")" = "('healthy', False)" ] && break
    sleep 0.5
done
[ "$(hw "(d['health_watch']['result'], d['health_watch']['paused'], d['health_watch']['failures'])")" = "('healthy', False, 0)" ] \
    && ok "healthy again: failures and pause reset" || bad "healthy again: $(hw "d['health_watch']")"
# A stopped application stays stopped.
call app-action "{\"domain_id\": $ID, \"action\": \"stop\"}" >/dev/null
runuser -u "$USER_NAME" -- touch "$APP/unhealthy"
"$H" _health now >/dev/null
[ "$(systemctl is-active runway-app-$ID)" != "active" ] && ok "a stopped application is not restarted by the watch" || bad "the watch started a stopped application"
rm -f "$APP/unhealthy"
call app-action "{\"domain_id\": $ID, \"action\": \"start\"}" >/dev/null
wait_new_pid 0 || bad "start after the watch tests"
[ "$(watch_apply ', "health_path": "/health", "health_watch": false')" = "True" ] && [ ! -e /etc/systemd/system/runway-health.timer ] \
    && [ ! -e /etc/systemd/system/runway-health.service ] && [ ! -e /var/lib/runway/health/$ID.json ] && [ "$(hw "d['health_watch']")" = "None" ] \
    && ok "watch off: timer, service and watch state removed" || bad "watch off: $(ls /etc/systemd/system/runway-health.* /var/lib/runway/health/ 2>&1)"
watch_apply '' >/dev/null

echo "== expected response content of the health check (docs/DESIGN.md section 7, health_match)"
# jstr TEXT: TEXT as a JSON string literal.
jstr() { python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"; }
# match_apply TEXT [EXTRA_FIELDS]: the sample with the health path /state and this expected content.
match_apply() { watch_apply ", \"health_path\": \"/state\", \"health_match\": $(jstr "$1")${2:-}"; }
# match_status: (health, health_code) of app-status (the health check with its 2 s timeout).
match_status() { hw "(d['health'], d['health_code'])"; }
# match_case NAME TEXT EXPECTED: app-status with this expected content gives EXPECTED.
match_case() {
    local st
    [ "$(match_apply "$2")" = "True" ] || { bad "$1: apply refused"; return; }
    st=$(match_status)
    [ "$st" = "$3" ] && ok "$1: $st" || bad "$1: $st, expected $3 ($(hw "d['health_detail']"))"
}
rm -f "$APP/unhealthy" "$APP/body-down" "$APP/body-text" "$APP/body-chunked" "$APP/body-slow"
# Validation (the expected text is customer-controlled as well).
expect_reject "expected content: text starting with { that is not JSON" '"health_path": "/state", "health_match": "{status: ok}"'
expect_reject "expected content: a JSON object with NaN" '"health_path": "/state", "health_match": "{\"a\": NaN}"'
expect_reject "expected content: 201 characters" "\"health_path\": \"/state\", \"health_match\": \"$(printf 'x%.0s' $(seq 201))\""
expect_reject "expected content: a control character" '"health_path": "/state", "health_match": "a\u0001b"'
expect_reject "expected content: not a string" '"health_path": "/state", "health_match": {"status": "ok"}'
[ "$(match_apply "$(printf 'ş%.0s' $(seq 200))")" = "True" ] && [ "$(hw "len(d['health_match'])")" = "200" ] \
    && ok "expected content: 200 characters (2-byte UTF-8 each) are accepted" || bad "200 multibyte characters: $(hw "len(d['health_match'])")"
[ "$(watch_apply ', "health_match": "Healthy"')" = "True" ] && [ "$(python3 -c "import json; print(json.load(open('/var/lib/runway/apps/$ID.json'))['health_match'])")" = "" ] \
    && ok "without a health check path the expected content is dropped" || bad "expected content without a path was kept"
[ "$(match_apply '  {"status":"ok"}  ')" = "True" ] && [ "$(python3 -c "import json; print(json.load(open('/var/lib/runway/apps/$ID.json'))['health_match'])")" = '{"status":"ok"}' ] \
    && [ "$(hw "d['health_match']")" = '{"status":"ok"}' ] && ok "expected content trimmed in the state and reported by app-status" || bad "stored expected content: $(hw "d['health_match']")"
# Text mode: a case-sensitive substring of the body.
match_case "text not in the JSON answer" 'Healthy' "('unhealthy', 'body_mismatch')"
match_case "text that is part of the JSON answer" '"n": 1' "('healthy', 'http_match')"
[ "$(hw "(d['health_detail'], d['health_params'])")" = "('HTTP 200 from /state, expected content found', {'code': 200, 'path': '/state'})" ] \
    && ok "detail and params of a match (no body in them)" || bad "match detail: $(hw "(d['health_detail'], d['health_params'])")"
runuser -u "$USER_NAME" -- touch "$APP/body-text"
match_case "text found in a text answer" 'Healthy' "('healthy', 'http_match')"
match_case "text is case-sensitive" 'healthy' "('unhealthy', 'body_mismatch')"
match_case "a JSON object expected, the answer is text" '{"status":"ok"}' "('unhealthy', 'body_not_json')"
[ "$(hw "d['health_detail']")" = "HTTP 200 from /state, the response is not a JSON object" ] && ok "detail of an answer that is not JSON" || bad "not-JSON detail: $(hw "d['health_detail']")"
rm -f "$APP/body-text"
# JSON mode: subsets with JSON types; spacing and key order do not matter.
match_case "JSON with other spacing and key order" '{"n":1,"status":"ok"}' "('healthy', 'http_match')"
match_case "JSON nested object as a subset" '{ "db": { "up": true } }' "('healthy', 'http_match')"
match_case "JSON nested key missing" '{"db": {"up": true, "region": "eu"}}' "('unhealthy', 'body_mismatch')"
match_case "JSON \"1\" is not 1" '{"n": "1"}' "('unhealthy', 'body_mismatch')"
match_case "JSON true is not 1" '{"n": true}' "('unhealthy', 'body_mismatch')"
match_case "JSON 1 is not true" '{"db": {"up": 1}}' "('unhealthy', 'body_mismatch')"
match_case "JSON with another value" '{"status": "down"}' "('unhealthy', 'body_mismatch')"
[ "$(hw "d['health_detail']")" = "HTTP 200 from /state, expected content not found" ] && ok "detail of a mismatch" || bad "mismatch detail: $(hw "d['health_detail']")"
runuser -u "$USER_NAME" -- touch "$APP/body-chunked"
match_case "a chunked JSON answer" '{"status": "ok", "n": 1}' "('healthy', 'http_match')"
rm -f "$APP/body-chunked"
runuser -u "$USER_NAME" -- touch "$APP/unhealthy"
match_case "HTTP 503 stays an HTTP failure (also with the content in the body)" 'Healthy' "('unhealthy', 'http')"
rm -f "$APP/unhealthy"
runuser -u "$USER_NAME" -- touch "$APP/body-slow"
[ "$(match_apply 'Healthy')" = "True" ] || bad "apply for the slow answer"
t0=$(date +%s%N)
st=$(hw "(d['health'], d['health_code'], d['health_detail'])")
elapsed=$(( ($(date +%s%N) - t0) / 1000000 ))
case "$st" in
    "('unhealthy', 'failed', 'Health check failed: timed out')") [ "$elapsed" -lt 6000 ] && ok "a slowly sent answer cannot extend the 2 s deadline (app-status took ${elapsed} ms)" || bad "slow answer: app-status took ${elapsed} ms" ;;
    *) bad "slow answer: $st after ${elapsed} ms" ;;
esac
rm -f "$APP/body-slow"
# The health watch restarts an application whose answer lacks the expected content.
[ "$(match_apply '{"status": "ok"}' ', "health_watch": true, "health_interval": 10, "health_failures": 2')" = "True" ] || bad "apply watch with expected content"
pid0=$(main_pid)
"$H" _health now >/dev/null
[ "$(hw "(d['health_watch']['result'], d['health_watch']['code'])")" = "('healthy', 'http_match')" ] && ok "health watch: the expected content is found" || bad "watch with content: $(hw "d['health_watch']")"
runuser -u "$USER_NAME" -- touch "$APP/body-down"
"$H" _health now >/dev/null
[ "$(main_pid)" = "$pid0" ] && [ "$(hw "(d['health_watch']['failures'], d['health_watch']['code'])")" = "(1, 'body_mismatch')" ] \
    && ok "health watch: an answer without the expected content counts as a failed check" || bad "watch mismatch: $(hw "d['health_watch']")"
"$H" _health now >/dev/null
if wait_new_pid "$pid0"; then
    [ "$(hw "(d['health_watch']['restart_code'], d['health_watch']['restart_detail'])")" = "('body_mismatch', 'HTTP 200 from /state, expected content not found')" ] \
        && ok "health watch: restarted after 2 answers without the expected content (reason body_mismatch)" || bad "watch restart reason: $(hw "d['health_watch']")"
else
    bad "health watch: no restart after 2 answers without the expected content: $(hw "d['health_watch']")"
fi
[ "$(call app-logs "{\"domain_id\": $ID, \"lines\": 100}" | jexpr "'(last: HTTP 200 from /state, expected content not found)' in d['log']")" = "True" ] \
    && ok "the application log names the missing content as the reason" || bad "application log of the content restart"
rm -f "$APP/body-down"
[ "$(match_apply '' ', "health_watch": false')" = "True" ] && [ ! -e /etc/systemd/system/runway-health.timer ] && [ "$(hw "d['health_code']")" = "http" ] \
    && ok "expected content off: the status line decides again" || bad "content off: $(hw "(d['health_code'], d['health_match'])")"
# Every app-apply restarts the trigger watcher (runway-deploy-<id>.path): the many saves of this
# section exceed systemd's start limit (5 within 10 s). Reset it for the trigger tests below.
systemctl reset-failed runway-deploy-$ID.path 2>/dev/null
watch_apply '' >/dev/null
[ "$(systemctl is-active runway-deploy-$ID.path)" = "active" ] || bad "trigger watcher after the expected content tests: $(systemctl is-active runway-deploy-$ID.path)"

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

echo "== document roots with symbolic links resolved (app-inspect and app-page: document_root)"
runuser -u "$USER_NAME" -- bash -c "mkdir -p '$HOME_DIR/apps/smoke-docroot/api' && ln -sfn smoke-docroot/api '$HOME_DIR/apps/smoke-link' && ln -sfn smoke '$HOME_DIR/apps/smoke-current'"
inspect_root() { # inspect_root APP_ROOT DOCUMENT_ROOTS_JSON: document_root of app-inspect
    call app-inspect "{\"sysuser\": \"$USER_NAME\", \"app_root\": \"$1\", \"document_roots\": $2}" | jexpr "d.get('document_root', 'missing')"
}
[ "$(inspect_root apps/smoke-link '["apps/smoke-docroot"]')" = "apps/smoke-docroot" ] && ok "an application root behind a link into a document root" \
    || bad "link into a document root: $(inspect_root apps/smoke-link '["apps/smoke-docroot"]')"
[ "$(inspect_root apps/smoke '["apps/smoke-docroot", "apps/smoke-current"]')" = "apps/smoke-current" ] && ok "a document root that is a link to the application root" \
    || bad "document root linked to the application root: $(inspect_root apps/smoke '["apps/smoke-docroot", "apps/smoke-current"]')"
[ "$(inspect_root apps/smoke '["apps/smoke-docroot", "../etc", 5]')" = "None" ] && ok "outside the document roots (invalid entries are ignored)" \
    || bad "outside the document roots: $(inspect_root apps/smoke '["apps/smoke-docroot", "../etc", 5]')"
[ "$(call app-page "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke\", \"runtime\": \"go\", \"document_roots\": [\"apps/smoke-current\"]}" | jexpr "d['inspect']['document_root']")" = "apps/smoke-current" ] \
    && ok "app-page names the document root as well" || bad "app-page document_root"
rm -rf "$HOME_DIR/apps/smoke-docroot" "$HOME_DIR/apps/smoke-link" "$HOME_DIR/apps/smoke-current"

echo "== candidate document roots of the inspection (public_dirs: real directories only, order per runtime)"
# Real directories public and wwwroot; "dist" is a link (never counts), "web" a file.
runuser -u "$USER_NAME" -- bash -c "mkdir -p '$HOME_DIR/apps/smoke-pub/'{public,wwwroot} && ln -sfn public '$HOME_DIR/apps/smoke-pub/dist' && touch '$HOME_DIR/apps/smoke-pub/web'"
PD=$(call app-inspect "{\"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-pub\"}" | jexpr "d['public_dirs']")
[ "$(echo "$PD" | python3 -c "import ast,sys; d = ast.literal_eval(sys.stdin.read()); print((d['dotnet'], d['bun'], d['php'], d['ruby'], d['python'], d['go'], d['binary']))")" \
    = "(['wwwroot'], ['public'], ['public'], ['public'], ['public'], ['public', 'wwwroot'], ['public', 'wwwroot'])" ] \
    && ok "public_dirs: wwwroot (.NET), public (Bun: dist is a link), public (PHP: web is a file), public (Ruby, Python), public, wwwroot (others)" \
    || bad "public_dirs: $PD"
[ "$(call app-inspect "{\"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-pub-missing\"}" | jexpr "d['exists'] is False and all(v == [] for v in d['public_dirs'].values()) and len(d['public_dirs']) == 9")" = "True" ] \
    && ok "public_dirs of a missing application root: empty for every runtime" || bad "public_dirs of a missing application root"
[ "$(call app-page "{\"domain_id\": $ID, \"sysuser\": \"$USER_NAME\", \"app_root\": \"apps/smoke-pub\", \"runtime\": \"dotnet\"}" | jexpr "d['inspect']['public_dirs']['dotnet']")" = "['wwwroot']" ] \
    && ok "app-page reports public_dirs as well" || bad "app-page public_dirs"

echo "== document root checks (docroot-check, docroot-access)"
runuser -u "$USER_NAME" -- bash -c "umask 027; mkdir -p '$HOME_DIR/apps/smoke-pub/wwwroot/media' && ln -sfn /etc '$HOME_DIR/apps/smoke-out' && ln -sfn smoke-pub/wwwroot '$HOME_DIR/apps/smoke-in' && ln -sfn .. '$HOME_DIR/apps/smoke-up' && echo x > '$HOME_DIR/apps/smoke-pub/file.txt'"
dr() { call docroot-check "{\"sysuser\": \"$USER_NAME\", \"document_root\": \"$1\"}"; }
[ "$(dr apps/smoke-pub/wwwroot | jexpr "(d['ok'], d['exists'], d['real'])")" = "(True, True, 'apps/smoke-pub/wwwroot')" ] && ok "docroot-check: an existing directory" || bad "docroot-check existing: $(dr apps/smoke-pub/wwwroot)"
[ "$(dr apps/smoke-pub/new/www | jexpr "(d['ok'], d['exists'])")" = "(True, False)" ] && ok "docroot-check: a missing directory is fine (Plesk creates it)" || bad "docroot-check missing: $(dr apps/smoke-pub/new/www)"
[ "$(dr apps/smoke-in | jexpr "(d['ok'], d['real'])")" = "(True, 'apps/smoke-pub/wwwroot')" ] && ok "docroot-check: a link inside the home directory" || bad "docroot-check link inside: $(dr apps/smoke-in)"
[ "$(dr apps/smoke-out | jexpr "(d['ok'], d.get('code'))")" = "(False, 'docroot_outside')" ] && ok "docroot-check: a link that leads outside the home directory is refused" || bad "docroot-check link outside: $(dr apps/smoke-out)"
[ "$(dr apps/smoke-out/new | jexpr "(d['ok'], d.get('code'))")" = "(False, 'docroot_outside')" ] && ok "docroot-check: a missing directory below a link outside is refused" || bad "docroot-check below a link outside: $(dr apps/smoke-out/new)"
[ "$(dr apps/smoke-up | jexpr "(d['ok'], d.get('code'))")" = "(False, 'docroot_outside')" ] && ok "docroot-check: a link to the home directory itself is refused" || bad "docroot-check home itself: $(dr apps/smoke-up)"
[ "$(dr apps/smoke-pub/file.txt | jexpr "(d['ok'], d.get('code'))")" = "(False, 'docroot_not_dir')" ] && ok "docroot-check: a file is not a document root" || bad "docroot-check file: $(dr apps/smoke-pub/file.txt)"
for bad_root in "../etc" "apps/-x" "apps/./x" "apps//x" "apps/a b"; do
    [ "$(dr "$bad_root" | jexpr "d['ok']")" = "False" ] && ok "docroot-check refuses \"$bad_root\"" || bad "docroot-check accepted \"$bad_root\""
done
# docroot-access: o+x for the directories the web server group cannot pass (Runway's 0750 psacln
# directories), nothing else; Plesk's own directories (group psaserv) stay as they are.
# Directly below the home directory, so that the mode of apps (which depends on how the container
# was prepared) plays no part.
runuser -u "$USER_NAME" -- bash -c "umask 027; mkdir -p '$HOME_DIR/smoke-acc/app/wwwroot'"
out=$(call docroot-access "{\"sysuser\": \"$USER_NAME\", \"document_root\": \"smoke-acc/app/wwwroot\"}")
modes="$(stat -c %a "$HOME_DIR/smoke-acc") $(stat -c %a "$HOME_DIR/smoke-acc/app") $(stat -c %a "$HOME_DIR/smoke-acc/app/wwwroot")"
[ "$modes" = "751 751 751" ] \
    && [ "$(echo "$out" | jexpr "d['blocked'] == [] and d['changed'] == ['smoke-acc', 'smoke-acc/app', 'smoke-acc/app/wwwroot']")" = "True" ] \
    && ok "docroot-access: o+x on the directories the web server cannot pass ($modes)" || bad "docroot-access: modes $modes, $out"
chgrp psaserv "$HOME_DIR/smoke-acc/app/wwwroot" && chmod 750 "$HOME_DIR/smoke-acc/app/wwwroot"
[ "$(call docroot-access "{\"sysuser\": \"$USER_NAME\", \"document_root\": \"smoke-acc/app/wwwroot\"}" | jexpr "d['changed']")" = "[]" ] \
    && [ "$(stat -c %a "$HOME_DIR/smoke-acc/app/wwwroot")" = "750" ] && ok "docroot-access: a directory of the group psaserv (Plesk's) stays 0750" || bad "docroot-access psaserv: $(stat -c '%a %G' "$HOME_DIR/smoke-acc/app/wwwroot")"
[ "$(call docroot-access "{\"sysuser\": \"$USER_NAME\", \"document_root\": \"apps/smoke-out\"}" | jexpr "(d['ok'], d.get('code'))")" = "(False, 'docroot_outside')" ] \
    && [ "$(stat -c %a /etc)" = "755" ] && ok "docroot-access: never follows a link outside the home directory" || bad "docroot-access through a link outside"
rm -rf "$HOME_DIR/apps/smoke-pub" "$HOME_DIR/smoke-acc" "$HOME_DIR/apps/smoke-out" "$HOME_DIR/apps/smoke-in" "$HOME_DIR/apps/smoke-up"

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

echo "== zero-downtime deployments (docs/DESIGN.md section 12)"
# The fake domain smoke.test has no vhost: an nginx test server on 127.0.0.1 uses the switchable
# snippets (tcp: the include on ZD_TCP_PORT, unix: the root link on ZD_UNIX_PORT), and a fake
# generated configuration carries the marker the switch looks for. A request loop counts every
# answer that is not 2xx while the switches run.
ZD_ROOT=apps/smoke-zd
ZD_APP=$HOME_DIR/$ZD_ROOT
ZD_TCP_PORT=18990
ZD_UNIX_PORT=18991
ZD_NGINX=/etc/nginx/conf.d/zz-runway-smoke-zd.conf
ZD_VHOSTS=$(awk '$1 == "HTTPD_VHOSTS_D" {print $2}' /etc/psa/psa.conf 2>/dev/null)
ZD_CONF=${ZD_VHOSTS:-/var/www/vhosts}/system/smoke.test/conf
ZD_TMP=$(mktemp -d /root/runway-zd-XXXXXX)
ZD_FAULT=/var/lib/runway/test-switch-fault
LOOP_PID=""
zd_cleanup() {
    [ -n "$LOOP_PID" ] && touch "$ZD_TMP/stop" && wait "$LOOP_PID" 2>/dev/null
    rm -f "$ZD_NGINX" "$ZD_FAULT"
    rm -rf "${ZD_CONF%/conf}" "$ZD_TMP"
    systemctl reload nginx >/dev/null 2>&1
}
mkdir -p "$ZD_APP" "$ZD_CONF"
printf 'module smokezd\n\ngo 1.22\n' > "$ZD_APP/go.mod"
cat > "$ZD_APP/main.go" <<'EOF'
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	if d, err := time.ParseDuration(os.Getenv("ZD_DELAY")); err == nil {
		time.Sleep(d)
	}
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "zd %s", os.Getenv("RUNWAY_SLOT"))
	})
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if os.Getenv("ZD_FAIL") != "" {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		// ZD_STATUS: a JSON answer {"status": "<value>"} for the expected response content.
		if s := os.Getenv("ZD_STATUS"); s != "" {
			fmt.Fprintf(w, `{"status": %q}`, s)
			return
		}
		fmt.Fprint(w, "ok")
	})
	var ln net.Listener
	var err error
	if sock := os.Getenv("RUNWAY_SOCKET"); sock != "" {
		if p := os.Getenv("ZD_BIND"); p != "" {
			// Like gunicorn and asyncio: remove whatever is at the path, then bind it.
			os.Remove(p)
			sock = p
		}
		ln, err = net.Listen("unix", sock)
	} else {
		ln, err = net.Listen("tcp", os.Getenv("LISTEN_ADDR"))
	}
	if err != nil {
		panic(err)
	}
	fmt.Println("listening on", ln.Addr())
	// SIGTERM closes the listener, and a unix listener unlinks its path (as Go servers, gunicorn
	// and uvicorn do): an old slot must not break the active one.
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM)
	go func() {
		<-stop
		ln.Close()
		os.Exit(0)
	}()
	http.Serve(ln, nil)
}
EOF
chown -R "$USER_NAME":psacln "$ZD_APP"
cat > "$ZD_TMP/loop.py" <<'PYEOF'
import http.client, os, sys, threading, time
port, out, stop = int(sys.argv[1]), sys.argv[2], sys.argv[3]
lock = threading.Lock()
count = {"ok": 0, "bad": 0}
bad = []
def worker():
    while not os.path.exists(stop):
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/", headers={"Connection": "close"})
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
cat > "$ZD_NGINX" <<EOF
# tests/helper-smoke.sh: the switchable snippets of the fake domain smoke.test (#$ID)
server {
    listen 127.0.0.1:$ZD_TCP_PORT;
    location / {
        set \$runway_upstream "unix:/run/runway/$ID.none:";
        include /etc/runway/web/$ID.nginx[.]conf;
        proxy_pass http://\$runway_upstream;
        proxy_set_header Host smoke.test;
    }
}
server {
    listen 127.0.0.1:$ZD_UNIX_PORT;
    location / {
        proxy_pass http://unix:/run/runway/$ID.sock:;
        proxy_set_header Host smoke.test;
    }
}
EOF
printf '# tests/helper-smoke.sh: generated configuration of smoke.test\n# Runway: zero-downtime #%s\ninclude /etc/runway/web/%s.nginx[.]conf;\nproxy_pass http://unix:/run/runway/%s.sock:;\n' "$ID" "$ID" "$ID" > "$ZD_CONF/nginx.conf"
nginx -t >/dev/null 2>&1 && systemctl reload nginx && ok "nginx test server for the switchable snippets" || bad "nginx test server: $(nginx -t 2>&1 | tail -2)"

zd_base() { # zd_base [ENV-JSON]: the payload of the test application (the variables are always sent)
    local env=${1:-'{}'}
    cat <<EOF
"env": $env,
"domain_id": $ID, "domain": "smoke.test", "sysuser": "$USER_NAME", "app_root": "$ZD_ROOT",
"runtime": "go", "toolchain": "$GO_VERSION", "build_cmd": "go build -o bin/app .", "start_cmd": "./bin/app",
"port": 0, "port_range": [29900, 29999], "enabled": true, "auto_deploy": false, "build_timeout": 600, "limits": {},
"health_path": "/healthz", "ready_timeout": 20, "drain_seconds": 2
EOF
}
zd_status() { call app-status "{\"domain_id\": $ID}"; }
loop_start() { rm -f "$ZD_TMP/stop" "$ZD_TMP/loop.out"; python3 "$ZD_TMP/loop.py" "$1" "$ZD_TMP/loop.out" "$ZD_TMP/stop" & LOOP_PID=$!; sleep 1; }
loop_stop() { # loop_stop NAME: every answer during the loop must be 2xx
    local n_ok=0 n_bad=1 rest="no output of the request loop"
    touch "$ZD_TMP/stop"; wait "$LOOP_PID" 2>/dev/null; LOOP_PID=""
    [ -f "$ZD_TMP/loop.out" ] && read -r n_ok n_bad rest < "$ZD_TMP/loop.out"
    [ "${n_bad:-1}" = "0" ] && [ "${n_ok:-0}" -gt 50 ] && ok "$1: $n_ok requests through nginx, none failed" || bad "$1: $n_ok ok, $n_bad failed ($rest)"
}
wait_listening() { for _ in $(seq 1 30); do [ "$(zd_status | field "['listener']")" = "ok" ] && return 0; sleep 1; done; return 1; }
slot_now() { zd_status | field "['slot']"; }
job_msg() { call job-status "{\"job\": \"deploy-$ID\"}" | jexpr "(d['state'], d.get('message'))"; }

echo "-- tcp"
out=$(call app-apply "{$(zd_base), \"listen\": \"tcp\", \"start\": false}")
call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && wait_listening && ok "classic unit built and running (setting off)" || bad "classic unit: $(tail -4 /var/lib/runway/jobs/deploy-$ID.log)"
ZD_PORT=$(echo "$out" | field "['port']")
out=$(call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": true, \"restart\": false}")
[ "$(echo "$out" | jexpr "(d['switchable'], d['job'], d['state']['slot'], d['state']['port_a'] == $ZD_PORT, d['state']['port_b'] not in (0, $ZD_PORT))")" = "(True, None, '', True, True)" ] && ok "turning it on: switchable, slot b gets its own port, nothing restarted" || bad "turning on: $out"
[ "$(grep -c "^set \$runway_upstream 127.0.0.1:$ZD_PORT;$" /etc/runway/web/$ID.nginx.conf 2>/dev/null)" = "1" ] && [ "$(stat -c '%U %a' /etc/runway/web/$ID.nginx.conf)" = "root 644" ] && ok "include file names the classic unit's port (root 0644)" || bad "include: $(cat /etc/runway/web/$ID.nginx.conf 2>&1)"
grep -q "^SocketBindAllow=tcp:$(echo "$out" | field "['state']['port_b']")$" /etc/systemd/system/runway-app-$ID-b.service && grep -q '^RUNWAY_SLOT="b"' /etc/runway/env/$ID-b.env \
    && grep -q '^SyslogIdentifier=runway-app-999-b$' /etc/systemd/system/runway-app-$ID-b.service && ok "slot units: own port, RUNWAY_SLOT, journal identifier" || bad "slot unit b: $(grep -E 'SocketBind|Syslog' /etc/systemd/system/runway-app-$ID-b.service)"
grep -q '^TimeoutStopSec=300$' /etc/systemd/system/runway-deploy-$ID.service && ok "deploy unit of a switchable app: TimeoutStopSec covers an interrupted switch" || bad "deploy unit: $(grep Timeout /etc/systemd/system/runway-deploy-$ID.service)"
[ "$(systemctl is-enabled runway-converge.service 2>&1)" = "enabled" ] && ok "boot unit runway-converge.service installed" || bad "runway-converge.service: $(systemctl is-enabled runway-converge.service 2>&1)"
loop_start $ZD_TCP_PORT
out=$(call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}")
[ "$(echo "$out" | field "['job']")" = "deploy-$ID" ] && [ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "b" ] && ok "first switch: the classic unit to slot b" || bad "first switch: $out $(job_msg)"
[ ! -e /etc/systemd/system/runway-app-$ID.service ] && [ ! -e /etc/runway/env/$ID.env ] && ok "the classic unit was retired" || bad "classic unit left over"
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "a" ] && ok "restart switches to slot a" || bad "restart: $(job_msg)"
[ "$(zd_status | jexpr "all(set(['memory_bytes', 'memory_used_bytes', 'memory_cache_bytes']) <= set(s) for s in d['slots'].values()) and d['slots']['a']['memory_used_bytes'] is not None")" = "True" ] \
    && [ "$(call apps-list '{}' | jexpr "[a['memory_used_bytes'] is not None and 'memory_cache_bytes' in a for a in d['apps'] if a['domain_id'] == $ID][0]")" = "True" ] \
    && ok "slots and apps-list report the used memory and the file cache per slot" || bad "slot memory: $(zd_status | jexpr "d['slots']")"
# Turning it off from slot a, which holds the classic unit's port: the classic unit gets a new
# port. A later apply with the panel's old port and no restart (the Reconcile that follows) keeps
# the port the classic unit listens on (docs/DESIGN.md section 12.8); then it is turned on again.
call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": false}" >/dev/null
st=$(wait_job deploy-$ID)
OFF_PORT=$(zd_status | field "['port']")
[ "$st" = "succeeded" ] && [ "$(slot_now)" = "" ] && [ "$OFF_PORT" != "$ZD_PORT" ] && grep -q "gets port $OFF_PORT" /var/lib/runway/jobs/deploy-$ID.log \
    && [ ! -e /etc/systemd/system/runway-app-$ID-a.service ] && ok "turning it off from slot a: the classic unit gets port $OFF_PORT (slot a held $ZD_PORT), the slots are retired" \
    || bad "turning off from slot a: $st $(job_msg) port $OFF_PORT"
out=$(call app-apply "{$(zd_base), \"port\": $ZD_PORT, \"listen\": \"tcp\", \"zero_downtime\": false, \"restart\": false}")
[ "$(echo "$out" | jexpr "(d['port'], d['switchable'], d['job'])")" = "($OFF_PORT, False, None)" ] && grep -q "^PORT=\"$OFF_PORT\"$" /etc/runway/env/$ID.env \
    && [ "$(curl -s --max-time 5 http://127.0.0.1:$OFF_PORT/)" = "zd " ] && ok "a re-apply with the panel's old port keeps the port the classic unit listens on" \
    || bad "re-apply after turning off: $out $(grep '^PORT=' /etc/runway/env/$ID.env)"
call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": true, \"restart\": false}" >/dev/null
call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "b" ] && [ "$(systemctl is-active runway-app-$ID-a)" != "active" ] && ok "build & restart switches back to slot b, slot a stops" || bad "deploy switch: $(job_msg)"
call app-apply "{$(zd_base '{"ZD_FAIL": "1"}'), \"listen\": \"tcp\", \"zero_downtime\": true}" >/dev/null
st=$(wait_job deploy-$ID)
[ "$st" = "failed" ] && job_msg | grep -q 'was not ready within 20 s (HTTP 503 from /healthz)' && [ "$(slot_now)" = "b" ] && [ "$(systemctl is-active runway-app-$ID-a)" != "active" ] \
    && ok "a new version that fails its health check is stopped, the old one keeps serving" || bad "failed health: $st $(job_msg)"
# A new version that answers 200 without the expected response content never gets traffic.
call app-apply "{$(zd_base '{"ZD_STATUS": "starting"}'), \"listen\": \"tcp\", \"zero_downtime\": true, \"health_match\": \"{\\\"status\\\": \\\"ok\\\"}\"}" >/dev/null
st=$(wait_job deploy-$ID)
[ "$st" = "failed" ] && job_msg | grep -q 'was not ready within 20 s (HTTP 200 from /healthz, expected content not found)' && [ "$(slot_now)" = "b" ] \
    && [ "$(systemctl is-active runway-app-$ID-a)" != "active" ] && [ "$(curl -s --max-time 5 http://127.0.0.1:$ZD_TCP_PORT/)" = "zd b" ] \
    && ok "a new version without the expected response content is stopped, the old one keeps serving" || bad "readiness with expected content: $st $(job_msg)"
STANDBY=$(zd_status | jexpr "d['slots']['a']['endpoint'].split(':')[1]")
runuser -u nobody -- python3 -c "import socket,time; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', $STANDBY)); s.listen(); time.sleep(60)" &
SQUAT=$!
sleep 1
[ "$(zd_status | field "['standby_listener']")" = "foreign" ] && ok "status reports a foreign holder of the standby port" || bad "standby: $(zd_status | jexpr "d.get('standby_listener')")"
call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": true}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "a" ] && grep -q 'gets port' /var/lib/runway/jobs/deploy-$ID.log \
    && [ "$(zd_status | jexpr "d['port'] != $STANDBY")" = "True" ] && ok "a held standby port moves to another port, the switch succeeds" || bad "squatted standby: $(job_msg)"
kill $SQUAT 2>/dev/null; wait $SQUAT 2>/dev/null
LIVE=$(slot_now)
echo "kill:moved" > "$ZD_FAULT"
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
sleep 2
for _ in $(seq 1 60); do case "$(systemctl is-active runway-deploy-$ID.service)" in active|activating|deactivating) sleep 1 ;; *) break ;; esac; done
rm -f "$ZD_FAULT"
st=$(python3 -c "import json; d = json.load(open('/var/lib/runway/apps/$ID.json')); print((d['slot'], (d.get('switch') or {}).get('phase')))")
[ "$st" = "('$LIVE', 'switching')" ] && ok "a job killed after the traffic moved leaves its intent record" || bad "killed job state: $st"
"$H" _converge
st=$(python3 -c "import json; d = json.load(open('/var/lib/runway/apps/$ID.json')); print((d['slot'], d.get('switch')))")
[ "$st" != "('$LIVE', None)" ] && [ "$(echo "$st" | cut -c3)" != "$LIVE" ] && [ "$(systemctl is-active runway-app-$ID-$LIVE)" != "active" ] \
    && journalctl -u runway-app-$ID.service -n 20 --no-pager | grep -q 'settled an interrupted switch' && ok "the convergence completes the switch from the pointer ($st)" || bad "convergence after kill: $st"
loop_stop "tcp: turning on, restart, build, failed health, missing content, held standby port, killed job"
call app-apply "{$(zd_base '{"ZD_DELAY": "6s"}'), \"listen\": \"tcp\", \"zero_downtime\": true}" >/dev/null
for _ in $(seq 1 40); do [ "$(call job-status "{\"job\": \"deploy-$ID\"}" | field "['phase']" 2>/dev/null)" = "waiting" ] && break; sleep 0.5; done
call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": true}" | grep -q 'A deployment is running' && ok "a save is refused while a switch runs" || bad "app-apply during a switch was not refused"
call app-action "{\"domain_id\": $ID, \"action\": \"stop\"}" >/dev/null
st=$(wait_job deploy-$ID)
[ "$st" = "succeeded" ] && job_msg | grep -q 'stopped during the switch' && [ "$(systemctl is-active runway-app-$ID-a runway-app-$ID-b | sort -u | tr '\n' ' ')" = "inactive " ] \
    && [ "$(zd_status | field "['stopped']")" = "True" ] && ok "Stop during a switch stops both versions and persists" || bad "stop during switch: $st $(job_msg) $(systemctl is-active runway-app-$ID-a runway-app-$ID-b)"
call app-action "{\"domain_id\": $ID, \"action\": \"start\"}" >/dev/null
wait_listening && ok "Start runs the live slot again" || bad "start after stop: $(zd_status | jexpr "(d['slot'], d['listener'])")"

echo "-- unix"
out=$(call app-apply "{$(zd_base), \"listen\": \"unix\", \"zero_downtime\": true}")
st=$(wait_job deploy-$ID)
wait_listening && [ "$(slot_now)" != "" ] && [ "$(readlink /run/runway/$ID.sock)" = "$ID/$(slot_now).sock" ] && [ "$(stat -c '%U' /run/runway/$ID.sock)" = "root" ] \
    && ok "listen mode change: plain restart, the root link names the live slot ($(readlink /run/runway/$ID.sock))" || bad "unix apply: $st $out $(ls -la /run/runway/ 2>&1)"
grep -q "^L /run/runway/$ID.sock - - - - $ID/$(slot_now).sock$" /etc/tmpfiles.d/runway-$ID.conf && ok "tmpfiles entry recreates the root link at boot" || bad "tmpfiles: $(cat /etc/tmpfiles.d/runway-$ID.conf)"
runuser -u "$USER_NAME" -- rm -f /run/runway/$ID.sock 2>/dev/null; [ -L /run/runway/$ID.sock ] && ok "the customer cannot remove the root link" || bad "the customer removed the root link"
loop_start $ZD_UNIX_PORT
for round in 1 2; do
    before=$(slot_now)
    call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
    [ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" != "$before" ] && ok "unix restart $round: slot $before to slot $(slot_now)" || bad "unix restart $round: $(job_msg)"
done
OLD=$([ "$(slot_now)" = "a" ] && echo b || echo a)
[ ! -e /run/runway/$ID/$OLD.sock ] && [ -S /run/runway/$ID/$(slot_now).sock ] && ok "the old slot unlinked its own socket on exit, the live one stays" || bad "sockets: $(ls -la /run/runway/$ID)"
LIVE=$(slot_now)
echo "kill:moved" > "$ZD_FAULT"
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
sleep 2
for _ in $(seq 1 60); do case "$(systemctl is-active runway-deploy-$ID.service)" in active|activating|deactivating) sleep 1 ;; *) break ;; esac; done
rm -f "$ZD_FAULT"
"$H" _converge
[ "$(slot_now)" != "$LIVE" ] && [ "$(readlink /run/runway/$ID.sock)" = "$ID/$(slot_now).sock" ] && [ "$(systemctl is-active runway-app-$ID-$LIVE)" != "active" ] \
    && grep -q "$ID/$(slot_now).sock" /etc/tmpfiles.d/runway-$ID.conf && ok "unix: the convergence completes a switch whose job was killed after the link moved" || bad "unix convergence: $(slot_now) $(readlink /run/runway/$ID.sock)"
loop_stop "unix: two restarts and a killed job"
STANDBY=$([ "$(slot_now)" = "a" ] && echo b || echo a)
runuser -u "$USER_NAME" -- ln -sfn /run/runway/elsewhere.sock /run/runway/$ID/$STANDBY.sock
[ "$(zd_status | jexpr "(d['tampered'], 'replaced by a symbolic link' in d['tampered_detail'])")" = "(True, True)" ] && [ ! -L /run/runway/$ID/$STANDBY.sock ] \
    && [ "$(systemctl is-active runway-app-$ID-a runway-app-$ID-b | sort -u | tr '\n' ' ')" = "inactive " ] && ok "a symbolic link at a slot socket is contained (both slots stopped)" || bad "slot tampering: $(zd_status | jexpr "(d['tampered'], d.get('tampered_detail'))")"
call app-action "{\"domain_id\": $ID, \"action\": \"start\"}" >/dev/null
wait_listening && [ "$(zd_status | field "['tampered']")" = "False" ] && ok "Start runs it again; the root link is accepted" || bad "start after slot tampering"
LIVE=$(slot_now)
systemctl stop runway-app-$ID-$LIVE
rm -rf /run/runway/$ID /run/runway/$ID.sock
systemd-tmpfiles --create /etc/tmpfiles.d/runway-$ID.conf
[ "$(readlink /run/runway/$ID.sock)" = "$ID/$LIVE.sock" ] && [ "$(stat -c '%U:%G %a' /run/runway/$ID)" = "$USER_NAME:psaserv 2750" ] && ok "boot: systemd-tmpfiles recreates the directory and the root link" || bad "tmpfiles boot: $(ls -la /run/runway 2>&1)"
systemctl start runway-app-$ID-$LIVE
wait_listening && [ "$(curl -s --max-time 5 http://127.0.0.1:$ZD_UNIX_PORT/)" = "zd $LIVE" ] && ok "the live slot serves through the recreated link" || bad "after boot simulation: $(curl -s --max-time 5 http://127.0.0.1:$ZD_UNIX_PORT/)"
loop_start $ZD_UNIX_PORT
# Turning it off, with the job killed right after it committed the switch back to the classic unit:
# the intent record keeps the application switchable until the convergence has settled it.
LIVE=$(slot_now)
echo "kill:committed" > "$ZD_FAULT"
call app-apply "{$(zd_base), \"listen\": \"unix\", \"zero_downtime\": false}" >/dev/null
sleep 2
for _ in $(seq 1 60); do case "$(systemctl is-active runway-deploy-$ID.service)" in active|activating|deactivating) sleep 1 ;; *) break ;; esac; done
rm -f "$ZD_FAULT"
st=$(python3 -c "import json; d = json.load(open('/var/lib/runway/apps/$ID.json')); print((d['slot'], (d.get('switch') or {}).get('to'), d['zero_downtime']))")
[ "$st" = "('', '', False)" ] && [ "$(systemctl is-active runway-app-$ID-$LIVE)" = "active" ] \
    && [ "$(call apps-list '{}' | jexpr "[(a['switchable'], a['switching']) for a in d['apps'] if a['domain_id'] == $ID][0]")" = "(True, True)" ] \
    && ok "a job killed after it committed the switch back to the classic unit leaves its intent record (still switchable)" || bad "killed turn-off: $st $(systemctl is-active runway-app-$ID-$LIVE)"
"$H" _converge
[ "$(slot_now)" = "" ] && [ "$(readlink /run/runway/$ID.sock)" = "$ID/app.sock" ] && [ "$(systemctl is-active runway-app-$ID-$LIVE)" != "active" ] \
    && [ "$(systemctl is-enabled runway-app-$ID.service)" = "enabled" ] && [ ! -e /etc/systemd/system/runway-app-$ID-a.service ] && [ ! -e /etc/runway/env/$ID-b.env ] \
    && grep -q "^L /run/runway/$ID.sock - - - - $ID/app.sock$" /etc/tmpfiles.d/runway-$ID.conf \
    && [ "$(python3 -c "import json; d = json.load(open('/var/lib/runway/apps/$ID.json')); print((d.get('switch'), d['port_a'], d['port_b']))")" = "(None, 0, 0)" ] \
    && ok "the convergence settles it: the classic unit serves and is enabled, the old slot stops, the slots are retired" \
    || bad "convergence of the killed turn-off: $(slot_now) $(readlink /run/runway/$ID.sock) $(systemctl is-active runway-app-$ID-$LIVE) $(ls /etc/systemd/system | grep "runway-app-$ID" | tr '\n' ' ')"
loop_stop "unix: turning it off (job killed after the commit)"
printf '# tests/helper-smoke.sh: the 1.0 snippet again\nproxy_pass http://unix:/run/runway/%s/app.sock:;\n' "$ID" > "$ZD_CONF/nginx.conf"
"$H" _converge
[ ! -e /run/runway/$ID.sock ] && [ "$(grep -v '^#' /etc/tmpfiles.d/runway-$ID.conf)" = "d /run/runway/$ID 2750 $USER_NAME psaserv -" ] \
    && [ "$(ls /etc/systemd/system | grep -c "^runway-app-$ID")" = "1" ] && ! grep -q 'RUNWAY_SLOT' /etc/runway/env/$ID.env && ok "back to the 1.0 layout once the snippet no longer uses the link" || bad "1.0 layout: $(ls -la /run/runway; cat /etc/tmpfiles.d/runway-$ID.conf)"
printf '# tests/helper-smoke.sh: generated configuration of smoke.test\n# Runway: zero-downtime #%s\nproxy_pass http://unix:/run/runway/%s.sock:;\n' "$ID" "$ID" > "$ZD_CONF/nginx.conf"
call app-apply "{$(zd_base "{\"ZD_BIND\": \"/run/runway/$ID/app.sock\"}"), \"listen\": \"unix\", \"zero_downtime\": true, \"restart\": false}" >/dev/null
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
st=$(wait_job deploy-$ID)
[ "$st" = "failed" ] && job_msg | grep -q "listens on /run/runway/$ID/app.sock instead of \$RUNWAY_SOCKET" && [ "$(slot_now)" = "" ] && ok "a new version that binds app.sock fails the first switch at once" || bad "app.sock hijack: $st $(job_msg)"
wait_listening && [ "$(curl -s --max-time 5 http://127.0.0.1:$ZD_UNIX_PORT/)" = "zd " ] && ok "the classic unit serves again (restarted in place when its socket was taken)" || bad "classic after hijack attempt: $(zd_status | jexpr "(d['slot'], d['listener'])")"
# A listen mode change while the classic unit is still the live instance: one plain restart, no
# switch (docs/DESIGN.md section 12.5).
out=$(call app-apply "{$(zd_base), \"listen\": \"tcp\", \"zero_downtime\": true}")
[ "$(echo "$out" | jexpr "(d['job'], d['state']['slot'], d['state']['restart_plain'])")" = "(None, '', False)" ] && wait_listening \
    && ok "a listen mode change while the classic unit is live restarts it in place" || bad "listen change with the classic unit: $out"
out=$(call app-apply "{$(zd_base), \"listen\": \"unix\", \"zero_downtime\": true}")
[ "$(echo "$out" | jexpr "(d['job'], d['state']['slot'])")" = "(None, '')" ] && wait_listening && ok "and back to unix, again in place" || bad "back to unix with the classic unit: $out"
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "b" ] && ok "without the hardcoded path the switch succeeds" || bad "switch after hijack test: $(job_msg)"
journalctl -u runway-app-$ID.service -u runway-app-$ID-a.service -u runway-app-$ID-b.service -n 200 --no-pager -o short-iso | grep -q 'runway-app-999-b\[' \
    && [ "$(call app-logs "{\"domain_id\": $ID, \"kind\": \"app\", \"lines\": 200}" | jexpr "'runway-app-999-b[' in d['log'] and 'switched from' in d['log']")" = "True" ] && ok "app-logs merges the slots' journals and Runway's notes" || bad "app-logs of the slots"
# A running slot that becomes a worker, with a build command: the build's restart runs the classic
# unit in place (the slots are retired); then back to unix with a live slot.
out=$(call app-apply "{$(zd_base), \"listen\": \"none\", \"mode\": \"worker\", \"start_cmd\": \"exec sleep 600\", \"start\": false}")
call app-deploy "{\"domain_id\": $ID, \"build\": true}" >/dev/null
st=$(wait_job deploy-$ID)
[ "$(echo "$out" | jexpr "(d['switchable'], d['state']['zero_downtime'], d['state']['restart_plain'])")" = "(False, False, True)" ] \
    && [ "$st" = "succeeded" ] && [ "$(slot_now)" = "" ] && [ "$(systemctl is-active runway-app-$ID.service)" = "active" ] \
    && [ ! -e /etc/systemd/system/runway-app-$ID-b.service ] && ok "a running slot that becomes a worker: the deployment restarts the classic unit, the slots are retired" \
    || bad "worker after a live slot: $st $(job_msg) $out"
call app-apply "{$(zd_base), \"listen\": \"unix\", \"zero_downtime\": true}" >/dev/null
wait_listening
call app-action "{\"domain_id\": $ID, \"action\": \"restart\"}" >/dev/null
[ "$(wait_job deploy-$ID)" = "succeeded" ] && [ "$(slot_now)" = "b" ] || bad "back to unix with a slot: $(job_msg)"
call app-apply "{$(zd_base), \"listen\": \"unix\", \"zero_downtime\": true, \"suspended\": true}" >/dev/null
[ "$(systemctl is-active runway-app-$ID-a runway-app-$ID-b | sort -u | tr '\n' ' ')" = "inactive " ] && [ "$(systemctl is-enabled runway-app-$ID-a runway-app-$ID-b | sort -u | tr '\n' ' ')" = "disabled " ] \
    && ok "suspension stops and disables both slots" || bad "suspend: $(systemctl is-active runway-app-$ID-a runway-app-$ID-b)"
res=$(python3 - "$USER_NAME" <<'PYEOF'
# Every slot renders its own endpoint, also into the runtime conventions (Java, .NET).
import importlib.machinery, importlib.util, pwd, sys
loader = importlib.machinery.SourceFileLoader("helper", "/opt/runway/bin/runway-helper")
spec = importlib.util.spec_from_loader("helper", loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)
pw = pwd.getpwnam(sys.argv[1])
found = []
for runtime, listen in (("java", "tcp"), ("dotnet", "tcp"), ("dotnet", "unix")):
    state, _ = helper.validate_app({"domain_id": 995, "domain": "slots.test", "sysuser": sys.argv[1], "app_root": "apps/smoke-zd",
                                    "runtime": runtime, "toolchain": "", "start_cmd": "./app", "port": 29995,
                                    "port_range": [29900, 29999], "enabled": True, "listen": listen, "zero_downtime": True})
    if listen == "tcp":
        # As app-apply: slot a keeps the port, slot b gets its own. Unix mode allocates no slot ports.
        state.update({"port_a": 29995, "port_b": 29994})
    for slot in ("a", "b"):
        env = helper.render_env_file(helper.slot_view(state, slot), pw)
        port = "29995" if slot == "a" else "29994"
        found.append(all(line in env for line in (
            ['SERVER_PORT="%s"' % port, 'QUARKUS_HTTP_PORT="%s"' % port, 'PORT="%s"' % port] if runtime == "java" else
            ['ASPNETCORE_URLS="http://127.0.0.1:%s"' % port] if listen == "tcp" else
            ['ASPNETCORE_URLS="http://unix:/run/runway/995/%s.sock"' % slot, 'RUNWAY_SOCKET="/run/runway/995/%s.sock"' % slot]))
            and 'RUNWAY_SLOT="%s"' % slot in env)
print(found)
PYEOF
)
[ "$res" = "[True, True, True, True, True, True]" ] && ok "each slot renders its own port or socket into SERVER_PORT, QUARKUS_HTTP_PORT and ASPNETCORE_URLS" || bad "slot endpoints of Java/.NET: $res"
if [ -f /root/runway-helper-1.0.0 ]; then
    # Applications without the setting render byte-identical files: compare with the 1.0.0 helper.
    res=$(python3 - "$USER_NAME" "$HOME_DIR" <<'PYEOF'
import importlib.machinery, importlib.util, json, pwd, sys
def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
old = load("helper_old", "/root/runway-helper-1.0.0")
new = load("helper_new", "/opt/runway/bin/runway-helper")
user, home = sys.argv[1], sys.argv[2]
pw = pwd.getpwnam(user)
diffs = []
# The one later change of a 1.0 unit: a unit with a memory or CPU limit gets this line on systemd
# 254 and later (docs/DESIGN.md section 7, limits).
watch = "MemoryPressureWatch=off\n"
for listen in ("tcp", "unix", "none"):
    for limits in ({}, {"memory_mb": 256}):
        payload = {"domain_id": 996, "domain": "same.test", "sysuser": user, "app_root": "apps/smoke-zd", "runtime": "go",
                   "toolchain": "", "build_cmd": "go build", "start_cmd": "./bin/app", "port": 29996, "port_range": [29900, 29999],
                   "enabled": True, "auto_deploy": True, "build_timeout": 600, "limits": limits, "listen": listen,
                   "health_path": "/h", "env": {"A": "x y"}}
        s_old, _ = old.validate_app(dict(payload))
        s_new, _ = new.validate_app(dict(payload))
        if old.render_env_file(s_old, pw) != new.render_env_file(s_new, pw):
            diffs.append("%s %s render_env_file" % (listen, limits))
        unit_old, unit_new = old.render_app_unit(s_old, pw), new.render_app_unit(s_new, pw)
        expected = bool(limits) and new.cached_systemd_version() >= 254
        if unit_new.count(watch) != int(expected) or unit_new.replace(watch, "") != unit_old:
            diffs.append("%s %s render_app_unit" % (listen, limits))
        for name in ("render_deploy_service", "render_deploy_path"):
            if getattr(old, name)(s_old) != getattr(new, name)(s_new):
                diffs.append("%s %s %s" % (listen, limits, name))
        # The expected response content of the health check never reaches a unit or env file.
        s_match, _ = new.validate_app(dict(payload, health_match='{"status": "ok"}'))
        if s_match["health_match"] != ("" if listen == "none" else '{"status": "ok"}'):
            diffs.append("%s %s health_match %r" % (listen, limits, s_match["health_match"]))
        if (new.render_env_file(s_match, pw), new.render_app_unit(s_match, pw), new.render_deploy_service(s_match),
                new.render_deploy_path(s_match)) != (new.render_env_file(s_new, pw), unit_new, new.render_deploy_service(s_new),
                                                     new.render_deploy_path(s_new)):
            diffs.append("%s %s files depend on health_match" % (listen, limits))
print("same" if not diffs else "different: " + ", ".join(diffs))
PYEOF
)
    [ "$res" = "same" ] && ok "applications without the setting render the files of the 1.0.0 helper byte for byte (with a memory limit and systemd 254+: plus MemoryPressureWatch=off; an expected response content changes no file)" || bad "1.0 rendering: $res"
else
    echo "SKIP  byte-identical 1.0 rendering (no /root/runway-helper-1.0.0; plesk-e2e.sh smoke copies it from git)"
fi
call app-remove "{\"domain_id\": $ID}" >/dev/null
left=$(ls /etc/systemd/system/runway-app-$ID* /etc/runway/env/$ID* /etc/runway/web/$ID.* /etc/tmpfiles.d/runway-$ID.conf /run/runway/$ID.sock /run/runway/$ID 2>/dev/null | tr '\n' ' ')
[ -z "$left" ] && ok "app-remove deletes both slots, their env files, the root link and the include files" || bad "left after app-remove: $left"
zd_cleanup

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
    # A running application has to survive the upgrade; the zero-downtime section removed the
    # one of the earlier sections, so deploy the tcp sample again (sets PORT).
    sample_app binary "" tcp
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
