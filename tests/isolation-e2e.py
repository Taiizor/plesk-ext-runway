#!/usr/bin/env python3
# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Destructive-to-fixtures-only checks against a local disposable Plesk test subscription.

Requires the installed Runway package and bubblewrap. Uses the same CONTAINER, PANEL and
SITE_ID variables as runtime-e2e.sh. Restores the complete app configuration and isolation
policy, and removes only directories created with this run's unpredictable fixture token.
"""

import http.cookiejar
import json
import os
import subprocess
import time
import urllib.request
import uuid


CONTAINER = os.environ.get("CONTAINER", "runway-plesk")
PANEL = os.environ.get("PANEL", "http://localhost:18880").rstrip("/")
SITE_ID = int(os.environ.get("SITE_ID", "1"))


def docker(*args, data=None, user=None):
    command = ["docker", "exec"]
    if data is not None:
        command.append("-i")
    if user:
        command += ["-u", user]
    result = subprocess.run(command + [CONTAINER] + list(args), input=data, text=True,
                            capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError("A fixture command failed (%d): %s" % (result.returncode, result.stderr.strip()[:2000]))
    return result.stdout.strip()


class Panel:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        link = docker("plesk", "bin", "admin", "--get-login-link", "-relative-url")
        with self.opener.open(PANEL + link, timeout=30) as response:
            response.read(2 * 1024 * 1024)
        with self.opener.open(PANEL + "/modules/runway/index.php/overview", timeout=30) as response:
            html = response.read(2 * 1024 * 1024).decode("utf-8")
        import re
        match = re.search(r'id="forgery_protection_token" content="([^"]+)"', html)
        if not match:
            raise RuntimeError("The local test administrator could not log in")
        self.token = match.group(1)

    def request(self, path, body=None, error=False):
        if body is None:
            path += ("&" if "?" in path else "?") + "site_id=" + str(SITE_ID)
        else:
            body = dict(body, site_id=SITE_ID)
        request = urllib.request.Request(PANEL + "/modules/runway/index.php/api/" + path,
                                         data=None if body is None else json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest",
                                                  "X-Forgery-Protection-Token": self.token})
        with self.opener.open(request, timeout=120) as response:
            result = json.load(response)
        if error:
            if result.get("status") != "error":
                raise AssertionError("An invalid isolation request was accepted")
            return result
        if result.get("status") != "success":
            raise RuntimeError("Panel request %s failed: %s" % (path, result.get("errors")))
        return result["data"]

    def settle(self):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = self.request("app/status")
            job = status.get("deploy") or {}
            if job.get("state") not in ("running", "queued"):
                if job.get("state") == "failed":
                    raise AssertionError("The fixture deployment failed; inspect its deployment log")
                return status
            time.sleep(1)
        raise TimeoutError("The fixture deployment did not finish within three minutes")


PROBE = r'''import json,os,pathlib,socket,subprocess,time
p=json.loads(%r)
app=pathlib.Path.cwd()
checks={}
checks['sibling files hidden']=not pathlib.Path(p['sibling']).exists()
checks['symlink escape hidden']=not (app/'escape/secret').exists()
checks['private process namespace']=os.stat('/proc/self/ns/pid').st_ino != p['pid_ns']
checks['private network namespace']=os.stat('/proc/self/ns/net').st_ino != p['net_ns']
checks['private dependency home']=os.environ['HOME']==p['private_home']
checks['environment restored inside']=os.environ.get('FIXTURE_TOKEN')=='dummy-fixture-token' and os.environ.get('OPENSSL_CONF')=='/unavailable/fixture.conf'
checks['private transport removed']=not any(k.startswith('RUNWAY_ISOLATION_') for k in os.environ)
checks['no new privileges']=any(line.split()==['NoNewPrivs:','1'] for line in pathlib.Path('/proc/self/status').read_text().splitlines())
checks['nested user namespaces blocked']=subprocess.run(['/usr/bin/unshare','--user','--map-root-user','/bin/true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0
checks['isolated build wrote source']=(app/'build-ok').read_text()=='built'
try:
    (app/'source.txt').write_text('changed')
    checks['runtime source is read-only']=False
except OSError:
    checks['runtime source is read-only']=True
(app/'uploads/writable').write_text('allowed')
checks['declared uploads are writable']=(app/'uploads/writable').read_text()=='allowed'
checks['ungranted socket neighbour hidden']=not pathlib.Path(p['socket_dir']+'/not-granted').exists()
with socket.socket(socket.AF_UNIX) as client:
    client.settimeout(5)
    client.connect(p['socket'])
    checks['granted Unix service reachable offline']=client.recv(32)==b'dummy-database'
with socket.socket() as client:
    client.settimeout(1)
    try:
        client.connect(('192.0.2.1',80))
        checks['offline IP networking blocked']=False
    except OSError:
        checks['offline IP networking blocked']=True
checks['no inherited descriptors']=not [fd for fd in os.listdir('/proc/self/fd') if int(fd)>3]
(app/'uploads/results.json').write_text(json.dumps(checks))
print(json.dumps(checks),flush=True)
time.sleep(180)
'''


def main():
    panel = Panel()
    initial = panel.request("app")
    if not initial.get("configured") or initial.get("env") is None:
        raise RuntimeError("Use a configured disposable application with readable environment settings")
    original = dict(initial["config"], env=initial["env"])
    policy = panel.request("app/isolation")["options"]
    stopped = bool(initial["status"].get("stopped"))
    username = initial["domain"]["sysuser"]
    python = initial["toolchains"]["python"][0]
    toolchain = python["id"] if isinstance(python, dict) else python
    home = initial["domain"]["home"].rstrip("/")
    token = uuid.uuid4().hex
    root = "apps/runway-isolation-check-" + token
    sibling = home + "/apps/runway-isolation-sibling-" + token
    socket_dir = "/run/runway-isolation-check-" + token
    service = socket_dir + "/database.sock"
    public_url = "/runway-isolation-static-" + token
    public_path = home + "/" + initial["domain"]["documentRoot"].strip("/") + public_url
    protected = False
    params = {"sibling": sibling, "socket": service, "socket_dir": socket_dir,
              "private_home": home + "/.runway/isolation/%d/home" % SITE_ID}
    namespaces = json.loads(docker("python3", "-c", "import json,os; print(json.dumps({k:os.stat('/proc/self/ns/'+k).st_ino for k in ('pid','net')}))"))
    params.update(pid_ns=namespaces["pid"], net_ns=namespaces["net"])
    passed = 0

    def check(condition, message):
        nonlocal passed
        if not condition:
            raise AssertionError(message)
        passed += 1
        print("PASS  " + message, flush=True)

    try:
        panel.request("app/save", {"enabled": False, "runtime": "python", "toolchain": toolchain, "appRoot": root,
                                   "mode": "worker", "listen": "none", "staticPaths": [], "healthPath": "",
                                   "healthMatch": "", "healthWatch": False, "zeroDowntime": False, "autoDeploy": False,
                                   "startCmd": "/usr/bin/python3 -I probe.py", "buildCmd": ""})
        docker("python3", "-c", "import os,pwd,sys; p=pwd.getpwnam(sys.argv[1]); os.mkdir(sys.argv[2],0o755); os.chown(sys.argv[2],p.pw_uid,p.pw_gid)", username, socket_dir)
        files = {"source.txt": "immutable", "probe.py": PROBE % json.dumps(params),
                 "early.sh": "test ! -e '%s/secret' || exit 94\n" % sibling,
                 "build.py": "import pathlib; assert not pathlib.Path(%r).exists(); pathlib.Path('build-ok').write_text('built')\n" % sibling}
        fixture = {"home": home, "root": root, "sibling": sibling, "socket_dir": socket_dir, "files": files}
        docker("python3", "-c", "import json,pathlib,sys; p=json.load(sys.stdin); a=pathlib.Path(p['home'])/p['root']; s=pathlib.Path(p['sibling']); s.mkdir(); (s/'secret').write_text('dummy-secret'); (a/'escape').symlink_to(s,target_is_directory=True); [(a/n).write_text(v) for n,v in p['files'].items()]; pathlib.Path(p['socket_dir']+'/not-granted').write_text('dummy-neighbour')",
               data=json.dumps(fixture), user=username)
        server = "import pathlib,socket,sys,time; d=pathlib.Path(sys.argv[1]); s=socket.socket(socket.AF_UNIX); s.bind(str(d/'database.sock')); s.listen(4); s.settimeout(1); end=time.monotonic()+180\nwhile d.exists() and time.monotonic()<end:\n try:\n  c,_=s.accept(); c.sendall(b'dummy-database'); c.close()\n except TimeoutError: pass"
        subprocess.run(["docker", "exec", "-d", "-u", username, CONTAINER, "python3", "-c", server, socket_dir], check=True, timeout=30)
        for _ in range(30):
            if docker("python3", "-c", "import os,sys; print(os.path.exists(sys.argv[1]))", service) == "True":
                break
            time.sleep(0.1)
        options = {"enabled": True, "network": "offline", "writable_paths": ["uploads"], "socket_paths": [service]}
        panel.request("app/isolation", {"options": options})
        env = "FIXTURE_TOKEN=dummy-fixture-token\nOPENSSL_CONF=/unavailable/fixture.conf\nBASH_ENV=" + home + "/" + root + "/early.sh"
        panel.request("app/save", {"enabled": True, "env": env, "buildCmd": "/usr/bin/python3 -I build.py"})
        panel.settle()
        results = None
        for _ in range(30):
            try:
                results = json.loads(docker("cat", home + "/" + root + "/uploads/results.json", user=username))
                break
            except (RuntimeError, ValueError):
                time.sleep(1)
        check(isinstance(results, dict) and bool(results), "the isolated worker produced its result file")
        for message, value in results.items():
            check(value is True, message)
        unit = "runway-app-%d.service" % SITE_ID
        pid = docker("systemctl", "show", "-p", "MainPID", "--value", unit)
        memory = docker("systemctl", "show", "-p", "MemoryMax", "--value", unit)
        check(memory.isdigit() and int(memory) > 0, "the live isolated unit has a finite memory limit")
        check(" _isolate " in docker("systemctl", "cat", unit), "the live unit uses the common isolation launcher")
        for bad in (dict(options, writable_paths=["escape"]), dict(options, socket_paths=[socket_dir + "/not-granted"])):
            panel.request("app/isolation", {"options": bad}, error=True)
            check(panel.request("app/isolation")["options"] == options, "an invalid candidate keeps the existing administrator policy")
            check(docker("systemctl", "show", "-p", "MainPID", "--value", unit) == pid, "a rejected candidate leaves the confined process running")
        panel.request("app/save", {"listen": "tcp", "mode": "web"}, error=True)
        check(panel.request("app/isolation")["options"] == options, "an invalid offline TCP save cannot remove isolation")
        # The web server runs outside the app namespace. Verify both frontends and Plesk's
        # password protection, using harmless text files instead of executable payloads.
        extensions = ("php", "phtml", "py", "rb", "cgi", "pl", "jsp", "aspx", "shtml")
        public = {"path": public_path, "home": home, "token": token, "extensions": extensions}
        docker("python3", "-c", "import json,pathlib,sys; p=json.load(sys.stdin); d=pathlib.Path(p['path']); assert d.is_relative_to(pathlib.Path(p['home'])) and d.name.endswith(p['token']); d.mkdir(); (d/'protected').mkdir(); (d/'ok.txt').write_text('public-static-fixture'); (d/'protected/ok.css').write_text('protected-static-fixture'); (d/'.env').write_text('dummy-secret'); [(d/('blocked.'+ext)).write_text('must-not-be-served') for ext in p['extensions']]",
               data=json.dumps(public), user=username)
        panel.request("app/save", {"mode": "web", "listen": "unix", "staticPaths": [public_url],
                                   "buildCmd": "", "startCmd": "/bin/sleep 180"})
        domain = initial["domain"]["name"]
        docker("plesk", "bin", "protdir", "--create", public_url + "/protected", "-domain", domain,
               "-type", "wwwroot", "-title", "Runway isolation fixture")
        protected = True
        docker("plesk", "bin", "protdir", "--update", public_url + "/protected", "-domain", domain,
               "-add_user", "fixture", "-passwd", "Runway-Test!8-cxQ2#")
        address = docker("hostname", "-i").split()[0]

        def http(path, apache=False, body=False):
            port, ip = (7081, "127.0.0.1") if apache else (443, address)
            arguments = ["curl", "-sk", "--max-time", "5", "--resolve", "%s:%d:%s" % (domain, port, ip)]
            if not body:
                arguments += ["-o", "/dev/null", "-w", "%{http_code}"]
            return docker(*(arguments + ["https://%s:%d%s" % (domain, port, path)]))

        for _ in range(20):
            if http(public_url + "/ok.txt", body=True) == "public-static-fixture" and http(public_url + "/protected/ok.css") == "401":
                break
            time.sleep(1)
        for apache in (False, True):
            frontend = "Apache" if apache else "nginx"
            check(http(public_url + "/ok.txt", apache, body=True) == "public-static-fixture", frontend + " serves ordinary static downloads")
            for name in ["blocked." + ext for ext in extensions] + [".env", "blocked.php/path-info"]:
                check(http(public_url + "/" + name, apache) == "403", frontend + " denies static " + name)
            check(http(public_url + "/protected/ok.css", apache) == "401", frontend + " preserves Plesk password protection")
        print("%d isolation integration checks passed." % passed, flush=True)
    finally:
        if protected:
            docker("plesk", "bin", "protdir", "--remove", public_url + "/protected", "-domain", initial["domain"]["name"])
        panel.request("app/save", {"enabled": False})
        panel.request("app/isolation", {"options": {"enabled": False}})
        panel.request("app/save", original)
        panel.settle()
        panel.request("app/isolation", {"options": policy})
        panel.settle()
        if stopped:
            panel.request("app/control", {"op": "stop"})
        cleanup = {"home": home, "paths": [home + "/" + root, sibling, public_path], "socket_dir": socket_dir, "token": token}
        docker("python3", "-c", "import json,pathlib,shutil,sys; p=json.load(sys.stdin); h=pathlib.Path(p['home']); paths=[pathlib.Path(x) for x in p['paths']]; assert all(x.is_relative_to(h) and x.name.endswith(p['token']) for x in paths); [shutil.rmtree(x,ignore_errors=True) for x in paths]", data=json.dumps(cleanup), user=username)
        docker("python3", "-c", "import json,pathlib,shutil,sys; p=json.load(sys.stdin); d=pathlib.Path(p['socket_dir']); assert d.parent==pathlib.Path('/run') and d.name=='runway-isolation-check-'+p['token']; shutil.rmtree(d,ignore_errors=True)", data=json.dumps(cleanup))
        print("Restored the application and administrator policy; removed fixture directories.", flush=True)


if __name__ == "__main__":
    main()
