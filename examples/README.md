# Runway examples

Minimal applications for a first test of every runtime. Each one listens on the Unix socket in
`RUNWAY_SOCKET` when Runway sets it (listen mode **Unix socket**; `PORT`, `HOST` and `LISTEN_ADDR`
are not set then) and on `HOST:PORT` otherwise (listen mode **TCP port**), and answers `GET /` with a short text. `GET /healthz` returns
HTTP 200 in every example, so it can be used as the health check path.

| Example | Runtime | Build command | Start command | Listen modes |
|---|---|---|---|---|
| [go-hello](go-hello) | Go | `go build -o bin/app .` | `./bin/app` | tcp, unix |
| [rust-hello](rust-hello) | Rust | `cargo build --release` | `./target/release/rust-hello` | tcp, unix |
| [bun-hello](bun-hello) | Bun | `bun install` | `bun run start` | tcp, unix |
| [java-hello](java-hello) | Java 21+ | `javac -d build App.java` | `java -XX:MaxRAMPercentage=75 -cp build App` | tcp, unix |
| [dotnet-hello](dotnet-hello) | .NET 10 | `dotnet publish -c Release -o publish` | `dotnet publish/app.dll` | tcp, unix |
| [python-hello](python-hello) | Python (stdlib) | `uv venv .venv && uv pip install -r requirements.txt` | `.venv/bin/python app.py` | tcp, unix |
| [python-fastapi](python-fastapi) | Python (FastAPI + uvicorn) | `uv venv .venv && uv pip install -r requirements.txt` | `.venv/bin/python main.py` | tcp, unix |
| [ruby-hello](ruby-hello) | Ruby (Rack + puma) | `bundle install` | `bundle exec puma -C config/puma.rb -e production` | tcp, unix |
| [php-hello](php-hello) | PHP | none | `frankenphp php-server --listen $HOST:$PORT -r public/` or `php -S $HOST:$PORT -t public` | tcp (unix with FrankenPHP) |

Try one:

1. *Runway > Toolchains* (administrator): install a version of the runtime.
2. Upload the example folder into the subscription, e.g. to `apps/example.com` (the default
   application directory of the domain `example.com`).
3. Open the domain's **Runway** page (*Websites & Domains > Dev Tools*), pick the runtime and
   toolchain, check the commands from the table, enable the application and save.

The domain page can also write these samples for you (**Create sample app**). Notes on every
runtime (version discovery, environment, detection, listen modes) are in
[docs/runtimes](../docs/runtimes).
