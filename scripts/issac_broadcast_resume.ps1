param([Parameter(Mandatory=$true)][int]$ProcessId,[Parameter(Mandatory=$true)][long]$WindowHandle,[switch]$InspectOnly)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'issac_broadcast_state.psm1') -Force
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class LiveResumeInput {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(Point p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
 public struct Point { public int X; public int Y; }
}
'@
$window=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]::new($WindowHandle))
if(-not $window -or $window.Current.ProcessId -ne $ProcessId){throw 'EXACT_OFFICIAL_WINDOW_REQUIRED'}
# Only resume/start controls; this helper cannot end a broadcast.
$labels=@('开始直播','立即开播','确认开播')
$nodes=$window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
if($nodes.Count -gt 6000){throw 'BOUNDED_OFFICIAL_UI_REQUIRED'}
$targets=@()
$uiButtons=@()
foreach($node in $nodes){
    $info=$node.Current
    # Qt exports both the button and its child text with the same name.
    # Only actionable buttons can authorize a click; text is never a target.
    if($info.ControlType -ne [Windows.Automation.ControlType]::Button){continue}
    $uiButtons+=@{name=$info.Name.Trim();is_button=$true;enabled=$info.IsEnabled;offscreen=$info.IsOffscreen}
    if($labels -contains $info.Name.Trim() -and $info.IsEnabled -and -not $info.IsOffscreen){$targets+=,$node}
}
$state=Get-IssacBroadcastUiState -Buttons $uiButtons
if($InspectOnly){$state.can_stop_broadcast=$false;$state.invoked=$false;$state|ConvertTo-Json -Compress;exit 0}
if($state.already_running){$state.can_stop_broadcast=$false;$state|ConvertTo-Json -Compress;exit 0}
if($targets.Count -ne 1){throw 'ONE_EXPLICIT_START_BROADCAST_CONTROL_REQUIRED'}
$pattern=$null
if($targets[0].TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
    ([Windows.Automation.InvokePattern]$pattern).Invoke()
}else{
    $box=$targets[0].Current.BoundingRectangle
    $frame=$window.Current.BoundingRectangle
    if($box.Width -lt 20 -or $box.Height -lt 15 -or -not $frame.Contains($box)){throw 'VISIBLE_START_CONTROL_REQUIRED'}
    $handle=[IntPtr]::new($WindowHandle)
    [void][LiveResumeInput]::SetForegroundWindow($handle)
    Start-Sleep -Milliseconds 150
    if([LiveResumeInput]::GetForegroundWindow() -ne $handle){throw 'EXACT_OFFICIAL_FOREGROUND_REQUIRED'}
    $point=[LiveResumeInput+Point]::new();$point.X=[int]($box.X+$box.Width/2);$point.Y=[int]($box.Y+$box.Height/2)
    $hit=[LiveResumeInput]::WindowFromPoint($point);[uint32]$owner=0
    [void][LiveResumeInput]::GetWindowThreadProcessId($hit,[ref]$owner)
    if($owner -ne $ProcessId){throw 'START_CONTROL_OCCLUDED'}
    [void][LiveResumeInput]::SetCursorPos($point.X,$point.Y)
    [LiveResumeInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    [LiveResumeInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
@{action='resume-requested-live';invoked=$true;can_stop_broadcast=$false}|ConvertTo-Json -Compress
