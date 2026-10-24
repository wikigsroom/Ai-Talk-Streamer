param(
    [string]$Python='python',
    [switch]$PrepareAvatar,
    [ValidateSet('','rtx3080-original','rtx3080-batch4','rtx3080-batch2','rtx3080-batch1','rtx3080-cpu-tts')]
    [string]$HardwareProfile=''
)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if($env:OS -ne 'Windows_NT'){throw 'This distribution targets native Windows.'}
function Invoke-AvatarStep([string]$Interpreter,[string]$Script,[string[]]$Extra=@()) {
    & $Interpreter -X utf8 -B $Script @Extra
    if($LASTEXITCODE -ne 0){throw "Stage failed: $Script. See .setup and logs before retrying."}
}
# Native tools, dependencies and model weights; no virtual machine or container.
Invoke-AvatarStep $Python 'deployment/bootstrap.py'
Invoke-AvatarStep $Python 'deployment/download_models.py'
Invoke-AvatarStep $Python 'deployment/prepare_extras.py'
Invoke-AvatarStep $Python 'deployment/prepare_environments.py'
Invoke-AvatarStep $Python 'deployment/configure_stack.py'
Invoke-AvatarStep $Python 'deployment/prepare_runtime_assets.py'
Invoke-AvatarStep $Python 'deployment/prepare_ffmpeg7.py'
Invoke-AvatarStep $Python 'deployment/configure_obs_runtime.py'
Invoke-AvatarStep $Python 'deployment/activate_studio.py'
Invoke-AvatarStep $Python 'deployment/check_installation.py'
if($PrepareAvatar) {
    foreach($AvatarStage in @('compose_vertical_loop','prepare_vertical_avatar','prepare_motion_library','assemble_motion_bank','package_motion_materials','finalize_preparation')) {
        Invoke-AvatarStep $Python 'deployment/run_avatar_stage.py' @($AvatarStage)
    }
    Write-Output 'Preparation complete. Start with .\Start-Streamer.cmd'
} else {
    Write-Output 'Installation checks complete. Run the avatar preparation stages in docs/DEPLOYMENT.md before starting.'
}
if($HardwareProfile){Invoke-AvatarStep (Join-Path $PSScriptRoot 'runtime/livetalking/Scripts/python.exe') 'scripts/hardware_profile.py' @($HardwareProfile)}
