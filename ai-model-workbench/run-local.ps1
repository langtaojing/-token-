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

Write-Host 'AI Team Hub is starting at http://127.0.0.1:8000. Press Ctrl+C to stop.'
& $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
