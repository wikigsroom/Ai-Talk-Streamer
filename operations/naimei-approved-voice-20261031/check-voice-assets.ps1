$ErrorActionPreference='Stop'
$root='C:\dev\虚拟数字人直播\naimei'
$state=Join-Path $root 'state\naimei'
$receipt=Join-Path $state 'approved-voice-pipeline.json'
if(Test-Path -LiteralPath $receipt){Get-Content -LiteralPath $receipt -Raw -Encoding UTF8}
else {
 $progress=Join-Path $root 'assets\naimei\live-v1\voice\preparation-status.json'
 $status=if(Test-Path -LiteralPath $progress){Get-Content -LiteralPath $progress -Raw -Encoding UTF8|ConvertFrom-Json}else{$null}
 @{complete=$false;progress=$status;stdout=((Get-Content -LiteralPath (Join-Path $state 'approved-voice-pipeline.stdout.log') -Encoding UTF8 -Tail 2|ForEach-Object {[string]$_}) -join "`n");stderr=((Get-Content -LiteralPath (Join-Path $state 'approved-voice-pipeline.stderr.log') -Encoding UTF8 -Tail 4|ForEach-Object {[string]$_}) -join "`n")}|ConvertTo-Json -Compress -Depth 4
}
