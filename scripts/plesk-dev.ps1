<#
.SYNOPSIS
    Local Plesk test server for Runway development (PowerShell 7 version of scripts/plesk-dev.sh).

.DESCRIPTION
    Runs the official plesk/plesk image with real systemd in Docker and installs the package built
    from this checkout. Commands:

      up        start the container, wait for the panel, print a login link
      install   build dist/runway-<version>-<release>.zip (python build.py --strict) and install or
                upgrade it; -NoFrontend packages the existing frontend build
      login     print a one-time administrator login link
      prepare   subscription gotest.local, customer cust1, Go toolchain and sample app
                (runs .github/scripts/plesk-e2e.sh: needs bash, on Windows from Git for Windows)
      test      helper-smoke, api-smoke, customer-smoke and the Go part of runtime-e2e (needs bash)
      status    container, extension and Runway units
      shell     root shell inside the container
      logs      panel log and the journal of the Runway units; -Follow keeps reading the journal
      down      remove the container (toolchains and test data are lost)

    The first "up" downloads the image (about 2 GB); Plesk then needs a few minutes to initialise.
    The hosted sites answer on http://localhost:<HttpPort>: add "127.0.0.1 gotest.local" to
    C:\Windows\System32\drivers\etc\hosts and open http://gotest.local:18080.

.PARAMETER Command
    One of up, install, login, prepare, test, status, shell, logs, down, help.
.PARAMETER NoFrontend
    install: package the existing frontend build instead of rebuilding it.
.PARAMETER Follow
    logs: follow the journal of the Runway units.
.PARAMETER Container
    Container name (environment CONTAINER, default runway-plesk).
.PARAMETER Image
    Docker image (environment PLESK_IMAGE, default plesk/plesk:latest).
.PARAMETER PanelPort
    Host port of the panel over HTTP (environment PANEL_PORT, default 18880).
.PARAMETER PanelSslPort
    Host port of the panel over HTTPS (environment PANEL_SSL_PORT, default 18443).
.PARAMETER HttpPort
    Host port of the hosted sites (environment HTTP_PORT, default 18080).
.PARAMETER Runtimes
    test: runtimes of tests/runtime-e2e.sh (environment E2E_RUNTIMES, default go; "" skips it).
.PARAMETER WaitMinutes
    up: how long to wait for the panel (environment WAIT_MINUTES, default 25).

.EXAMPLE
    ./scripts/plesk-dev.ps1 up
    ./scripts/plesk-dev.ps1 install -NoFrontend
    ./scripts/plesk-dev.ps1 logs -Follow
#>
#Requires -Version 7.3
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('up', 'install', 'login', 'prepare', 'test', 'status', 'shell', 'logs', 'down', 'help')]
    [string]$Command = 'help',
    [switch]$NoFrontend,
    [switch]$Follow,
    [string]$Container = $(if ($env:CONTAINER) { $env:CONTAINER } else { 'runway-plesk' }),
    [string]$Image = $(if ($env:PLESK_IMAGE) { $env:PLESK_IMAGE } else { 'plesk/plesk:latest' }),
    [int]$PanelPort = $(if ($env:PANEL_PORT) { [int]$env:PANEL_PORT } else { 18880 }),
    [int]$PanelSslPort = $(if ($env:PANEL_SSL_PORT) { [int]$env:PANEL_SSL_PORT } else { 18443 }),
    [int]$HttpPort = $(if ($env:HTTP_PORT) { [int]$env:HTTP_PORT } else { 18080 }),
    [string]$Runtimes = $(if ($null -ne $env:E2E_RUNTIMES) { $env:E2E_RUNTIMES } else { 'go' }),
    [int]$WaitMinutes = $(if ($env:WAIT_MINUTES) { [int]$env:WAIT_MINUTES } else { 25 })
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Exit codes of docker, python and bash are checked explicitly below.
$PSNativeCommandUseErrorActionPreference = $false

$Root = Split-Path -Parent $PSScriptRoot
$E2E = Join-Path $Root '.github' 'scripts' 'plesk-e2e.sh'

