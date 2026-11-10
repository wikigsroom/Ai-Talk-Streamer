function Get-IssacBroadcastUiState {
    param([object[]]$Buttons)
    $visible=@($Buttons|Where-Object {$_.is_button -eq $true -and $_.enabled -eq $true -and $_.offscreen -ne $true})
    $start=@($visible|Where-Object {$_.name -in @('开始直播','立即开播','确认开播')})
    $stop=@($visible|Where-Object {$_.name -eq '关播'})
    $elapsed=@($visible|Where-Object {$_.name -match '^\d{2,}:[0-5]\d:[0-5]\d$'})
    $quality=@($visible|Where-Object {$_.name -like '直播质量*'})
    # The actual client replaces its start button with an elapsed-time button.
    # A local recording clock cannot qualify while a start button still exists.
    $active=($start.Count -eq 0 -and ($stop.Count -eq 1 -or ($elapsed.Count -eq 1 -and $quality.Count -ge 1)))
    return @{
        already_running=$active;start_buttons=$start.Count;running_buttons=$stop.Count
        live_elapsed_controls=$elapsed.Count;live_quality_controls=$quality.Count
        running_evidence=$(if($active -and $stop.Count -eq 1){'named_live_control'}elseif($active){'owned_live_elapsed_and_quality_controls'}else{$null})
    }
}
Export-ModuleMember -Function Get-IssacBroadcastUiState
