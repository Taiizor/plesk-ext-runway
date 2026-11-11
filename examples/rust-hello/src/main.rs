//! Minimal Rust web app (std only) for testing Runway (Plesk extension).
//! Build: cargo build --release    Start: ./target/release/rust-hello
use std::env;
use std::io::{BufRead, BufReader, Write};
use std::io::Read;
use std::net::TcpListener;
use std::os::unix::net::UnixListener;
use std::thread;

fn handle<S: Read + Write>(stream: S) {
    let mut reader = BufReader::new(stream);
    let mut request_line = String::new();
    if reader.read_line(&mut request_line).is_err() {
        return;
    }
    // Drain the request headers.
    let mut line = String::new();
    while reader.read_line(&mut line).map(|n| n > 2).unwrap_or(false) {
        line.clear();
    }
    let path = request_line.split_whitespace().nth(1).unwrap_or("/");
    let body = if path == "/healthz" {
        "ok\n".to_string()
    } else {
        format!("Hello from Rust ({} {})\n", env!("CARGO_PKG_NAME"), env!("CARGO_PKG_VERSION"))
    };
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    );
    let _ = reader.get_mut().write_all(response.as_bytes());
}

fn main() {
    // Unix socket mode (recommended on shared servers): Runway sets RUNWAY_SOCKET.
    if let Ok(path) = env::var("RUNWAY_SOCKET") {
        let listener = UnixListener::bind(&path).expect("bind unix socket");
        eprintln!("listening on unix:{}", path);
        for stream in listener.incoming().flatten() {
            thread::spawn(move || handle(stream));
        }
        return;
    }
    let host = env::var("HOST").unwrap_or_else(|_| "127.0.0.1".into());
    let port = env::var("PORT").unwrap_or_else(|_| "8080".into());
    let addr = format!("{}:{}", host, port);
    let listener = TcpListener::bind(&addr).expect("bind listener");
    eprintln!("listening on {}", addr);
    for stream in listener.incoming().flatten() {
        thread::spawn(move || handle(stream));
    }
}
