param(
    [string]$Backend = "http://192.168.110.144:5000",
    [string]$PanelUrl = "http://192.168.110.144:5000/copilot-panel",
    [string]$VisionBaseUrl = "https://apihub.agnes-ai.com/v1",
    [string]$VisionModel = "agnes-2.0-flash",
    [string]$VisionProvider = "custom",
    [switch]$NoVision
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
Set-Location $projectRoot

function Import-ClientEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

function Test-Backend {
    param([string]$Url)
    try {
        $healthUrl = $Url.TrimEnd("/") + "/api/health"
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        return ($resp.StatusCode -eq 200)
    } catch {
        return $false
    }
}

$clientEnvPath = Join-Path $projectRoot "data\sidecar\client.env"
Import-ClientEnv $clientEnvPath

if ($env:COPILOT_BACKEND) { $Backend = $env:COPILOT_BACKEND }
if ($env:COPILOT_PANEL_URL) { $PanelUrl = $env:COPILOT_PANEL_URL }
if ($env:SIDECAR_VISION_BASE_URL) { $VisionBaseUrl = $env:SIDECAR_VISION_BASE_URL }
if ($env:SIDECAR_VISION_MODEL) { $VisionModel = $env:SIDECAR_VISION_MODEL }
if ($env:SIDECAR_VISION_PROVIDER) { $VisionProvider = $env:SIDECAR_VISION_PROVIDER }

if (-not (Test-Backend $Backend)) {
    Write-Host "Copilot backend connection failed: $Backend" -ForegroundColor Red
    Write-Host "Check that the backend host is running and port 5000 is allowed by firewall."
    Write-Host "Panel URL: $PanelUrl"
    Read-Host "Press Enter to exit"
    exit 1
}

$env:COPILOT_BACKEND = $Backend
$env:COPILOT_PANEL_URL = $PanelUrl
$env:QIANNIU_SIDECAR_INTERVAL = "2"
$env:QIANNIU_STABLE_READS = "1"
$env:QIANNIU_SIDECAR_LOG = Join-Path $projectRoot "data\sidecar\qianniu_sidecar.log"

if ($NoVision) {
    $env:SIDECAR_ENABLE_VISION = "false"
} else {
    $env:SIDECAR_ENABLE_VISION = "true"
    $env:SIDECAR_VISION_PROVIDER = $VisionProvider
    $env:SIDECAR_VISION_BASE_URL = $VisionBaseUrl
    $env:SIDECAR_VISION_MODEL = $VisionModel
    $env:SIDECAR_VISION_TIMEOUT_SECONDS = "30"
    $env:SIDECAR_VISION_MIN_CONFIDENCE = "0.5"
    $env:SIDECAR_VISION_REQUIRE_CONFIRM = "true"

    if (-not $env:SIDECAR_VISION_API_KEY) {
        $secure = Read-Host "Enter VLM API Key (hidden)" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        )
        $env:SIDECAR_VISION_API_KEY = $plain
    }
}

Write-Host "Copilot backend: $Backend" -ForegroundColor Green
Write-Host "Panel URL: $PanelUrl" -ForegroundColor Green
Write-Host "Keep QianNiu reception window open and not minimized." -ForegroundColor Yellow
Write-Host "Sidecar is starting. Closing this window stops auto detection."

$venvPython = Join-Path $projectRoot ".venv-sidecar\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython scripts\sidecar\qianniu_sidecar.py --vision-provider $VisionProvider --auto-analyze --stable-reads 1
} else {
    python scripts\sidecar\qianniu_sidecar.py --vision-provider $VisionProvider --auto-analyze --stable-reads 1
}
