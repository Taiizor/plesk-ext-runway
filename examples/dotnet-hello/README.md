# dotnet-hello

Minimal ASP.NET Core application (minimal API) for Runway.

| Setting | Value |
|---|---|
| Runtime | .NET SDK 10 (set `TargetFramework` in `app.csproj` to the installed channel, e.g. `net11.0`) |
| Build command | `dotnet publish -c Release -o publish` |
| Start command | `dotnet publish/app.dll` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

`Program.cs` binds Kestrel to the Unix socket in `RUNWAY_SOCKET` (removing a stale socket file
first) or to `http://$HOST:$PORT`. Without either variable `ASPNETCORE_URLS` or Kestrel's
default `http://localhost:5000` applies.

Locally: `dotnet run` with `PORT=8080`, then `curl http://127.0.0.1:8080/`.
