# Copyright 2026 Taiizor. Licensed under the MIT License.

SAMPLE_GO = """// Runway sample app: listens on RUNWAY_SOCKET (unix mode) or LISTEN_ADDR (tcp mode).
package main

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"runtime"
)

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "Hello from Go %s on Runway\\n", runtime.Version())
	})
	if sock := os.Getenv("RUNWAY_SOCKET"); sock != "" {
		os.Remove(sock)
		ln, err := net.Listen("unix", sock)
		if err != nil {
			panic(err)
		}
		panic(http.Serve(ln, nil))
	}
	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8080"
	}
	panic(http.ListenAndServe(addr, nil))
}
"""

SAMPLE_CARGO = """[package]
name = "runway-sample"
version = "0.1.0"
edition = "2021"

[dependencies]
"""

SAMPLE_RUST = """// Runway sample app (std only): listens on RUNWAY_SOCKET (unix mode) or LISTEN_ADDR (tcp mode).
use std::io::{Read, Write};
use std::net::TcpListener;
use std::os::unix::net::UnixListener;
use std::thread;

fn respond<S: Read + Write>(mut stream: S) {
    let mut buf = [0u8; 8192];
    let _ = stream.read(&mut buf);
    let body = "Hello from Rust on Runway\\n";
    let _ = write!(stream, "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nContent-Length: {}\\r\\nConnection: close\\r\\n\\r\\n{}", body.len(), body);
}

fn main() {
    if let Ok(path) = std::env::var("RUNWAY_SOCKET") {
        let _ = std::fs::remove_file(&path);
        let listener = UnixListener::bind(&path).expect("bind unix socket");
        for stream in listener.incoming().flatten() {
            thread::spawn(move || respond(stream));
        }
    } else {
        let addr = std::env::var("LISTEN_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".to_string());
        let listener = TcpListener::bind(addr).expect("bind tcp port");
        for stream in listener.incoming().flatten() {
            thread::spawn(move || respond(stream));
        }
    }
}
"""

SAMPLE_BUN_PACKAGE = """{
  "name": "runway-sample",
  "private": true,
  "scripts": {
    "start": "bun run index.ts"
  }
}
"""

SAMPLE_BUN = """// Runway sample app: listens on RUNWAY_SOCKET (unix mode) or HOST:PORT (tcp mode).
const socket = process.env.RUNWAY_SOCKET;
const fetch = () => new Response(`Hello from Bun ${Bun.version} on Runway\\n`, { headers: { "content-type": "text/plain" } });
const server = socket
  ? Bun.serve({ unix: socket, fetch })
  : Bun.serve({ hostname: process.env.HOST || "127.0.0.1", port: Number(process.env.PORT || 3000), fetch });
console.log(`Listening on ${socket || server.url}`);
"""

SAMPLE_JAVA = """// Runway sample app (JDK only): listens on RUNWAY_SOCKET (unix mode) or HOST:PORT (tcp mode).
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class Main {
    static final byte[] BODY = ("Hello from Java " + System.getProperty("java.version") + " on Runway\\n")
            .getBytes(StandardCharsets.UTF_8);

    public static void main(String[] args) throws Exception {
        String socket = System.getenv("RUNWAY_SOCKET");
        if (socket != null && !socket.isEmpty()) {
            Path path = Path.of(socket);
            Files.deleteIfExists(path);
            ServerSocketChannel server = ServerSocketChannel.open(StandardProtocolFamily.UNIX);
            server.bind(UnixDomainSocketAddress.of(path));
            while (true) {
                SocketChannel client = server.accept();
                new Thread(() -> handle(client)).start();
            }
        }
        String host = System.getenv().getOrDefault("HOST", "127.0.0.1");
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress(host, port), 0);
        server.createContext("/", exchange -> {
            exchange.getResponseHeaders().set("Content-Type", "text/plain");
            exchange.sendResponseHeaders(200, BODY.length);
            exchange.getResponseBody().write(BODY);
            exchange.close();
        });
        server.start();
    }

    static void handle(SocketChannel client) {
        try (client) {
            client.read(ByteBuffer.allocate(8192));
            String head = "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nContent-Length: " + BODY.length
                    + "\\r\\nConnection: close\\r\\n\\r\\n";
            client.write(ByteBuffer.wrap(head.getBytes(StandardCharsets.US_ASCII)));
            client.write(ByteBuffer.wrap(BODY));
        } catch (Exception e) {
            System.err.println(e);
        }
    }
}
"""

SAMPLE_DOTNET_PROJECT = """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>%s</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <AssemblyName>app</AssemblyName>
    <InvariantGlobalization>true</InvariantGlobalization>
  </PropertyGroup>
</Project>
"""

SAMPLE_DOTNET = """// Runway sample app: Runway sets ASPNETCORE_URLS (http://127.0.0.1:PORT or http://unix:RUNWAY_SOCKET).
var app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/{**path}", () => $"Hello from .NET {Environment.Version} on Runway\\n");
app.Run();
"""

SAMPLE_PYTHON = """# Runway sample app (stdlib only): listens on RUNWAY_SOCKET (unix mode) or HOST:PORT (tcp mode).
import os
import socketserver
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("Hello from Python %s on Runway\\n" % sys.version.split()[0]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        request, _ = super().get_request()
        return request, ("unix", 0)


class TCPHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


sock = os.environ.get("RUNWAY_SOCKET")
if sock:
    if os.path.exists(sock):
        os.unlink(sock)
    server = UnixHTTPServer(sock, Handler)
else:
    server = TCPHTTPServer((os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))), Handler)
print("Listening on %s" % (sock or "%s:%s" % server.server_address[:2]), flush=True)
server.serve_forever()
"""

SAMPLE_RUBY = """# Runway sample app (stdlib only): listens on RUNWAY_SOCKET (unix mode) or HOST:PORT (tcp mode).
require "socket"

sock = ENV["RUNWAY_SOCKET"].to_s
server = if sock.empty?
  TCPServer.new(ENV.fetch("HOST", "127.0.0.1"), Integer(ENV.fetch("PORT", "3000")))
else
  File.unlink(sock) if File.exist?(sock)
  UNIXServer.new(sock)
end
$stdout.sync = true
puts "Listening on #{sock.empty? ? "#{ENV['HOST']}:#{ENV['PORT']}" : sock}"
body = "Hello from Ruby #{RUBY_VERSION} on Runway\\n"
loop do
  client = server.accept
  Thread.new(client) do |c|
    begin
      while (line = c.gets) && line != "\\r\\n"
      end
      c.write "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\nContent-Length: #{body.bytesize}\\r\\nConnection: close\\r\\n\\r\\n#{body}"
    rescue StandardError
      nil
    ensure
      c.close
    end
  end
end
"""

SAMPLE_PHP = """<?php
// Runway sample app: served by FrankenPHP (tcp or unix mode) or php -S (tcp mode).
header('Content-Type: text/plain');
echo 'Hello from PHP ' . PHP_VERSION . " on Runway\\n";
"""
