# bun-hello

Minimal Bun web application (`Bun.serve`, TypeScript, no dependencies) for Runway.

| Setting | Value |
|---|---|
| Runtime | Bun |
| Build command | `bun install` (creates `bun.lock`; with a committed lock file use `bun install --frozen-lockfile`) |
| Start command | `bun run start` (= `bun run server.ts`) |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

`Bun.serve` binds `0.0.0.0` unless a hostname is given: the app passes `HOST` (127.0.0.1)
explicitly, keep that in your own apps. A stale socket file is removed at start, and the socket
is removed again on `SIGTERM`.

Locally: `bun run start` then `curl http://127.0.0.1:3000/`.
