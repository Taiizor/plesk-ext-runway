# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Expected response content of the health check (opt-in, docs/DESIGN.md section 7, health_match)
#
# The response is untrusted output of a customer's application and this process runs as root:
# no regular expression is built from it or from the expected text, nothing is evaluated, the
# response is read up to HEALTH_BODY_MAX bytes within the check's deadline and json.loads()
# only ever sees that much (ValueError and RecursionError mean "not JSON"). The body never
# reaches a detail text or the params.
# ---------------------------------------------------------------------------

def _json_no_constant(name):
    """json.loads parse_constant: NaN and Infinity are not JSON (PHP's json_decode refuses them too)."""
    raise ValueError("%s is not JSON" % name)


def health_json_object(text):
    """The JSON object a text holds, or None (not JSON, nested too deeply, not an object)."""
    try:
        value = json.loads(text, parse_constant=_json_no_constant)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def health_expectation(state):
    """The expected response content of a state: None (off, or no health path), ("json", object)
    or ("text", UTF-8 bytes). app-status passes the stored state as it is, so anything that is not
    a valid value (validate_app refuses it) becomes ("json", None), which never matches."""
    value = state.get("health_match") if isinstance(state, dict) else None
    if not isinstance(value, str) or not state.get("health_path"):
        return None
    value = value.strip(HEALTH_MATCH_TRIM)
    if not value:
        return None
    if len(value) > HEALTH_MATCH_MAX or RE_CTRL_UNICODE.search(value):
        return ("json", None)
    if value.startswith("{"):
        return ("json", health_json_object(value))
    return ("text", value.encode("utf-8", "replace"))


def _http_header_end(data, start=0):
    """Offset of the body in a raw response (after the empty line that ends the headers; a bare
    LF is tolerated), -1 while it has not arrived."""
    ends = []
    crlf = data.find(b"\r\n\r\n", start)
    if crlf >= 0:
        ends.append(crlf + 4)
    lf = data.find(b"\n\n", start)
    if lf >= 0:
        ends.append(lf + 2)
    return min(ends) if ends else -1


def _http_headers(head):
    """{lower-case name: lower-case value} of the header block (status line skipped, 100 lines)."""
    headers = {}
    for line in head.replace(b"\r\n", b"\n").split(b"\n")[1:101]:
        name, sep, value = line.partition(b":")
        if sep:
            headers[name.strip().lower()] = value.strip().lower()
    return headers


def _http_content_length(headers):
    """The Content-Length of a response without chunked transfer coding, or None."""
    if b"chunked" in headers.get(b"transfer-encoding", b""):
        return None
    value = headers.get(b"content-length", b"")
    return int(value) if value.isdigit() and len(value) <= 12 else None


def health_read_response(sock, deadline):
    """Reads a health check response for the content check: status line, headers and body until
    the server closes the connection, the body of its Content-Length is complete or HEALTH_BODY_MAX
    bytes arrived. Every recv waits only for the time left until the deadline, so a server that
    sends slowly cannot extend it (socket.timeout)."""
    data = bytearray()
    limit = HEALTH_BODY_MAX
    body_at = -1
    while len(data) < limit:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise socket.timeout("timed out")
        sock.settimeout(remaining)
        chunk = sock.recv(min(16384, limit - len(data)))
        if not chunk:
            break
        searched = max(0, len(data) - 3)
        data += chunk
        if body_at < 0:
            body_at = _http_header_end(data, searched)
            if body_at >= 0:
                length = _http_content_length(_http_headers(bytes(data[:body_at])))
                if length is not None:
                    limit = min(HEALTH_BODY_MAX, body_at + length)
    return bytes(data)


def _decode_chunked(data):
    """The body of a chunked transfer coding: what arrived when it is cut off (at the read limit or
    by the server), None when it is malformed."""
    parts = []
    pos = 0
    size_of = len(data)
    while pos < size_of:
        end = data.find(b"\n", pos, pos + 1024)
        if end < 0:
            # A size line cut off by the read limit, or one that is far too long.
            return b"".join(parts) if size_of - pos < 1024 else None
        size = data[pos:end].rstrip(b"\r").split(b";", 1)[0].strip()
        if not RE_CHUNK_SIZE.fullmatch(size):
            return None
        size = int(size, 16)
        pos = end + 1
        if size == 0:
            break
        parts.append(data[pos:pos + size])
        pos += size
        if pos >= size_of or data[pos:] == b"\r":
            break
        if data[pos:pos + 2] == b"\r\n":
            pos += 2
        elif data[pos:pos + 1] == b"\n":
            pos += 1
        else:
            return None
    return b"".join(parts)


def health_response_body(data):
    """The body of a raw health check response (chunked transfer coding decoded, cut to its
    Content-Length); b"" without the end of the headers, None for a malformed chunked coding."""
    body_at = _http_header_end(data)
    if body_at < 0:
        return b""
    headers = _http_headers(data[:body_at])
    body = data[body_at:]
    if b"chunked" in headers.get(b"transfer-encoding", b""):
        return _decode_chunked(body)
    length = _http_content_length(headers)
    return body[:length] if length is not None else body


def _json_same(expected, actual):
    """Equality of two JSON values with their JSON types: "1" is not 1 and true is not 1 (Python's
    True == 1 must not count); numbers compare by value; arrays and objects in full."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and expected == actual
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and expected == actual
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(expected) == len(actual)
                and all(_json_same(item, other) for item, other in zip(expected, actual)))
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and len(expected) == len(actual)
                and all(key in actual and _json_same(value, actual[key]) for key, value in expected.items()))
    return False


def _json_contains(expected, actual):
    """Every key of the expected object is in the actual one with an equal value; nested objects are
    compared as subsets, everything else with _json_same."""
    if not isinstance(actual, dict):
        return False
    for key, value in expected.items():
        if key not in actual:
            return False
        if isinstance(value, dict):
            if not _json_contains(value, actual[key]):
                return False
        elif not _json_same(value, actual[key]):
            return False
    return True


def health_match_result(expect, data, code, path):
    """The result of a 2xx/3xx health check with an expected response content: healthy
    ("http_match") when the body contains it, else unhealthy ("body_mismatch", or "body_not_json"
    when a JSON object is expected and the body is none). The body never reaches the detail."""
    params = {"code": code, "path": path}
    mode, wanted = expect
    body = health_response_body(data)
    found = False
    if mode == "text":
        found = body is not None and wanted in body
    else:
        actual = None
        if body is not None:
            try:
                actual = health_json_object(body.decode("utf-8").lstrip("\ufeff"))
            except UnicodeDecodeError:
                actual = None
        if actual is None:
            return ("unhealthy", "HTTP %d from %s, the response is not a JSON object" % (code, path),
                    "body_not_json", params)
        try:
            found = wanted is not None and _json_contains(wanted, actual)
        except RecursionError:
            found = False
    if found:
        return "healthy", "HTTP %d from %s, expected content found" % (code, path), "http_match", params
    return "unhealthy", "HTTP %d from %s, expected content not found" % (code, path), "body_mismatch", params
