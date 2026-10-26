param([Parameter(Mandatory=$true)][string]$ProjectRoot, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
$DshProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
Set-Location -LiteralPath $DshProjectRoot
$DshVersion = '24.22.1'
$DshNodeName = "node-v$DshVersion-win-x64"
$DshDownload = Join-Path $DshProjectRoot 'downloads/dsh'
$DshNodeFolder = Join-Path $DshProjectRoot "tools/node/$DshNodeName"
$DshRuntime = Join-Path $DshProjectRoot 'tools/dsh'
New-Item -ItemType Directory -Path $DshDownload,$DshRuntime,(Join-Path $DshProjectRoot 'cache/npm-dsh'),(Join-Path $DshProjectRoot '.setup') -Force | Out-Null
$DshZip = Join-Path $DshDownload "$DshNodeName.zip"
$DshExpected = 'd2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5'
if (!(Test-Path -LiteralPath $DshZip)) { Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/v$DshVersion/$DshNodeName.zip" -OutFile $DshZip }
if ((Get-FileHash -LiteralPath $DshZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $DshExpected) { throw 'Node archive SHA256 mismatch' }
if (!(Test-Path -LiteralPath (Join-Path $DshNodeFolder 'node.exe'))) { Expand-Archive -LiteralPath $DshZip -DestinationPath (Join-Path $DshProjectRoot 'tools/node') }
Copy-Item -LiteralPath (Join-Path $DshProjectRoot 'backend/dsh-bridge/package.json') -Destination $DshRuntime
Copy-Item -LiteralPath (Join-Path $DshProjectRoot 'backend/dsh-bridge/package-lock.json') -Destination $DshRuntime
$env:Path = "$DshNodeFolder;" + $env:Path
$env:npm_config_cache = Join-Path $DshProjectRoot 'cache/npm-dsh'
& (Join-Path $DshNodeFolder 'node.exe') --version
# Windows PowerShell 5 wraps native stderr in error records. npm warnings
# must remain diagnostic output; the process exit code determines success.
$DshPreviousPreference = $ErrorActionPreference
try {
 $ErrorActionPreference = 'Continue'
 & (Join-Path $DshNodeFolder 'node.exe') (Join-Path $DshNodeFolder 'node_modules/npm/bin/npm-cli.js') ci --prefix $DshRuntime --ignore-scripts --omit=dev --no-audit --no-fund
} finally { $ErrorActionPreference = $DshPreviousPreference }
if ($LASTEXITCODE -ne 0) { throw 'Pinned npm ci failed' }
if (!$PythonExe) { $PythonExe = Join-Path $DshProjectRoot 'runtime/livetalking/Scripts/python.exe' }
if (!(Test-Path -LiteralPath $PythonExe)) { throw 'Pass -PythonExe with an existing native Python executable' }
& $PythonExe -X utf8 -B (Join-Path $DshProjectRoot 'deployment/patch_humanity.py') --project-root $DshProjectRoot --runtime $DshRuntime --source-root $DshProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Humanity connector patch failed' }
@{ installed_at = [DateTime]::UtcNow.ToString('o'); node = $DshVersion; node_sha256 = $DshExpected; dsh = '0.2.0-rc.2'; humanity = '0.1.17'; scripts_disabled = $true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $DshProjectRoot '.setup/dsh-runtime.json') -Encoding UTF8
