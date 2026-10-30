$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $project

if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
}

& '.venv/Scripts/python.exe' -m pip install -r 'backendequirements.txt'
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }

Write-Host '打开 http://127.0.0.1:8000 ；按 Ctrl+C 停止。'
& '.venv/Scripts/python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
