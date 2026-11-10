param([Parameter(Mandatory=$true)][string]$ModulePath)
$ErrorActionPreference='Stop'
Import-Module $ModulePath -Force
$buttons=ConvertFrom-Json -InputObject ([Console]::In.ReadToEnd())
Get-IssacBroadcastUiState -Buttons $buttons|ConvertTo-Json -Compress
