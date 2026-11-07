param([ValidateSet('start','status','pause','arm','arm-local','stop','restart','restart-controller')][string]$Action='status')
$ErrorActionPreference='Stop'
$isaacPython=$env:ISAAC_PYTHON
if (-not $isaacPython) { $isaacPython=(Get-Command python.exe -ErrorAction Stop).Source }
if (-not (Test-Path -LiteralPath $isaacPython)) { throw '未找到原生 Python，请在配置的路径安装运行环境。' }
& $isaacPython -B -X utf8 (Join-Path $PSScriptRoot 'manage_stack.py') $Action
if ($LASTEXITCODE -ne 0) { throw '操作未完成，请查看上方说明；游戏不会因此自动恢复。' }
