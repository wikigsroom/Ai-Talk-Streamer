[CmdletBinding()]
param(
    [string]$JavaHome,
    [string]$NodePath,
    [string]$GradlePath,
    [switch]$SkipInterop,
    [switch]$RefreshDependencyLocks
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mcRepoRoot = Split-Path -Parent $PSScriptRoot
$mcProject = Join-Path $mcRepoRoot 'game-adapters\minecraft\fabric'
$mcEvidence = Join-Path $mcRepoRoot 'outputs\mc-validation'
$mcWrapperHash = '7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172'

$mcBranch = & git -C $mcRepoRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $mcBranch.Trim() -ne 'mc') { throw 'MC builds must run on the mc branch.' }
$mcWrapper = Join-Path $mcProject 'gradle\wrapper\gradle-wrapper.jar'
if ((Get-FileHash -LiteralPath $mcWrapper -Algorithm SHA256).Hash.ToLowerInvariant() -ne $mcWrapperHash) {
    throw 'The Gradle wrapper JAR does not match the pinned upstream checksum.'
}
if (-not $JavaHome) { $JavaHome = $env:JAVA_HOME }
if (-not $JavaHome) {
    $mcJavaCommand = Get-Command java.exe -ErrorAction SilentlyContinue
    if ($mcJavaCommand) { $JavaHome = Split-Path -Parent (Split-Path -Parent $mcJavaCommand.Source) }
}
if (-not $JavaHome) { throw 'Provide -JavaHome pointing to an installed JDK 21.' }
$mcJava = Join-Path $JavaHome 'bin\java.exe'
if (-not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\javac.exe'))) { throw 'JavaHome must contain a full JDK 21.' }
$mcJavaVersion = (& $mcJava --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $mcJavaVersion -notmatch '(?m)^(openjdk|java) 21[. ]') { throw 'This project requires JDK 21.' }
$mcNodeVersion = $null
if (-not $SkipInterop) {
    if (-not $NodePath) {
        $mcNodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
        if ($mcNodeCommand) { $NodePath = $mcNodeCommand.Source }
    }
    if (-not $NodePath) { throw 'Provide -NodePath pointing to Node 24 for the protocol interoperability checks.' }
    $mcNodeVersion = (& $NodePath --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $mcNodeVersion -notmatch '^v24\.') { throw 'Protocol interoperability checks require Node 24.' }
}
if (-not $GradlePath) { $GradlePath = Join-Path $mcProject 'gradlew.bat' }
if (-not (Test-Path -LiteralPath $GradlePath -PathType Leaf)) { throw 'Gradle executable was not found.' }

New-Item -ItemType Directory -Path $mcEvidence -Force | Out-Null
$mcBuildLog = Join-Path $mcEvidence 'fabric-build.log'
$mcEnvKeys = @('JAVA_HOME', 'GRADLE_USER_HOME', 'MC_TEST_NODE', 'TEMP', 'TMP')
$mcPreviousEnv = @{}
foreach ($mcEnvKey in $mcEnvKeys) { $mcPreviousEnv[$mcEnvKey] = [Environment]::GetEnvironmentVariable($mcEnvKey, 'Process') }
$mcExit = 1
try {
    $env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
    $env:GRADLE_USER_HOME = Join-Path $mcRepoRoot '.setup\mc-gradle'
    $mcNativeTemp = Join-Path $mcRepoRoot '.setup\mc-gradle-temp'
    New-Item -ItemType Directory -Path $mcNativeTemp -Force | Out-Null
    $env:TEMP = $mcNativeTemp
    $env:TMP = $mcNativeTemp
    if (-not $SkipInterop) { $env:MC_TEST_NODE = (Resolve-Path -LiteralPath $NodePath).Path }
    $mcArguments = @('--no-daemon', '-p', $mcProject, 'test', 'build')
    if (-not $SkipInterop) { $mcArguments += 'interopTest' }
    if ($RefreshDependencyLocks) { $mcArguments += '--write-locks' }
    $mcArguments += @('--console', 'plain')
    & $GradlePath @mcArguments 2>&1 | Tee-Object -FilePath $mcBuildLog
    $mcExit = $LASTEXITCODE
} finally {
    foreach ($mcEnvKey in $mcEnvKeys) { [Environment]::SetEnvironmentVariable($mcEnvKey, $mcPreviousEnv[$mcEnvKey], 'Process') }
}
if ($mcExit -ne 0) { throw "Fabric build or checks failed (exit $mcExit). See $mcBuildLog" }

$mcJar = Join-Path $mcProject 'build\libs\ai-talk-streamer-mc-bridge-0.1.0.jar'
$mcSchema = Join-Path $mcRepoRoot 'docs\technical\mc-live-v1\contracts\game.schema.json'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$mcArchive = [System.IO.Compression.ZipFile]::OpenRead($mcJar)
$mcSqliteVersion = '3.53.4.0'
$mcSqliteDllHash = $null
try {
    foreach ($mcRequired in @('fabric.mod.json', 'mc-bridge.mixins.json', 'mc-contracts/game.schema.json', 'dev/aitalkstreamer/mc/McBridgeClient.class')) {
        if (-not $mcArchive.GetEntry($mcRequired)) { throw "Mod JAR is missing $mcRequired" }
    }
    if ($mcArchive.Entries.FullName -match 'HeadlessBridge|Test.class$') { throw 'Test fixture classes must not be packaged in the Mod.' }
    $mcSchemaEntry = $mcArchive.GetEntry('mc-contracts/game.schema.json').Open()
    $mcHasher = [System.Security.Cryptography.SHA256]::Create()
    try { $mcEmbeddedHash = [BitConverter]::ToString($mcHasher.ComputeHash($mcSchemaEntry)).Replace('-', '').ToLowerInvariant() }
    finally { $mcSchemaEntry.Dispose(); $mcHasher.Dispose() }
    if ($mcEmbeddedHash -ne (Get-FileHash -LiteralPath $mcSchema -Algorithm SHA256).Hash.ToLowerInvariant()) { throw 'Packaged game contract differs from the authoritative Schema.' }
    $mcSqliteEntry = $mcArchive.GetEntry("META-INF/jars/sqlite-jdbc-$mcSqliteVersion.jar")
    if (-not $mcSqliteEntry) { throw 'Mod JAR is missing the locked SQLite JDBC runtime.' }
    $mcSqliteMemory = [System.IO.MemoryStream]::new()
    $mcSqliteStream = $mcSqliteEntry.Open()
    try { $mcSqliteStream.CopyTo($mcSqliteMemory) } finally { $mcSqliteStream.Dispose() }
    $mcSqliteMemory.Position = 0
    $mcSqliteArchive = [System.IO.Compression.ZipArchive]::new($mcSqliteMemory, [System.IO.Compression.ZipArchiveMode]::Read)
    try {
        foreach ($mcSqliteRequired in @('org/sqlite/JDBC.class', 'org/sqlite/native/Windows/x86_64/sqlitejdbc.dll', 'META-INF/services/java.sql.Driver')) {
            if (-not $mcSqliteArchive.GetEntry($mcSqliteRequired)) { throw "SQLite runtime is missing $mcSqliteRequired" }
        }
        $mcDllStream = $mcSqliteArchive.GetEntry('org/sqlite/native/Windows/x86_64/sqlitejdbc.dll').Open()
        $mcDllHasher = [System.Security.Cryptography.SHA256]::Create()
        try { $mcSqliteDllHash = [BitConverter]::ToString($mcDllHasher.ComputeHash($mcDllStream)).Replace('-', '').ToLowerInvariant() }
        finally { $mcDllStream.Dispose(); $mcDllHasher.Dispose() }
    } finally { $mcSqliteArchive.Dispose(); $mcSqliteMemory.Dispose() }
} finally { $mcArchive.Dispose() }

function Get-McTestSummary([string]$ReportDirectory) {
    $mcCounts = @{ tests = 0; failures = 0; errors = 0; skipped = 0 }
    $mcReportFiles = @(Get-ChildItem -LiteralPath $ReportDirectory -Filter '*.xml')
    if ($mcReportFiles.Count -eq 0) { throw "No test report found in $ReportDirectory" }
    foreach ($mcReportFile in $mcReportFiles) {
        [xml]$mcXml = Get-Content -LiteralPath $mcReportFile.FullName -Raw -Encoding UTF8
        $mcSuites = @($mcXml.SelectNodes('//testsuite[not(testsuite)]'))
        foreach ($mcSuite in $mcSuites) {
            foreach ($mcCountKey in @('tests', 'failures', 'errors', 'skipped')) {
                $mcCounts[$mcCountKey] += [int]$mcSuite.GetAttribute($mcCountKey)
            }
        }
        if ($mcSuites.Count -eq 0) {
            foreach ($mcCase in $mcXml.SelectNodes('//testcase')) {
                $mcCounts.tests++
                if ($mcCase.SelectSingleNode('failure')) { $mcCounts.failures++ }
                if ($mcCase.SelectSingleNode('error')) { $mcCounts.errors++ }
                if ($mcCase.SelectSingleNode('skipped')) { $mcCounts.skipped++ }
            }
        }
    }
    if ($mcCounts.tests -eq 0 -or $mcCounts.failures -ne 0 -or $mcCounts.errors -ne 0 -or $mcCounts.skipped -ne 0) { throw 'Test reports are empty or contain failures, errors or skipped cases.' }
    return $mcCounts
}
$mcUnitTests = Get-McTestSummary (Join-Path $mcProject 'build\test-results\test')
$mcInteropTests = $null
if (-not $SkipInterop) { $mcInteropTests = Get-McTestSummary (Join-Path $mcProject 'build\test-results\interop') }
$mcReceipt = [ordered]@{
    schema_version = 1
    recorded_at = [DateTimeOffset]::UtcNow.ToString('o')
    branch = 'mc'
    classification = 'NATIVE_BUILD_AND_CPU_PROTOCOL_CHECKS_ONLY'
    java = $mcJavaVersion
    gradle = '8.14.3'
    wrapper_jar_sha256 = $mcWrapperHash
    node = $mcNodeVersion
    unit_tests = $mcUnitTests
    interop_tests = $mcInteropTests
    interop_skipped_by_request = [bool]$SkipInterop
    jar = 'game-adapters/minecraft/fabric/build/libs/ai-talk-streamer-mc-bridge-0.1.0.jar'
    jar_sha256 = (Get-FileHash -LiteralPath $mcJar -Algorithm SHA256).Hash.ToLowerInvariant()
    embedded_schema_sha256 = $mcEmbeddedHash
    sqlite_jdbc_version = $mcSqliteVersion
    sqlite_windows_x64_dll_sha256 = $mcSqliteDllHash
    real_game_acceptance = 'not_run'
}
$mcReceiptFile = Join-Path $mcEvidence 'fabric-build-receipt.json'
$mcUtf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($mcReceiptFile, ($mcReceipt | ConvertTo-Json -Depth 5) + [Environment]::NewLine, $mcUtf8)
Write-Output "Fabric Mod built and verified. Receipt: $mcReceiptFile"
