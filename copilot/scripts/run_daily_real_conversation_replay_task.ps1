param(
    [string]$ProjectDir = "",
    [string]$SourceDir = "",
    [int]$SampleLimit = 50,
    [int]$MinTurns = 6,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $workspaceRoot = Split-Path (Split-Path $ProjectDir -Parent) -Parent
    $SourceDir = Join-Path $workspaceRoot ([string]::Concat([char[]](0x5ba2, 0x670d, 0x8d28, 0x68c0, 0x7cfb, 0x7edf)))
}

Set-Location -LiteralPath $ProjectDir

$OutputDir = Join-Path $ProjectDir "outputs"
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$ReplayDate = Get-Date -Format "yy-M-d"
$OutputDate = Get-Date -Format "yyyyMMdd"
$OutputPath = Join-Path $OutputDir "real_conversation_daily_$OutputDate.json"
$LogPath = Join-Path $OutputDir "real_conversation_daily_$OutputDate.log"
$StdoutPath = Join-Path $OutputDir "real_conversation_daily_$OutputDate.stdout.tmp"
$StderrPath = Join-Path $OutputDir "real_conversation_daily_$OutputDate.stderr.tmp"

$Arguments = @(
    "scripts\run_daily_real_conversation_replay.py",
    "--source-dir", $SourceDir,
    "--date", $ReplayDate,
    "--sample-limit", $SampleLimit,
    "--min-turns", $MinTurns,
    "--apply",
    "--generate-repair-tasks",
    "--json-output", $OutputPath
)

try {
    Remove-Item -LiteralPath $StdoutPath, $StderrPath -ErrorAction SilentlyContinue
    $Process = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $Arguments `
        -WorkingDirectory $ProjectDir `
        -NoNewWindow `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath

    $OutputLines = @()
    if (Test-Path -LiteralPath $StdoutPath) {
        $OutputLines += Get-Content -LiteralPath $StdoutPath
    }
    if (Test-Path -LiteralPath $StderrPath) {
        $OutputLines += Get-Content -LiteralPath $StderrPath
    }
    $OutputLines | Tee-Object -FilePath $LogPath

    if ($Process.ExitCode -ne 0) {
        throw "Daily real conversation replay failed with exit code $($Process.ExitCode)"
    }
    Write-Output "success output=$OutputPath log=$LogPath"
}
catch {
    "failed $($_.Exception.Message)" | Tee-Object -FilePath $LogPath -Append
    throw
}
finally {
    Remove-Item -LiteralPath $StdoutPath, $StderrPath -ErrorAction SilentlyContinue
}
