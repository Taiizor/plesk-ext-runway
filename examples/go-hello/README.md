# go-hello

Minimal Go web application (standard library only) for Runway.

| Setting | Value |
|---|---|
| Runtime | Go (any installed version, module requires Go 1.22+) |
| Build command | `go build -o bin/app .` |
| Start command | `./bin/app` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

Locally: `go run .` then `curl http://127.0.0.1:8080/`, or
`RUNWAY_SOCKET=/tmp/app.sock go run .` then `curl --unix-socket /tmp/app.sock http://localhost/`.