function Write-Step([string]$Message) { Write-Host "== $Message" }

function Assert-Exit([string]$What) {
    # After a native command (docker, python, bash): throw when it failed.
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Get-ContainerState {
    # "$(...)" instead of [string](...): a native command without output yields $null, not "".
    $state = "$(& docker inspect -f '{{.State.Status}}' $Container 2>$null)".Trim()
    if ($LASTEXITCODE -ne 0 -or -not $state) { return 'absent' }
    return $state
}

function Assert-Running {
    if ((Get-ContainerState) -ne 'running') {
        throw "the container $Container is not running: ./scripts/plesk-dev.ps1 up"
    }
}

function Get-LoginLink {
    $relative = "$(& docker exec $Container plesk bin admin --get-login-link -relative-url)".Trim()
    if ($LASTEXITCODE -ne 0) { throw 'plesk bin admin --get-login-link failed' }
    return "http://localhost:$PanelPort$relative"
}

function Get-Python {
    # "python3" may be a non-working Microsoft Store alias on Windows: probe the candidates.
    foreach ($candidate in @('python', 'python3', 'py')) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        $arguments = if ($candidate -eq 'py') { @('-3', '-c', 'import json') } else { @('-c', 'import json') }
        & $candidate @arguments *> $null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    throw 'python3 (3.8+) is needed for build.py'
}

function Get-Bash {
    # Git for Windows' bash, not the WSL launcher in System32.
    $candidates = @()
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) { $candidates += Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) 'bin' 'bash.exe' }
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles 'Git' 'bin' 'bash.exe' }
    foreach ($candidate in $candidates) { if (Test-Path -LiteralPath $candidate) { return $candidate } }
    $bash = Get-Command bash -ErrorAction SilentlyContinue
    if ($bash -and $bash.Source -notlike '*\System32\*') { return $bash.Source }
    throw 'bash is needed for this command (on Windows: Git for Windows, https://gitforwindows.org)'
}

function Invoke-E2E([string]$Subcommand) {
    # Runs .github/scripts/plesk-e2e.sh with the settings of this script. The variables are
    # restored afterwards: a script run from an interactive shell shares its environment.
    $settings = @{
        CONTAINER = $Container; PLESK_IMAGE = $Image; PANEL_PORT = "$PanelPort"
        E2E_RUNTIMES = $Runtimes; WAIT_MINUTES = "$WaitMinutes"
    }
    $saved = @{}
    foreach ($name in $settings.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
    try {
        foreach ($name in $settings.Keys) { [Environment]::SetEnvironmentVariable($name, $settings[$name]) }
        & (Get-Bash) $E2E $Subcommand
        Assert-Exit "plesk-e2e.sh $Subcommand"
    } finally {
        foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    }
}

function Wait-Panel {
    Write-Step "waiting for Plesk ($Image, at most $WaitMinutes minutes)"
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    while ($true) {
        $state = "$(& docker exec $Container systemctl is-system-running 2>$null)".Trim()
        $code = 0
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$PanelPort/login_up.php" -UseBasicParsing `
                -TimeoutSec 5 -SkipHttpErrorCheck
            $code = [int]$response.StatusCode
        } catch { $code = 0 }
        if (($state -eq 'running' -or $state -eq 'degraded') -and $code -eq 200) {
            & docker exec $Container plesk bin admin --get-login-link -relative-url *> $null
            if ($LASTEXITCODE -eq 0) { break }
        }
        if ((Get-Date) -gt $deadline) { throw "Plesk did not become ready (systemd: $state, panel: HTTP $code)" }
        Start-Sleep -Seconds 10
    }
    if ($state -eq 'degraded') { & docker exec $Container systemctl --failed --no-pager }
    & docker exec $Container plesk version | Select-Object -First 2
}

