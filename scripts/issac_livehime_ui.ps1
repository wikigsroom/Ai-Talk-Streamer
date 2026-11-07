param([Parameter(Mandatory=$true)][int]$ProcessId,[Parameter(Mandatory=$true)][long]$WindowHandle,[ValidateSet('inspect','record-start','record-stop')][string]$Action='inspect')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$window=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]::new($WindowHandle))
if(-not $window -or $window.Current.ProcessId -ne $ProcessId){throw 'EXACT_OWNED_OFFICIAL_WINDOW_REQUIRED'}
$nodes=$window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
if($nodes.Count -gt 6000){throw 'BOUNDED_OFFICIAL_UI_TREE_REQUIRED'}
$startNames=@('开始录制','开始录像','录制')
$stopNames=@('停止录制','结束录制','停止录像','结束录像')
$starts=@();$stops=@();$items=@()
for($index=0;$index -lt $nodes.Count;$index++){
  $node=$nodes.Item($index);$info=$node.Current
  if(-not $info.Name -or $info.Name.Length -gt 100){continue}
  $items+=@{name=$info.Name;automation_id=$info.AutomationId;type=$info.ControlType.ProgrammaticName;enabled=$info.IsEnabled;offscreen=$info.IsOffscreen}
  if($info.IsEnabled -and -not $info.IsOffscreen){
    if($startNames -contains $info.Name){$starts+=,$node}
    if($stopNames -contains $info.Name){$stops+=,$node}
  }
}
if($Action -eq 'inspect'){
  @{process_id=$ProcessId;window_name=$window.Current.Name;controls=$items;start_controls=$starts.Count;stop_controls=$stops.Count;recording_indicator=($stops.Count -gt 0)}|ConvertTo-Json -Depth 5 -Compress
  exit 0
}
$targets=if($Action -eq 'record-start'){$starts}else{$stops}
if($Action -eq 'record-start' -and $stops.Count -gt 0){throw 'EXISTING_OFFICIAL_RECORDING_LEFT_UNCHANGED'}
if($targets.Count -ne 1){throw 'UNIQUE_OFFICIAL_RECORD_BUTTON_REQUIRED'}
$pattern=$null
if(-not $targets[0].TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){throw 'RECORD_BUTTON_INVOKE_UNAVAILABLE'}
# The allowlist contains only recording labels. Never invoke 开始直播/推流.
([Windows.Automation.InvokePattern]$pattern).Invoke()
@{action=$Action;process_id=$ProcessId;invoked=$true;public_broadcast_started=$false}|ConvertTo-Json -Compress
