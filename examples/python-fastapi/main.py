"""Minimal FastAPI app served by uvicorn, for testing Runway (Plesk extension).

Build: uv venv .venv && uv pip install -r requirements.txt
Start: .venv/bin/python main.py
       (listens on RUNWAY_SOCKET when it is set, else on HOST:PORT; the uvicorn command line
       alternatives are listed in README.md)
"""
import os
import sys

from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def hello():
    return {"hello": "Runway", "python": sys.version.split()[0]}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    sock = os.environ.get("RUNWAY_SOCKET")
    if sock:
        # Unix socket mode (recommended on shared servers). Behind a unix socket the client
        # address is empty, so the forwarded headers of nginx are trusted from any source.
        uvicorn.run(app, uds=sock, proxy_headers=True, forwarded_allow_ips="*")
    else:
        uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")),
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1")
