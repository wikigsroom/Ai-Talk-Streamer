$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
$shared='C:\dev\虚拟数字人直播'
$destination=Join-Path $shared 'naimei'
$stage=Join-Path $shared 'operations\naimei-a01-a14-20261031\release'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri 'http://192.168.196.87:8951/naimei-source.zip' -OutFile (Join-Path $stage 'naimei-source.zip')
Invoke-WebRequest -UseBasicParsing -Uri 'http://192.168.196.87:8951/install_naimei.py' -OutFile (Join-Path $stage 'install_naimei.py')
$python=Join-Path $shared 'runtime\python\cpython-3.10.22-windows-x86_64-none\python.exe'
& $python -X utf8 -B (Join-Path $stage 'install_naimei.py') --archive (Join-Path $stage 'naimei-source.zip') --sha256 '46474861bb023b3346a6ca2472b311d34a3b2a7bd4e23c5af3cad9ee2dfafc7c' --destination $destination --shared-root $shared
if($LASTEXITCODE -ne 0){throw 'Naimei archive verification failed'}
& $python -X utf8 -B (Join-Path $destination 'scripts\deployment_target.py') --root $destination --expected-target naimei-rtx4090
if($LASTEXITCODE -ne 0){throw 'Naimei native target validation failed'}
$empty=Join-Path $stage 'empty.stdin'
[IO.File]::WriteAllText($empty,'')
$process=Start-Process -FilePath $python -ArgumentList @('-X','utf8','-B',(Join-Path $destination 'scripts\start_naimei.py'),'--root',$destination,'--voice-only') -WorkingDirectory $destination -WindowStyle Hidden -RedirectStandardInput $empty -RedirectStandardOutput (Join-Path $stage 'voice-start.stdout.log') -RedirectStandardError (Join-Path $stage 'voice-start.stderr.log') -PassThru
@{installed=$destination;voice_launcher_pid=$process.Id;public_broadcast_started=$false}|ConvertTo-Json -Compress
