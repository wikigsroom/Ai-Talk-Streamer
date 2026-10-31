$ErrorActionPreference='Stop'
$root='C:\dev\虚拟数字人直播\naimei'
$origin=Get-Content -LiteralPath (Join-Path $root '.setup\deployment-origin.json') -Raw -Encoding UTF8|ConvertFrom-Json
$profile=Get-Content -LiteralPath (Join-Path $root 'assets\naimei\live-v1\voice\profile.json') -Raw -Encoding UTF8|ConvertFrom-Json
$studio=Invoke-RestMethod 'http://127.0.0.1:8052/api/studio/status' -TimeoutSec 5
$bridge=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/status' -TimeoutSec 5
$workers=@()
foreach($port in @(9891,9892)) {$health=Invoke-RestMethod ('http://127.0.0.1:'+ $port+'/health') -TimeoutSec 5;$workers+=@{port=$port;engine=$health.engine;voice_id=$health.voice_id;ready=$health.ready;busy=$health.busy}}
$queue=Invoke-RestMethod 'http://127.0.0.1:8188/queue' -TimeoutSec 5
@{branch=$origin.branch;source_commit=$origin.source_commit;selected_voice=$studio.voice_id;profile_default=$profile.default_voice_id;primary_engine=$profile.engine;fallback_engine=$profile.fallback_engine;voices=@($profile.voices|ForEach-Object {@{id=$_.id;reference_sha256=$_.sha256}});workers=$workers;active_speech=($null -ne $bridge.active_request);queued_speech=@($bridge.queued).Count;comfy_running=@($queue.queue_running).Count;comfy_pending=@($queue.queue_pending).Count;viewers=$studio.viewers}|ConvertTo-Json -Depth 6 -Compress
