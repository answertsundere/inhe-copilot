# 一键创建 Windows 定时任务：每天同步钉钉媒体数据到商品库
# 右键 "使用 PowerShell 运行" 即可

$taskName = "INHE-SyncDingTalkMedia"
$batPath = Join-Path $PSScriptRoot "run_daily_sync.bat"

if (-not (Test-Path $batPath)) {
    Write-Host "错误: 找不到 $batPath" -ForegroundColor Red
    pause
    exit 1
}

# 如果已存在则先删除旧任务
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "已删除旧任务: $taskName" -ForegroundColor Yellow
}

# 创建任务（每天早上 8:57 运行，避开整点 herd）
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:57"
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest

Register-ScheduledTask -TaskName $taskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "每天同步钉钉多维表的安装视频、打包指南和SKU图到INHE商品知识库" | Out-Null

Write-Host "✅ 定时任务创建成功!" -ForegroundColor Green
Write-Host "   任务名称: $taskName"
Write-Host "   执行时间: 每天 08:57"
Write-Host "   执行脚本: $batPath"
Write-Host ""
Write-Host "你可以通过以下方式管理:"
Write-Host "   • 打开 '任务计划程序' (taskschd.msc) 查看"
Write-Host "   • 或运行: schtasks /query /tn $taskName"
Write-Host "   • 手动测试: schtasks /run /tn $taskName"
pause
