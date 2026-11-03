[CmdletBinding()]
param(
    [string]$JavaHome,
    [string]$NodePath,
    [string]$GradlePath,
    [string]$PythonPath = 'python',
    [switch]$OfflineInputs,
    [switch]$RefreshDependencyLocks
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mcSurvivalRoot = Split-Path -Parent $PSScriptRoot
if (-not $GradlePath) { $GradlePath = Join-Path $mcSurvivalRoot 'game-adapters\minecraft\fabric\gradlew.bat' }
if (-not $JavaHome) { $JavaHome = $env:JAVA_HOME }
if (-not $JavaHome) { throw 'Provide -JavaHome pointing to JDK21.' }
$mcNativeArguments = @{JavaHome=$JavaHome; NodePath=$NodePath; GradlePath=$GradlePath}
if ($RefreshDependencyLocks) { $mcNativeArguments.RefreshDependencyLocks = $true }
& (Join-Path $PSScriptRoot 'mc_build_fabric.ps1') @mcNativeArguments
$mcPrepareArguments = @('-X', 'utf8', '-B', (Join-Path $PSScriptRoot 'mc_prepare_survival.py'))
if ($OfflineInputs) { $mcPrepareArguments += '--offline' }
& $PythonPath @mcPrepareArguments
if ($LASTEXITCODE -ne 0) { throw 'Pinned survival input preparation failed.' }
$mcSurvivalEnv = @{}
foreach ($mcKey in @('JAVA_HOME', 'GRADLE_USER_HOME', 'TEMP', 'TMP', 'MC_BUILD_PYTHON')) {
    $mcSurvivalEnv[$mcKey] = [Environment]::GetEnvironmentVariable($mcKey, 'Process')
}
$mcSurvivalOutput = Join-Path $mcSurvivalRoot 'outputs\mc-validation'
New-Item -ItemType Directory -Path $mcSurvivalOutput -Force | Out-Null
$mcSurvivalExit = 1
try {
    $env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
    $env:GRADLE_USER_HOME = Join-Path $mcSurvivalRoot '.setup\mc-gradle'
    $env:TEMP = Join-Path $mcSurvivalRoot '.setup\mc-gradle-temp'
    $env:TMP = $env:TEMP
    $env:MC_BUILD_PYTHON = (Get-Command $PythonPath -ErrorAction Stop).Source
    New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
    # Materialize the controlled nested module before Loom resolves include metadata.
    $mcGateArguments = @('--no-daemon', '-p', (Join-Path $mcSurvivalRoot 'game-adapters\minecraft\survival'), 'compileControlledBaritone')
    if ($RefreshDependencyLocks) { $mcGateArguments += '--write-locks' }
    $mcGateArguments += @('--console', 'plain')
    & $GradlePath @mcGateArguments 2>&1 | Tee-Object -FilePath (Join-Path $mcSurvivalOutput 'survival-gates.log')
    if ($LASTEXITCODE -ne 0) { throw 'Controlled nested pathfinding compilation failed.' }
    $mcBuildArguments = @('--no-daemon', '-p', (Join-Path $mcSurvivalRoot 'game-adapters\minecraft\survival'), 'test', 'build')
    if ($RefreshDependencyLocks) { $mcBuildArguments += '--write-locks' }
    $mcBuildArguments += @('--console', 'plain')
    & $GradlePath @mcBuildArguments 2>&1 | Tee-Object -FilePath (Join-Path $mcSurvivalOutput 'survival-build.log')
    $mcSurvivalExit = $LASTEXITCODE
} finally {
    foreach ($mcKey in $mcSurvivalEnv.Keys) { [Environment]::SetEnvironmentVariable($mcKey, $mcSurvivalEnv[$mcKey], 'Process') }
}
if ($mcSurvivalExit -ne 0) { throw 'Controlled survival build/checks failed.' }
& $PythonPath -X utf8 -B (Join-Path $PSScriptRoot 'mc_check_survival_build.py')
if ($LASTEXITCODE -ne 0) { throw 'Controlled survival artifact verification failed.' }
Write-Output 'Engineering artifact verified; unconditional prelaunch rejection remains. No game or model was started.'
