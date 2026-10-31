$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Virtual environment not found. Run run-local.ps1 once first.' }
& $python -m pip install pyinstaller --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
& $python -m PyInstaller --noconfirm --clean --onefile --name AI-Team-Hub desktop_app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Write-Host ("Built: " + (Join-Path $project 'dist/AI-Team-Hub.exe'))
