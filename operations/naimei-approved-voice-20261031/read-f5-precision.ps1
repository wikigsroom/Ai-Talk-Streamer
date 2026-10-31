$ErrorActionPreference='Stop'
$base='C:\dev\虚拟数字人直播\src\tts-benchmark\f5\src\f5_tts'
$api=Get-Content -LiteralPath (Join-Path $base 'api.py') -Encoding UTF8 -TotalCount 105
$utils=Get-Content -LiteralPath (Join-Path $base 'infer\utils_infer.py') -Encoding UTF8
$start=0
for($index=0;$index -lt $utils.Count;$index++){if($utils[$index] -match '^def load_model\('){$start=$index;break}}
@{api=($api -join "`n");loader=($utils[$start..([Math]::Min($start+45,$utils.Count-1))] -join "`n")}|ConvertTo-Json -Compress
