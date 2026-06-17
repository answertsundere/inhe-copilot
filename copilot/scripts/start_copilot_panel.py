"""
INHE 客服 Copilot 面板启动脚本

功能：
1. 检查 Flask 后端是否运行（http://127.0.0.1:5000/api/health）
2. 如果没运行，提示用户先启动后端
3. 用默认浏览器打开 compact 模式的 Copilot 面板
"""

import sys
import webbrowser

COMPACT_URL = "http://127.0.0.1:5000/copilot-panel?mode=compact"
HEALTH_URL = "http://127.0.0.1:5000/api/health"


def check_backend():
    """检查后端是否运行"""
    try:
        import urllib.request
        resp = urllib.request.urlopen(HEALTH_URL, timeout=3)
        return resp.status == 200
    except Exception:
        return False


def main():
    print("=" * 50)
    print("  INHE 客服 Copilot 面板启动")
    print("=" * 50)

    if check_backend():
        print("[OK] 后端运行中，正在打开面板...")
        webbrowser.open(COMPACT_URL)
        print(f"面板地址: {COMPACT_URL}")
        print("可以关闭此窗口。")
    else:
        print("[!] 后端未运行。")
        print("请先启动后端：")
        print("  cd copilot")
        print("  python run_web.py")
        print()
        print("启动后重新运行此脚本。")
        sys.exit(1)


if __name__ == "__main__":
    main()
