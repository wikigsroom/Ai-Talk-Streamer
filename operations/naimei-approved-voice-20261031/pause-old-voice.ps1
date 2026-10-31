$ErrorActionPreference='Stop'
$status=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/status' -TimeoutSec 5
if($status.health.character_id -ne 'naimei'){throw 'Naimei bridge required'}
$queued=@($status.queued).Count
Invoke-RestMethod 'http://127.0.0.1:8052/api/naimei/stop' -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 12|Out-Null
$status=Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/status' -TimeoutSec 5
if($status.broadcast.state -eq 'LIVE'){
 $body=@{broadcast_id=$status.broadcast.broadcast_id;expected_revision=$status.broadcast.revision}|ConvertTo-Json -Compress
 Invoke-RestMethod 'http://127.0.0.1:3094/api/dsh/broadcast/pause' -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 5|Out-Null
}
@{old_queued_requests_cancelled=$queued;paused_for_approved_voice=$true;models_stopped=$false;public_broadcast=$false}|ConvertTo-Json -Compress
