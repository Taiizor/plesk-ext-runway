# java-hello

Minimal Java web application using only the JDK (`com.sun.net.httpserver.HttpServer` for TCP,
a small HTTP/1.1 responder on a `UnixDomainSocketAddress` channel for Unix socket mode). No
Maven or Gradle.

| Setting | Value |
|---|---|
| Runtime | Java 21 or newer (Temurin) |
| Build command | `javac -d build App.java` |
| Start command | `java -XX:MaxRAMPercentage=75 -cp build App` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |

Runway detects a top-level `.java` file with a `static void main` method and suggests these
commands on the domain page. Alternative without a build step: start command `java App.java` (the source launcher compiles
the file at every start, about 1-2 s). For Java 17, replace
`Thread.ofPlatform().daemon().start(() -> handle(c));` with `new Thread(() -> handle(c)).start();`.

Real projects: Maven/Gradle wrappers (`sh ./mvnw -q -B -DskipTests package`,
`sh ./gradlew --no-daemon -q build -x test`) and `java -XX:MaxRAMPercentage=75 -jar target/app.jar`.
Spring Boot needs at least 384-512 MB of memory and a task limit of 512 or more.
