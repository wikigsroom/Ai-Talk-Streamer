param([Parameter(Mandatory=$true)][string]$ModulePath)
$ErrorActionPreference='Stop'
Import-Module $ModulePath -Force
$buttons=@([Console]::In.ReadToEnd()|ConvertFrom-Json)
Get-IssacBroadcastUiState -Buttons $buttons|ConvertTo-Json -Compress
