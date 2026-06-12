"""Launch script: forces fresh imports then starts server with /ask prefix support."""
import sys
import os

# Prevent bytecode writing entirely
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Remove ALL cached modules
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith("app") or mod_name.startswith("run_"):
        del sys.modules[mod_name]

# Invalidate import caches
import importlib
importlib.invalidate_caches()

print(f"[launcher] Modules reset, starting fresh imports")

from app.main import create_app
from app.config import WEB_HOST, WEB_PORT


class StripAskPrefix:
    """WSGI middleware: strips /ask prefix transparently before Flask routing."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith("/ask/"):
            environ["PATH_INFO"] = path[4:]
        elif path == "/ask":
            environ["PATH_INFO"] = "/"
        return self.app(environ, start_response)


def main():
    # Port conflict detection
    import socket
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1)
        result = test_sock.connect_ex((WEB_HOST, WEB_PORT))
        test_sock.close()
        if result == 0:
            print(f"\n[launcher][错误] 端口 {WEB_PORT} 已被占用！")
            print(f"  可能已有 Copilot 进程在运行。")
            print(f"  请先停止旧进程（检查 PID）或使用其他端口。\n")
            import sys
            sys.exit(1)
    except Exception:
        pass

    try:
        from sqlalchemy import inspect as sa_inspect
        from app.models.kb_tables import KBQA, KBReviewTask
        list(sa_inspect(KBQA).relationships.keys())
        list(sa_inspect(KBReviewTask).relationships.keys())
    except Exception:
        pass

    app = create_app()
    wrapped = StripAskPrefix(app)

    print(f"[launcher] Server: {WEB_HOST}:{WEB_PORT}")
    print(f"[launcher] https://www.inhe.ccwu.cc/ask/")
    print(f"[launcher] https://www.inhe.ccwu.cc/ask/kb-admin/")

    try:
        from waitress import serve
        serve(wrapped, host=WEB_HOST, port=WEB_PORT, threads=8)
    except ImportError:
        print("[launcher] waitress not installed, using Flask dev server")
        app.run(host=WEB_HOST, port=WEB_PORT)


if __name__ == "__main__":
    main()
