from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.sidecar_context_service import build_sidecar_context


WINDOW_TITLE_KEYWORDS = ("千牛", "旺旺", "阿里旺旺", "接待台", "接待中心")


@dataclass
class QianNiuSnapshot:
    window_title: str
    chat_text: str
    raw_context: dict[str, Any]


def configure_logging(log_file: str) -> None:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _load_pywinauto():
    try:
        from pywinauto import Desktop
        return Desktop
    except Exception as exc:
        logging.warning("pywinauto is unavailable: %s", exc)
        return None


def _find_qianniu_hwnd() -> int | None:
    try:
        import win32gui
    except Exception as exc:
        logging.warning("win32gui is unavailable: %s", exc)
        return None

    matches: list[int] = []

    def enum_handler(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = (win32gui.GetWindowText(hwnd) or "").strip()
        except Exception:
            return
        if title and any(keyword in title for keyword in WINDOW_TITLE_KEYWORDS):
            matches.append(hwnd)

    win32gui.EnumWindows(enum_handler, None)
    return matches[0] if matches else None


def find_qianniu_window() -> Any | None:
    hwnd = _find_qianniu_hwnd()
    if not hwnd:
        return None
    Desktop = _load_pywinauto()
    if Desktop is None:
        return None
    try:
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception as exc:
        logging.warning("attach qianniu window failed: %s", exc)
        return None


def find_qianniu_title_without_uia() -> str:
    try:
        import win32gui
    except Exception:
        return ""
    hwnd = _find_qianniu_hwnd()
    if not hwnd:
        return ""
    try:
        return (win32gui.GetWindowText(hwnd) or "").strip()
    except Exception:
        return ""


def read_window_text(window: Any, max_items: int = 600) -> str:
    texts: list[str] = []
    try:
        controls = window.descendants(control_type="Text")
    except Exception as exc:
        logging.warning("read descendants failed: %s", exc)
        controls = []

    for control in controls[:max_items]:
        _append_control_text(texts, control)

    if not texts:
        try:
            controls = window.descendants()
        except Exception as exc:
            logging.warning("read all descendants failed: %s", exc)
            controls = []
        for control in controls[:max_items]:
            _append_control_text(texts, control)

    return "\n".join(texts)


def _append_control_text(texts: list[str], control: Any) -> None:
    candidates: list[str] = []
    try:
        candidates.append((control.window_text() or "").strip())
    except Exception:
        pass
    try:
        candidates.append((control.element_info.name or "").strip())
    except Exception:
        pass
    for text in candidates:
        if not text:
            continue
        if len(text) > 500:
            text = text[:500]
        if text and text not in texts:
            texts.append(text)


def capture_snapshot() -> QianNiuSnapshot | None:
    window = find_qianniu_window()
    if window is None:
        return None
    try:
        title = (window.window_text() or "").strip()
    except Exception:
        title = ""
    chat_text = read_window_text(window)
    return QianNiuSnapshot(
        window_title=title,
        chat_text=chat_text,
        raw_context={"text_line_count": len([line for line in chat_text.splitlines() if line.strip()])},
    )


def build_payload(snapshot: QianNiuSnapshot) -> dict[str, Any]:
    return build_sidecar_context({
        "source": "qianniu_sidecar",
        "window_title": snapshot.window_title,
        "chat_text": snapshot.chat_text,
        "raw_context": snapshot.raw_context,
    })


def post_context(backend: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    url = backend.rstrip("/") + "/api/copilot/context"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        logging.error("backend returned %s: %s", exc.code, raw[:500])
        return {"ok": False, "status": exc.code, "raw": raw}
    except Exception as exc:
        logging.error("post context failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def run_loop(args: argparse.Namespace) -> None:
    if args.open_panel:
        webbrowser.open(args.panel_url)

    last_key = ""
    while True:
        snapshot = capture_snapshot()
        if snapshot is None:
            logging.info("qianniu window not found")
        else:
            payload = build_payload(snapshot)
            key = f"{payload.get('conversation_id')}|{payload.get('customer_message')}"
            if payload.get("customer_message") and key != last_key:
                logging.info(
                    "captured title=%s lines=%s message=%s identifier_type=%s",
                    payload.get("window_title"),
                    snapshot.raw_context.get("text_line_count"),
                    payload.get("customer_message"),
                    payload.get("identifier_type"),
                )
                result = post_context(args.backend, payload, timeout=args.timeout)
                logging.info("copilot result=%s", json.dumps({
                    "ok": result.get("ok"),
                    "intent": result.get("intent"),
                    "risk_level": result.get("risk_level"),
                    "reply_len": len(result.get("suggested_reply", "")),
                }, ensure_ascii=False))
                last_key = key
            elif not payload.get("customer_message"):
                logging.info(
                    "no customer message parsed title=%s lines=%s",
                    payload.get("window_title"),
                    snapshot.raw_context.get("text_line_count"),
                )

        if args.once:
            break
        time.sleep(args.interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QianNiu desktop Sidecar POC")
    parser.add_argument("--backend", default=os.getenv("COPILOT_BACKEND", "http://127.0.0.1:5000"))
    parser.add_argument("--panel-url", default=os.getenv("COPILOT_PANEL_URL", "http://127.0.0.1:5000/copilot-panel"))
    parser.add_argument("--log-file", default=os.getenv("QIANNIU_SIDECAR_LOG", str(ROOT / "data" / "sidecar" / "qianniu_sidecar.log")))
    parser.add_argument("--interval", type=float, default=float(os.getenv("QIANNIU_SIDECAR_INTERVAL", "2.0")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("QIANNIU_SIDECAR_TIMEOUT", "10.0")))
    parser.add_argument("--open-panel", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_file)
    logging.info("starting qianniu sidecar backend=%s interval=%s", args.backend, args.interval)
    run_loop(args)


if __name__ == "__main__":
    main()
