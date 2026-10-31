$ErrorActionPreference='Stop'
[Net.WebRequest]::DefaultWebProxy=$null
$root='C:\dev\虚拟数字人直播\naimei'
$rows=@()
foreach($port in @(9891,9892,8030,8052)){
 try {
  $h=Invoke-RestMethod ('http://127.0.0.1:'+$port+'/health') -TimeoutSec 4
  $rows+=@{port=$port;ready=$h.ready;voice_id=$h.voice_id;engine=$h.engine;reference_sha256=$h.reference_sha256;precision=$h.precision;steps=$h.steps;seed=$h.seed;error=$h.error;busy=$h.busy;size=$h.size}
 }catch{$rows+=@{port=$port;unavailable=$true}}
}
$errors=@()
foreach($name in @('approved-voice-start','processes\voice-primary','processes\voice-fallback')){
 $file=Join-Path $root ('state\naimei\'+$name+'.stderr.log')
 if(Test-Path -LiteralPath $file){$errors+=@{service=$name;tail=@(Get-Content -LiteralPath $file -Tail 5 -Encoding UTF8|ForEach-Object {[string]$_})}}
}
@{health=$rows;errors=$errors}|ConvertTo-Json -Depth 6 -Compress
