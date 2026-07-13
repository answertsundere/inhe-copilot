"""Read-only OCR adapters for the composable visual-grounding shadow PoC."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from typing import Any

from PIL import Image

from app.services.composable_vision_grounding_service import normalize_ocr_items
from app.services.product_media_observation_service import _high_risk_attribute


_POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
_DIMENSION = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|cm|m|毫米|厘米|米)\b", re.IGNORECASE)
_MODE_HINTS = ("模式", "状态", "展开", "折叠", "坐姿", "mode", "folded", "open")
_PACKAGING_HINTS = ("包装", "纸箱", "外箱", "发货", "carton", "package", "box")


_WINDOWS_OCR_CAPABILITY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'windows_ocr_engine_unavailable' }
@{ available = $true; language = $engine.RecognizerLanguage.LanguageTag; max_image_dimension = $engine.MaxImageDimension } | ConvertTo-Json -Compress
'''


_WINDOWS_OCR_EXECUTION_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapPixelFormat,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapAlphaMode,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult,Windows.Media.Ocr,ContentType=WindowsRuntime]
function AwaitWinRt($operation, $resultType) {
  $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.ToString() -like 'Windows.Foundation.IAsyncOperation*'
  } | Select-Object -First 1
  if ($null -eq $method) { throw 'windows_ocr_async_bridge_unavailable' }
  return $method.MakeGenericMethod($resultType).Invoke($null, @($operation)).Result
}
$file = AwaitWinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:COPILOT_OCR_IMAGE_PATH)) ([Windows.Storage.StorageFile])
$stream = AwaitWinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = AwaitWinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = AwaitWinRt ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'windows_ocr_engine_unavailable' }
$result = AwaitWinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$items = @()
foreach ($line in $result.Lines) {
  $words = @($line.Words)
  if ($words.Count -eq 0) { continue }
  $left = [double]::PositiveInfinity; $top = [double]::PositiveInfinity; $right = 0.0; $bottom = 0.0
  $text = ''
  foreach ($word in $words) {
    $text += $word.Text
    $rect = $word.BoundingRect
    $left = [Math]::Min($left, [double]$rect.X); $top = [Math]::Min($top, [double]$rect.Y)
    $right = [Math]::Max($right, [double]($rect.X + $rect.Width)); $bottom = [Math]::Max($bottom, [double]($rect.Y + $rect.Height))
  }
  if ($text) { $items += [pscustomobject]@{ text = $text; x = $left; y = $top; width = $right - $left; height = $bottom - $top } }
}
@{ language = $engine.RecognizerLanguage.LanguageTag; items = @($items) } | ConvertTo-Json -Compress -Depth 4
'''


def _text(value: Any) -> str:
    return str(value or "").strip()


def _run_powershell(script: str, *, timeout_seconds: int, environment: dict[str, str] | None = None) -> dict[str, Any]:
    if not _POWERSHELL:
        return {"ok": False, "error": "powershell_not_available"}
    env = os.environ.copy()
    env.update(environment or {})
    try:
        completed = subprocess.run(
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, timeout_seconds),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "windows_ocr_timeout"}
    if completed.returncode != 0:
        return {"ok": False, "error": "windows_ocr_execution_error"}
    try:
        return {"ok": True, "payload": json.loads(completed.stdout)}
    except json.JSONDecodeError:
        return {"ok": False, "error": "windows_ocr_schema_error"}


def windows_ocr_status(*, timeout_seconds: int = 5) -> dict[str, Any]:
    """Detect Windows OCR without treating runtime presence as qualification."""
    if platform.system() != "Windows" or not _POWERSHELL:
        return {"available": False, "reason": "windows_ocr_not_supported"}
    result = _run_powershell(_WINDOWS_OCR_CAPABILITY_SCRIPT, timeout_seconds=timeout_seconds)
    if not result.get("ok") or not isinstance(result.get("payload"), dict):
        return {"available": False, "reason": result.get("error") or "windows_ocr_not_available"}
    payload = result["payload"]
    return {
        "available": bool(payload.get("available")),
        "provider_name": "windows_ocr",
        "model_name": "Windows.Media.Ocr.OcrEngine",
        "runtime_name": "Windows Runtime",
        "language": _text(payload.get("language")),
        "max_image_dimension": payload.get("max_image_dimension"),
    }


def installed_ocr_runtimes(*, timeout_seconds: int = 5) -> dict[str, Any]:
    """Report local OCR availability without importing or installing packages."""
    return {
        "windows_ocr": windows_ocr_status(timeout_seconds=timeout_seconds),
        "paddleocr": {"available": importlib.util.find_spec("paddleocr") is not None},
        "tesseract": {"available": bool(importlib.util.find_spec("pytesseract") and shutil.which("tesseract"))},
        "easyocr": {"available": importlib.util.find_spec("easyocr") is not None},
    }


def preferred_ocr_provider(*, requested_provider: str = "auto", timeout_seconds: int = 5) -> dict[str, Any]:
    runtimes = installed_ocr_runtimes(timeout_seconds=timeout_seconds)
    requested = _text(requested_provider).lower() or "auto"
    if requested in {"auto", "windows_ocr"} and runtimes["windows_ocr"].get("available"):
        return {"configured": True, **runtimes["windows_ocr"], "runtimes": runtimes}
    return {
        "configured": False,
        "provider_name": requested,
        "reason": "provider_not_configured",
        "minimum_install_guidance": "启用 Windows OCR 语言包，或安装 PaddleOCR 后重新运行资格评测。",
        "runtimes": runtimes,
    }


def classify_ocr_text(text: str) -> dict[str, bool]:
    normalized = _text(text).lower()
    return {
        "dimension_text": bool(_DIMENSION.search(normalized)),
        "mode_text": any(hint in normalized for hint in _MODE_HINTS),
        "packaging_text": any(hint in normalized for hint in _PACKAGING_HINTS),
        "high_risk_text": bool(_high_risk_attribute(normalized)),
    }


def _source_image_size(image_data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(image_data)) as image:
        return int(image.width), int(image.height)


def recognize_windows_ocr(*, image_data: bytes, extension: str, image_sha256: str, timeout_seconds: int = 20) -> dict[str, Any]:
    """Return normalized OCR label candidates; never creates visual observations."""
    status = windows_ocr_status(timeout_seconds=min(timeout_seconds, 5))
    if not status.get("available"):
        return {"provider_name": "windows_ocr", "model_name": "Windows.Media.Ocr.OcrEngine", "image_sha256": image_sha256, "items": [], "execution_error": status.get("reason") or "provider_not_configured", "schema_error": ""}
    image_size = _source_image_size(image_data)
    suffix = extension if _text(extension).startswith(".") else ".png"
    temp_path = ""
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(prefix="copilot_ocr_", suffix=suffix, delete=False) as handle:
            handle.write(image_data)
            temp_path = handle.name
        result = _run_powershell(_WINDOWS_OCR_EXECUTION_SCRIPT, timeout_seconds=timeout_seconds, environment={"COPILOT_OCR_IMAGE_PATH": temp_path})
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    base = {
        "provider_name": "windows_ocr",
        "model_name": "Windows.Media.Ocr.OcrEngine",
        "runtime_name": "Windows Runtime",
        "image_sha256": image_sha256,
        "source_image_size": {"width": image_size[0], "height": image_size[1]},
        "latency_ms": latency_ms,
        "execution_error": "",
        "schema_error": "",
        "items": [],
    }
    if not result.get("ok"):
        base["execution_error"] = _text(result.get("error")) or "windows_ocr_execution_error"
        return base
    payload = result.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        base["schema_error"] = "windows_ocr_schema_error"
        return base
    raw_items = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        raw_items.append({
            "text": item.get("text"),
            "bbox": {"x": item.get("x"), "y": item.get("y"), "width": item.get("width"), "height": item.get("height"), "coordinate_space": "pixel"},
            "confidence": 1.0,
            "source": "windows_ocr",
        })
    normalized = normalize_ocr_items(raw_items, image_size=image_size)
    if raw_items and not normalized:
        base["schema_error"] = "windows_ocr_no_valid_text_bbox"
        return base
    language = _text(payload.get("language")) or _text(status.get("language"))
    base["items"] = [
        {
            **item,
            "provider_name": base["provider_name"],
            "model_name": base["model_name"],
            "image_sha256": image_sha256,
            "language": language,
            "script": "han" if language.lower().startswith("zh") else "latin_or_mixed",
            "source_image_size": base["source_image_size"],
            "latency_ms": latency_ms,
            "execution_error": "",
            "schema_error": "",
            "classification": classify_ocr_text(item["text"]),
            "observation_eligible": False,
        }
        for item in normalized
    ]
    return base