function Invoke-Up {
    switch (Get-ContainerState) {
        'running' {
            Write-Host "$Container is already running"
            Wait-Panel
        }
        'absent' {
            & docker rm -f $Container *> $null
            # The same flags as the documented local test environment (README.md, "Development").
            & docker run -d --name $Container --hostname plesk.runway.test `
                --tmpfs /tmp --tmpfs /run --tmpfs /run/lock `
                -v /sys/fs/cgroup:/sys/fs/cgroup --cgroupns=host `
                --cap-add SYS_ADMIN --security-opt apparmor=unconfined `
                -p "${PanelPort}:8880" -p "${PanelSslPort}:8443" -p "${HttpPort}:80" $Image | Out-Null
            Assert-Exit 'docker run'
            Wait-Panel
        }
        default {
            Write-Step "starting the existing container $Container"
            & docker start $Container | Out-Null
            Assert-Exit 'docker start'
            Wait-Panel
        }
    }
    Write-Host "panel: http://localhost:$PanelPort (https://localhost:$PanelSslPort), sites: http://localhost:$HttpPort"
    Write-Host "login: $(Get-LoginLink)"
}

function Invoke-Install {
    Assert-Running
    $python = Get-Python
    Push-Location $Root
    try {
        $arguments = @('build.py', '--strict')
        if ($NoFrontend) { $arguments += '--no-frontend' }
        & $python @arguments
        Assert-Exit 'build.py'
        $meta = Get-Content -LiteralPath (Join-Path 'src' 'meta.xml') -Raw
        $version = [regex]::Match($meta, '<version>(.*?)</version>').Groups[1].Value
        $release = [regex]::Match($meta, '<release>(.*?)</release>').Groups[1].Value
        $package = Join-Path 'dist' "runway-$version-$release.zip"
        Write-Step "installing $(Split-Path -Leaf $package)"
        & docker cp $package "${Container}:/root/runway.zip"
        Assert-Exit 'docker cp'
        & docker exec $Container plesk bin extension --upgrade /root/runway.zip
        Assert-Exit 'plesk bin extension --upgrade'
        & docker exec $Container plesk bin extension --list | Select-String -Pattern '^runway\b' | ForEach-Object { $_.Line }
    } finally { Pop-Location }
    Write-Host "login: $(Get-LoginLink)"
}

function Invoke-Status {
    & docker ps -a --filter "name=^/$Container$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    if ((Get-ContainerState) -ne 'running') { return }
    Write-Host ''
    $extension = & docker exec $Container plesk bin extension --list | Select-String -Pattern '^runway\b'
    if ($extension) { Write-Host $extension.Line } else { Write-Host 'runway: not installed' }
    Write-Host ''
    # The unit table ends at the first empty line (the legend follows).
    $units = @(& docker exec $Container systemctl list-units --all --no-pager --plain 'runway-*')
    foreach ($line in $units) {
        if ($line -eq '') { break }
        Write-Host $line
    }
}

function Invoke-Logs {
    Assert-Running
    if ($Follow) {
        # A pty, so that Ctrl+C reaches journalctl instead of leaving it running in the container.
        & docker exec -it $Container journalctl -f -n 50 -u 'runway-*'
        return
    }
    & docker exec $Container bash -c 'echo "== /var/log/plesk/panel.log"; tail -n 50 /var/log/plesk/panel.log 2>/dev/null; echo; echo "== journalctl -u runway-*"; journalctl --no-pager -n 100 -u "runway-*" 2>&1'
}

switch ($Command) {
    'up' { Invoke-Up }
    'install' { Invoke-Install }
    'login' { Assert-Running; Write-Host (Get-LoginLink) }
    'prepare' { Assert-Running; Invoke-E2E prepare }
    'test' { Assert-Running; Invoke-E2E smoke }
    'status' { Invoke-Status }
    'shell' { Assert-Running; & docker exec -it $Container bash; exit $LASTEXITCODE }
    'logs' { Invoke-Logs }
    'down' { & docker rm -f $Container *> $null; Write-Host "$Container removed" }
    default { Get-Help $PSCommandPath -Detailed | Out-Host }
}
# Native commands that may fail harmlessly (docker inspect of a missing container, journalctl
# without units) leave their exit code in $LASTEXITCODE; the script itself succeeded.
exit 0
