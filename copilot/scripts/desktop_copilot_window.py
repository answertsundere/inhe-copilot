"""
INHE 客服 Copilot 桌面小窗

使用 pywebview 打开 480x820 桌面窗口加载 compact 模式面板。
如果 pywebview 不可用，回退到默认浏览器。

窗口参数：
- 宽度: 480px
- 高度: 820px
- 标题: INHE 客服 Copilot
- 可选: always_on_top
"""

import sys
import webbrowser

COMPACT_URL = "http://127.0.0.1:5000/copilot-panel?mode=compact"
HEALTH_URL = "http://127.0.0.1:5000/api/health"


def check_backend():
    try:
        import urllib.request
        resp = urllib.request.urlopen(HEALTH_URL, timeout=3)
        return resp.status == 200
    except Exception:
        return False


def open_pywebview():
    import webview
    window = webview.create_window(
        title="INHE 客服 Copilot",
        url=COMPACT_URL,
        width=480,
        height=820,
        resizable=True,
        frameless=False,
        easy_drag=True,
    )
    # always_on_top 需要在 start 时通过参数传入
    webview.start(gui="edgechromium" if sys.platform == "win32" else None)


def main():
    print("=" * 50)
    print("  INHE 客服 Copilot 桌面小窗")
    print("=" * 50)

    if not check_backend():
        print("[!] 后端未运行。")
        print("请先启动后端：")
        print("  cd copilot")
        print("  python run_web.py")
        sys.exit(1)

    try:
        print("[OK] 后端运行中，正在打开桌面窗口...")
        open_pywebview()
    except ImportError:
        print("[!] pywebview 未安装，回退到浏览器。")
        print("  安装 pywebview: pip install pywebview")
        webbrowser.open(COMPACT_URL)
    except Exception as e:
        print(f"[!] 桌面窗口失败 ({e})，回退到浏览器。")
        webbrowser.open(COMPACT_URL)


if __name__ == "__main__":
    main()
