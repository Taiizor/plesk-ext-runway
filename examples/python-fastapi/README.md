# python-fastapi

Minimal FastAPI application served by uvicorn for Runway. The build downloads FastAPI and
uvicorn from PyPI (the deploy job needs outbound HTTPS).

| Setting | Value |
|---|---|
| Runtime | Python 3.9 or newer (uv-managed CPython) |
| Build command | `uv venv .venv && uv pip install -r requirements.txt` |
| Start command | `.venv/bin/python main.py` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

`main.py` starts uvicorn itself and picks the listener from the environment. The equivalent
uvicorn command lines are:

```sh
# TCP port
.venv/bin/uvicorn main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips 127.0.0.1
# Unix socket
.venv/bin/uvicorn main:app --uds $RUNWAY_SOCKET --proxy-headers --forwarded-allow-ips '*'
```

Do not use `fastapi run` as start command: it binds all interfaces by default and cannot listen
on a Unix socket. With a `pyproject.toml` and `uv.lock` use `uv sync --frozen --no-dev` as the
build command instead.
