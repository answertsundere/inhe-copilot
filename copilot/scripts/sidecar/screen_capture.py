from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

from .chat_region import ChatRegion
from .config import SidecarConfig

logger = logging.getLogger(__name__)


@dataclass
class ScreenCaptureResult:
    success: bool
    image_data: bytes | None = None
    width: int = 0
    height: int = 0
    region: tuple[int, int, int, int] | None = None
    error_code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "width": self.width,
            "height": self.height,
            "region": list(self.region) if self.region else None,
            "error_code": self.error_code,
            "message": self.message,
        }


def capture_chat_region(
    hwnd: int,
    chat_region: ChatRegion,
    config: SidecarConfig | None = None,
) -> ScreenCaptureResult:
    config = config or SidecarConfig()

    try:
        import win32gui
    except Exception as exc:
        return ScreenCaptureResult(
            success=False, error_code="win32gui_unavailable",
            message=f"win32gui not available: {exc}",
        )

    try:
        import win32ui
        from PIL import Image
    except Exception as exc:
        return ScreenCaptureResult(
            success=False, error_code="pillow_unavailable",
            message=f"PIL/win32ui not available: {exc}",
        )

    if win32gui.IsIconic(hwnd):
        return ScreenCaptureResult(
            success=False, error_code="window_minimized",
            message="请打开千牛接待中心窗口后重试",
        )

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        window_width = right - left
        window_height = bottom - top
    except Exception as exc:
        return ScreenCaptureResult(
            success=False, error_code="get_rect_failed",
            message=f"Cannot get window rect: {exc}",
        )

    crop_left, crop_top, crop_right, crop_bottom = chat_region.to_pixels(window_width, window_height)
    abs_left = left + crop_left
    abs_top = top + crop_top
    abs_right = left + crop_right
    abs_bottom = top + crop_bottom
    crop_width = abs_right - abs_left
    crop_height = abs_bottom - abs_top

    if crop_width <= 0 or crop_height <= 0:
        return ScreenCaptureResult(
            success=False, error_code="invalid_region",
            message=f"Invalid capture region: {crop_width}x{crop_height}",
        )

    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, crop_width, crop_height)
        save_dc.SelectObject(bitmap)

        save_dc.BitBlt((0, 0), (crop_width, crop_height), mfc_dc, (crop_left, crop_top), 0x00CC0020)

        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)

        img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_bits,
            "raw",
            "BGRX",
            0,
            1,
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_data = buf.getvalue()

        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        win32gui.DeleteObject(bitmap.GetHandle())

    except Exception as exc:
        logger.warning("screenshot capture failed: %s", exc)
        return ScreenCaptureResult(
            success=False, error_code="capture_failed",
            message=f"Screenshot capture failed: {exc}",
        )

    if config.save_screenshot_debug:
        try:
            from pathlib import Path
            debug_dir = Path(config.log_file).parent if config.log_file else Path(".")
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / "debug_screenshot.png"
            debug_path.write_bytes(image_data)
            logger.info("debug screenshot saved to %s", debug_path)
        except Exception as exc:
            logger.warning("save debug screenshot failed: %s", exc)

    return ScreenCaptureResult(
        success=True,
        image_data=image_data,
        width=crop_width,
        height=crop_height,
        region=(abs_left, abs_top, abs_right, abs_bottom),
    )
