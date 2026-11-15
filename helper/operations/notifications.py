# Copyright 2026 Taiizor. Licensed under the MIT License.

class _OpsNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _user_send_notification(options, event):
    url = options["notification_url"]
    check_fetch_url(url, False, resolve=False)
    body = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > 8192:
        raise HelperError("Notification payload is too large")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "X-Runway-Event": event["event"]}
    if options["notification_secret"]:
        headers["X-Runway-Signature"] = "sha256=" + hmac.new(options["notification_secret"].encode("utf-8"), body,
                                                           hashlib.sha256).hexdigest()
    # No ambient proxies, redirects or repeat DNS lookup after public-address validation.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPSHandler(False), _OpsNoRedirect())
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with opener.open(request, timeout=5) as response:
        code = response.getcode()
        if not 200 <= code < 300:
            raise HelperError("Notification endpoint rejected the event")
    return {"state": "succeeded", "status": code}


def ops_notify(state, options, event):
    # A repeated paused-health event sends at most once every ten minutes.
    path = ops_dir(state["domain_id"]) + "/notification.json"
    previous = read_json(path, {}) or {}
    if event["event"] == "health_paused" and previous.get("event") == "health_paused" \
            and time.time() - float(previous.get("epoch") or 0) < 600:
        return
    try:
        pw = v_sysuser(state["sysuser"])
        result = call_as_user(pw, _user_send_notification, options, event, timeout=10)
    except Exception as exc:
        # HTTP exceptions include credential-bearing URLs; retain only the exception class.
        result = {"state": "failed", "error": type(exc).__name__}
    ensure_dir(ops_dir(state["domain_id"]), 0o700)
    write_json(path, dict(result, event=event["event"], time=now_iso(), epoch=time.time()))
