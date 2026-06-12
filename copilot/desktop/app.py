"""
Main pywebview Application — 窗口 + 托盘 + 启动
"""

import os
import sys

from desktop.config_store import load_config
from desktop.api_bridge import ApiBridge

# 确保项目根目录在 path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    cfg = load_config()
    always_on_top = cfg.get("always_on_top", True)

    try:
        import webview
    except ImportError:
        print("[!] pywebview 未安装，回退到浏览器模式。")
        print("  安装: pip install pywebview")
        import webbrowser
        webbrowser.open(f"{cfg.get('server_base_url', 'http://127.0.0.1:5000')}/copilot-panel?mode=compact")
        return

    index_html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages", "index.html")
    if not os.path.exists(index_html):
        print(f"[!] 渲染器文件不存在: {index_html}")
        return

    api = ApiBridge()
    if cfg.get("auto_start_sidecar", True):
        api.start_sidecar()
    window = webview.create_window(
        title="INHE 客服 Copilot",
        url=index_html,
        js_api=api,
        width=500,
        height=840,
        resizable=True,
        frameless=False,
        easy_drag=True,
        on_top=always_on_top,
        min_size=(420, 600),
    )
    api._window = window

    # 托盘菜单
    try:
        import webview.menu
        menu_items = [
            webview.menu.Menu(
                "操作",
                [
                    webview.menu.MenuAction("打开 Copilot", lambda: _show_window(window)),
                    webview.menu.MenuAction("启动 Sidecar", lambda: api.start_sidecar()),
                    webview.menu.MenuAction("停止 Sidecar", lambda: api.stop_sidecar()),
                    webview.menu.MenuSeparator(),
                    webview.menu.MenuAction("置顶窗口", lambda: _toggle_top(window)),
                    webview.menu.MenuSeparator(),
                    webview.menu.MenuAction("退出", lambda: _quit(window)),
                ]
            ),
        ]
        gui = "edgechromium" if sys.platform == "win32" else None
        webview.start(menu=menu_items, gui=gui, debug=False)
    except (ImportError, AttributeError, TypeError):
        # 托盘不可用，直接启动窗口
        gui = "edgechromium" if sys.platform == "win32" else None
        webview.start(gui=gui, debug=False)


def _show_window(window):
    try:
        window.restore()
    except Exception:
        pass


def _toggle_top(window):
    try:
        window.on_top = not getattr(window, "on_top", False)
    except Exception:
        pass


def _quit(window):
    try:
        window.destroy()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
