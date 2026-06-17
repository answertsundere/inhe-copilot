param(
    [string]$Backend = "http://192.168.110.144:5000",
    [string]$PanelUrl = "http://192.168.110.144:5000/copilot-panel",
    [string]$VisionBaseUrl = "https://apihub.agnes-ai.com/v1",
    [string]$VisionModel = "agnes-2.0-flash",
    [string]$VisionProvider = "custom"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
Set-Location $projectRoot

function Find-Python {
    $candidates = @()

    try {
        $py = Get-Command "py.exe" -ErrorAction Stop
        $candidates += @{ File = $py.Source; Args = @("-3") }
    } catch {
    }

    $knownRoots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        (Join-Path $env:ProgramFiles "Python312"),
        (Join-Path $env:ProgramFiles "Python311"),
        (Join-Path ${env:ProgramFiles(x86)} "Python312"),
        (Join-Path ${env:ProgramFiles(x86)} "Python311")
    )
    foreach ($root in $knownRoots) {
        if (-not $root -or -not (Test-Path $root)) {
            continue
        }
        Get-ChildItem -Path $root -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object {
                $candidates += @{ File = $_.FullName; Args = @() }
            }
    }

    foreach ($name in @("python.exe", "python3.exe")) {
        try {
            $cmd = Get-Command $name -ErrorAction Stop
            if ($cmd.Source -notlike "*\WindowsApps\*") {
                $candidates += @{ File = $cmd.Source; Args = @() }
            }
        } catch {
        }
    }

    foreach ($candidate in $candidates) {
        try {
            $versionOutput = & $candidate.File @($candidate.Args) --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$versionOutput" -match "Python 3\.(1[1-9]|[2-9][0-9])") {
                return $candidate
            }
        } catch {
        }
    }
    return $null
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

Write-Host "INHE Copilot Sidecar client installer v2.1" -ForegroundColor Cyan
Write-Host "Project root: $projectRoot"
Write-Host "Backend: $Backend"

if (-not (Test-Backend $Backend)) {
    Write-Host "Warning: backend is not reachable now: $Backend" -ForegroundColor Yellow
    Write-Host "Install will continue. Check backend and firewall before using Sidecar."
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python not found. Trying winget install Python 3.12..." -ForegroundColor Yellow
    try {
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    } catch {
        Write-Host "winget install failed: $($_.Exception.Message)" -ForegroundColor Red
    }
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
    $python = Find-Python
}

if (-not $python) {
    Write-Host "Python is still not available." -ForegroundColor Red
    Write-Host "Install Python 3.11+ with Add Python to PATH, then run this installer again."
    Read-Host "Press Enter to exit"
    exit 1
}

$pythonExe = $python.File
$pythonArgs = $python.Args
if ($pythonExe -like "*\WindowsApps\*") {
    Write-Host "Rejected Microsoft Store Python alias: $pythonExe" -ForegroundColor Red
    Write-Host "This installer must use a real Python installation."
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "Python: $pythonExe $($pythonArgs -join ' ')" -ForegroundColor Green

$venvDir = Join-Path $projectRoot ".venv-sidecar"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if ((Test-Path $venvDir) -and -not (Test-Path $venvPython)) {
    Write-Host "Removing incomplete virtual environment..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $venvDir -Recurse -Force
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Sidecar virtual environment..."
    & $pythonExe @pythonArgs -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python failed to create the virtual environment (exit code $LASTEXITCODE)." -ForegroundColor Red
    }
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Virtual environment creation failed: $venvPython" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Installing dependencies. First run can take several minutes..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython -m pip install "Pillow>=10.0.0"

$sidecarDataDir = Join-Path $projectRoot "data\sidecar"
New-Item -ItemType Directory -Force -Path $sidecarDataDir | Out-Null

$secure = Read-Host "Enter VLM API Key (hidden; saved to local client.env)" -AsSecureString
$plainKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
)

$envFile = Join-Path $sidecarDataDir "client.env"
@(
    "COPILOT_BACKEND=$Backend",
    "COPILOT_PANEL_URL=$PanelUrl",
    "SIDECAR_ENABLE_VISION=true",
    "SIDECAR_VISION_PROVIDER=$VisionProvider",
    "SIDECAR_VISION_BASE_URL=$VisionBaseUrl",
    "SIDECAR_VISION_MODEL=$VisionModel",
    "SIDECAR_VISION_TIMEOUT_SECONDS=30",
    "SIDECAR_VISION_MIN_CONFIDENCE=0.5",
    "SIDECAR_VISION_REQUIRE_CONFIRM=true",
    "SIDECAR_VISION_API_KEY=$plainKey",
    "QIANNIU_SIDECAR_INTERVAL=2",
    "QIANNIU_STABLE_READS=1"
) | Set-Content -Path $envFile -Encoding UTF8

$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "INHE-Copilot-Sidecar.lnk"
$targetPath = Join-Path $scriptDir "start_sidecar_client.bat"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
$shortcut.Save()

Write-Host "Install complete." -ForegroundColor Green
Write-Host "Desktop shortcut created: INHE-Copilot-Sidecar"
Write-Host "Daily use: open QianNiu reception window, then double click INHE-Copilot-Sidecar."
Write-Host "Panel URL: $PanelUrl"
Read-Host "Press Enter to start Sidecar now"
& (Join-Path $scriptDir "start_sidecar_client.bat")
