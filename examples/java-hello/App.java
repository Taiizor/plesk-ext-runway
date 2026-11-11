// Minimal Java web app for testing Runway (Plesk extension). JDK only, no Maven or Gradle.
// Needs Java 21+ (Thread.ofPlatform); for Java 17 use `new Thread(() -> handle(c)).start();`.
// Build: javac -d build App.java    Start: java -XX:MaxRAMPercentage=75 -cp build App
// (Runway detects this file and suggests exactly these commands.)
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import com.sun.net.httpserver.HttpServer;

public class App {
    static final byte[] BODY = ("Hello from Runway (Java " + System.getProperty("java.version") + ")\n")
        .getBytes(StandardCharsets.UTF_8);

    public static void main(String[] args) throws Exception {
        // Unix socket mode (recommended on shared servers): Runway sets RUNWAY_SOCKET.
        String sock = System.getenv("RUNWAY_SOCKET");
        if (sock != null && !sock.isEmpty()) { serveUnix(sock); return; }
        String host = System.getenv().getOrDefault("HOST", "127.0.0.1");
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress(host, port), 64);
        server.createContext("/", ex -> {
            ex.getResponseHeaders().add("Content-Type", "text/plain; charset=utf-8");
            ex.sendResponseHeaders(200, BODY.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(BODY); }
        });
        server.start();
        System.out.println("listening on http://" + host + ":" + port);
    }

    // Minimal HTTP/1.1 responder on a unix socket (HttpServer cannot bind to one).
    static void serveUnix(String path) throws Exception {
        Path p = Path.of(path);
        Files.deleteIfExists(p);                                   // stale socket from a crash
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try { Files.deleteIfExists(p); } catch (IOException e) { }
        }));
        try (ServerSocketChannel server = ServerSocketChannel.open(StandardProtocolFamily.UNIX)) {
            server.bind(UnixDomainSocketAddress.of(p));
            System.out.println("listening on unix:" + path);
            while (true) {
                SocketChannel c = server.accept();
                Thread.ofPlatform().daemon().start(() -> handle(c));
            }
        }
    }

    static void handle(SocketChannel c) {
        try (c) {
            ByteBuffer in = ByteBuffer.allocate(8192);
            StringBuilder req = new StringBuilder();
            while (c.read(in) > 0) {                               // read until end of headers
                in.flip(); req.append(StandardCharsets.ISO_8859_1.decode(in)); in.clear();
                if (req.indexOf("\r\n\r\n") >= 0) break;
            }
            String head = "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
                + BODY.length + "\r\nConnection: close\r\n\r\n";
            c.write(ByteBuffer.wrap(head.getBytes(StandardCharsets.ISO_8859_1)));
            c.write(ByteBuffer.wrap(BODY));
        } catch (IOException e) {
            // connection closed by peer
        }
    }
}
