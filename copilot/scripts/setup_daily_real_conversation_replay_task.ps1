param(
    [string]$TaskName = "INHE Copilot Daily Real Conversation Replay",
    [string]$ProjectDir = "",
    [string]$SourceDir = "",
    [string]$Time = "13:00",
    [int]$SampleLimit = 50,
    [int]$MinTurns = 6,
    [switch]$WhatIfMode
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $workspaceRoot = Split-Path (Split-Path $ProjectDir -Parent) -Parent
    $SourceDir = Join-Path $workspaceRoot ([string]::Concat([char[]](0x5ba2, 0x670d, 0x8d28, 0x68c0, 0x7cfb, 0x7edf)))
}

$WrapperPath = Join-Path $ProjectDir "scripts\run_daily_real_conversation_replay_task.ps1"
if (-not (Test-Path -LiteralPath $WrapperPath)) {
    throw "Daily replay wrapper not found: $WrapperPath"
}

$ActionArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$WrapperPath`"",
    "-ProjectDir", "`"$ProjectDir`"",
    "-SourceDir", "`"$SourceDir`"",
    "-SampleLimit", $SampleLimit,
    "-MinTurns", $MinTurns
) -join " "

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $ActionArguments -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if ($WhatIfMode) {
    Write-Output "what-if task=$TaskName trigger=$Time wrapper=$WrapperPath"
    Write-Output "manual-run: schtasks /Run /TN `"$TaskName`""
    return
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Run INHE Copilot daily real conversation replay and generate repair/knowledge gap tasks." `
    -Force | Out-Null

Write-Output "created task=$TaskName trigger=$Time"
Write-Output "manual-run: schtasks /Run /TN `"$TaskName`""
