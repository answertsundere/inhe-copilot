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
    parser.add_argument("--manual-native-stdin", action="store_true",
                        help="Private loopback preview pipe; no logging, generation or sending")
    parser.add_argument("--structured-preview-stdin", action="store_true",
                        help="Validate one scoped UIA capture; print counts only, never post or send")
    parser.add_argument("--backend", default=os.getenv("COPILOT_BACKEND", "http://127.0.0.1:5000"))
    parser.add_argument("--panel-url", default=os.getenv("COPILOT_PANEL_URL", "http://127.0.0.1:5000/copilot-panel"))
    parser.add_argument("--log-file", default=os.getenv("QIANNIU_SIDECAR_LOG", str(ROOT / "data" / "sidecar" / "qianniu_sidecar.log")))
    parser.add_argument("--interval", type=float, default=float(os.getenv("QIANNIU_SIDECAR_INTERVAL", "2.0")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("QIANNIU_SIDECAR_TIMEOUT", "10.0")))
    parser.add_argument("--open-panel", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.manual_native_stdin:
        if os.environ.get("COPILOT_QIANNIU_PREVIEW_PIPE") != "1" or sys.stdout.isatty():
            print('{"ok":false,"error":"private_preview_pipe_required"}')
            return 2
        try:
            raw = sys.stdin.read(1025)
            payload = json.loads(raw) if len(raw) <= 1024 else None
            result = manual_native_preview(payload)
        except Exception:
            result = {"ok": False, "error": "native_capture_unavailable"}
        sys.stdout.write(json.dumps(result, ensure_ascii=True))
        return 0 if result.get("ok") else 2
    if args.structured_preview_stdin:
        from scripts.sidecar.context_parser import build_uia_preview
        try:
            raw = sys.stdin.read(1_048_577)
            if len(raw) > 1_048_576:
                report = {"status": "blocked", "reason_code": "capture_size_limit"}
            else:
                report = build_uia_preview(json.loads(raw)).diagnostics
        except (ValueError, UnicodeError, RecursionError):
            report = {"status": "blocked", "reason_code": "capture_json_invalid"}
        print(json.dumps(report, ensure_ascii=True))
        return 0 if report["status"] == "preview_ready" else 2
    configure_logging(args.log_file)
    logging.info("starting qianniu sidecar backend=%s interval=%s", args.backend, args.interval)
    run_loop(args)
    return 0


def manual_native_preview(payload: Any) -> dict[str, Any]:
    """Called only by the local one-shot pipe. Never activate/type/scroll/send."""
    if not isinstance(payload, dict) or set(payload) - {"window_handle", "mode"}:
        return {"ok": False, "error": "capture_request_invalid"}
    mode = payload.get("mode", "native_selection")
    if mode not in ("native_selection", "manual_document_review"):
        return {"ok": False, "error": "capture_mode_invalid"}
    import win32gui
    import win32process
    import win32api
    import pywintypes

    windows = []
    diagnostics = {"visible_window_count": 0, "process_read_denied_count": 0}

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        diagnostics["visible_window_count"] += 1
        if not any(label in win32gui.GetWindowText(hwnd) for label in ("接待台", "接待中心")):
            return
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            process = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
            try:
                executable = win32process.GetModuleFileNameEx(process, 0)
            finally:
                process.Close()
            if Path(executable).name.lower() != "aliworkbench.exe":
                return
            windows.append({"handle": hwnd, "label": f"千牛接待窗口 {len(windows) + 1}"})
        except (pywintypes.error, OSError):
            diagnostics["process_read_denied_count"] += 1
            return

    win32gui.EnumWindows(collect, None)
    if not windows:
        return {"ok": False, "error": "qianniu_window_not_found", "diagnostics": diagnostics}
    hwnd = payload.get("window_handle")
    if hwnd is None:
        return {"ok": True, "status": "window_selection_required", "windows": windows}
    if type(hwnd) is not int or hwnd not in {w["handle"] for w in windows}:
        return {"ok": False, "error": "window_selection_invalid"}
    if win32gui.IsIconic(hwnd):
        return {"ok": False, "error": "qianniu_window_minimized"}
    from pywinauto import Desktop
    from scripts.sidecar.uia_sidebar_extractor import build_native_preview, read_native_tree

    try:
        window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        before = read_native_tree(window)
        after = read_native_tree(window)
        return build_native_preview(before, after, hwnd, mode=mode)
    except ValueError as exc:
        if str(exc) == "capture_size_limit":
            return {"ok": False, "error": "capture_size_limit"}
        return {"ok": False, "error": "native_capture_unavailable"}


if __name__ == "__main__":
    raise SystemExit(main())
