param([string]$Root='C:\dev\虚拟数字人直播\naimei',[string]$SharedRoot='C:\dev\虚拟数字人直播')
$ErrorActionPreference='Stop'
$rootPath=[IO.Path]::GetFullPath($Root)
$sharedPath=[IO.Path]::GetFullPath($SharedRoot)
if($rootPath -ne (Join-Path $sharedPath 'naimei')){throw 'Separate Naimei installation required'}
$existing=Join-Path $sharedPath 'outputs\platforms\setup\bilibili-livehime.json'
if(-not (Test-Path -LiteralPath $existing)){throw 'An existing official native Livehime installation was not found'}
$inventory=Get-Content -Raw -Encoding UTF8 -LiteralPath $existing|ConvertFrom-Json
$application=[IO.Path]::GetFullPath((Join-Path $sharedPath $inventory.application))
if(-not $application.StartsWith($sharedPath+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $application)){throw 'Official client path is outside the shared native installation'}
$signature=Get-AuthenticodeSignature -LiteralPath $application
if($signature.Status -ne 'Valid'){throw 'Official native client signature did not verify'}
$parent=Split-Path -Parent $application
$link=Join-Path $rootPath 'tools\bilibili-livehime-native'
if(Test-Path -LiteralPath $link){
  $item=Get-Item -LiteralPath $link -Force
  if(-not $item.Target -or [IO.Path]::GetFullPath($item.Target[0]) -ne $parent){throw 'Existing Naimei client link points elsewhere'}
}else{New-Item -ItemType Junction -Path $link -Target $parent|Out-Null}
$setup=Join-Path $rootPath 'outputs\platforms\setup'
New-Item -ItemType Directory -Path $setup -Force|Out-Null
$receipt=@{prepared=$true;version=[Diagnostics.FileVersionInfo]::GetVersionInfo($application).FileVersion;
  application='tools/bilibili-livehime-native/'+[IO.Path]::GetFileName($application);
  application_signature=@{status='Valid';subject=$signature.SignerCertificate.Subject};
  application_sha256=(Get-FileHash -LiteralPath $application -Algorithm SHA256).Hash.ToLower();
  verified_at=[DateTime]::UtcNow.ToString('o');origin='existing local signed official application; independently verified for naimei';
  account_login_verified=$false;public_broadcast_started=$false;obs_required=$false;imported_state=$false}
[IO.File]::WriteAllText((Join-Path $setup 'bilibili-livehime.json'),($receipt|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false))
@{prepared=$true;character='naimei';public_broadcast_started=$false;account_login_verified=$false;source_url='http://127.0.0.1:8052/output.html?renderer=livehime&codec=jpeg&buffer_ms=800&layout=portrait'}|ConvertTo-Json -Compress
