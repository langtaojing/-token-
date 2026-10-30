$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $project

$pythonExe = Join-Path $project '.venv/Scripts/python.exe'
$requirements = Join-Path $project 'backend/requirements.txt'

if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv (Join-Path $project '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

if (-not (Test-Path -LiteralPath $requirements)) {
    throw 'Requirements file not found.'
}

& $pythonExe -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

$port = $null
$preferredPort = 8000
if ($env:AI_TEAM_HUB_PORT) { $preferredPort = [int]$env:AI_TEAM_HUB_PORT }
foreach ($candidate in $preferredPort..($preferredPort + 10)) {
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
        $listener.Start()
        $port = $candidate
        break
    } catch [System.Net.Sockets.SocketException] {
        continue
    } finally {
        if ($null -ne $listener) { $listener.Stop() }
    }
}
if ($null -eq $port) { throw 'No free local port found in the selected range.' }

Write-Host "AI Team Hub is starting at http://127.0.0.1:$port. Press Ctrl+C to stop."
& $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port $port
