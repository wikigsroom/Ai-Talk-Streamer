param(
    [ValidateSet('status','precheck','prepare-avatar','start-tts','start-avatar','start-obs','stop','send')]
    [string]$Action='status',
    [ValidateSet('v2','v2ProPlus')][string]$Profile='v2',
    [string]$Text='你好，这是本地数字人直播链路测试。',
    [switch]$Chat,
    [string]$Session=''
)
$ErrorActionPreference='Stop'
$AvatarRoot=$PSScriptRoot
$AvatarPython=Join-Path $AvatarRoot 'runtime\livetalking\Scripts\python.exe'
$AvatarArgs=@('-X','utf8','-B',(Join-Path $AvatarRoot 'scripts\launch.py'),$Action,'--profile',$Profile)
if($Action -eq 'send') {$AvatarArgs+=@('--text',$Text);if($Chat){$AvatarArgs+='--chat'};if($Session){$AvatarArgs+=@('--session',$Session)}}
Push-Location -LiteralPath $AvatarRoot
try { & $AvatarPython @AvatarArgs; if($LASTEXITCODE -ne 0){throw "Avatar command failed: $LASTEXITCODE"} }
finally { Pop-Location }
