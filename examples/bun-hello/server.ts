// Minimal Bun web app for testing Runway (Plesk extension). No dependencies.
// Build: bun install    Start: bun run start
import { existsSync, unlinkSync } from "node:fs";

const socket = process.env.RUNWAY_SOCKET;
// Stale socket from a crash: Bun does not unlink it itself (EADDRINUSE otherwise).
if (socket && existsSync(socket)) unlinkSync(socket);

const server = Bun.serve({
  // Unix socket mode (recommended on shared servers) when Runway sets RUNWAY_SOCKET, else HOST:PORT.
  ...(socket
    ? { unix: socket }
    : { hostname: process.env.HOST || "127.0.0.1", port: Number(process.env.PORT || 3000) }),
  fetch(req: Request) {
    const path = new URL(req.url).pathname;
    if (path === "/healthz") return new Response("ok\n");
    return new Response(`Hello from Runway (Bun ${Bun.version}) ${path}\n`, {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
});

const stop = () => {
  server.stop(true);
  if (socket) {
    try {
      unlinkSync(socket);
    } catch {}
  }
  process.exit(0);
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
console.log(socket ? `listening on unix:${socket}` : `listening on http://${server.hostname}:${server.port}`);
