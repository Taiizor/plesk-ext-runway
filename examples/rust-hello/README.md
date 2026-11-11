# rust-hello

Minimal Rust web application (standard library only, no crates: it builds offline in seconds)
for Runway.

| Setting | Value |
|---|---|
| Runtime | Rust (`stable` or any installed toolchain) |
| Build command | `cargo build --release` |
| Start command | `./target/release/rust-hello` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

Builds need a C linker: install the build dependencies once on *Runway > Toolchains*.

Locally: `cargo run` then `curl http://127.0.0.1:8080/`.
