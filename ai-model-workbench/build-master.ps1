$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\Scripts\pyinstaller.exe') --noconfirm --clean --onefile --name master desktop_app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath (Join-Path $project 'dist/master.exe') -Destination (Join-Path $env:USERPROFILE 'Desktop\master.exe') -Force
