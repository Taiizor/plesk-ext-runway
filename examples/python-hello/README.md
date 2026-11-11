# python-hello

Minimal Python web application using only the standard library (`http.server`) for Runway.

| Setting | Value |
|---|---|
| Runtime | Python 3.8 or newer (uv-managed CPython) |
| Build command | `uv venv .venv && uv pip install -r requirements.txt` (or empty) |
| Start command | `.venv/bin/python app.py` (or `python3 app.py`) |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

`requirements.txt` is intentionally empty so the default build command works unchanged. For a
framework app see [python-fastapi](../python-fastapi).

Locally: `python3 app.py` then `curl http://127.0.0.1:8080/`.
