$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
& 'C:\Users\<user>\AppData\Local\Programs\Python\Python312\Scripts\pyinstaller.exe' --noconfirm --clean --onefile --name master desktop_app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
Copy-Item -LiteralPath (Join-Path $project 'dist/master.exe') -Destination 'C:\Users\<user>\Desktop\master.exe' -Force
