// Minimal ASP.NET Core app (minimal API) for testing Runway (Plesk extension).
// Build: dotnet publish -c Release -o publish    Start: dotnet publish/app.dll
var builder = WebApplication.CreateBuilder(args);

var socket = Environment.GetEnvironmentVariable("RUNWAY_SOCKET");
var port = Environment.GetEnvironmentVariable("PORT");
if (!string.IsNullOrEmpty(socket))
{
    // Unix socket mode (recommended on shared servers). Kestrel does not unlink a stale socket itself.
    if (File.Exists(socket)) File.Delete(socket);
    builder.WebHost.ConfigureKestrel(o => o.ListenUnixSocket(socket));
}
else if (!string.IsNullOrEmpty(port))
{
    var host = Environment.GetEnvironmentVariable("HOST");
    builder.WebHost.UseUrls($"http://{(string.IsNullOrEmpty(host) ? "127.0.0.1" : host)}:{port}");
}
// Otherwise ASPNETCORE_URLS or Kestrel's default http://localhost:5000 applies.

var app = builder.Build();
app.MapGet("/healthz", () => "ok\n");
app.MapGet("/", () => $"Hello from Runway (.NET {Environment.Version})\n");
app.MapGet("/{*path}", (string path) => $"Hello from Runway (.NET {Environment.Version}) /{path}\n");
app.Run();
