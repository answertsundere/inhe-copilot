#!/usr/bin/env python3
"""Production launcher using Waitress WSGI server."""
import os
import sys
import shutil
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env file
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

# Clear bytecode cache before importing
_project = os.path.dirname(os.path.abspath(__file__))
for _root, _dirs, _files in os.walk(_project):
    if "__pycache__" in _dirs:
        shutil.rmtree(os.path.join(_root, "__pycache__"), ignore_errors=True)
for _pyc in glob.glob(os.path.join(_project, "**", "*.pyc"), recursive=True):
    try:
        os.remove(_pyc)
    except OSError:
        pass
for _mod in list(sys.modules.keys()):
    if _mod.startswith("app"):
        del sys.modules[_mod]

from app.main import create_app
from app.config import WEB_HOST, WEB_PORT


class StripPathPrefix:
    """WSGI middleware: strips /ask prefix so Flask receives clean paths."""

    def __init__(self, app, prefix="/ask"):
        self.app = app
        self.prefix = prefix
        self.prefix_len = len(prefix)

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith(self.prefix + "/"):
            environ["PATH_INFO"] = path[self.prefix_len:]
        elif path == self.prefix:
            environ["PATH_INFO"] = "/"
        return self.app(environ, start_response)


def main():
    try:
        from sqlalchemy import inspect as sa_inspect
        from app.models.kb_tables import KBQA, KBReviewTask
        list(sa_inspect(KBQA).relationships.keys())
        list(sa_inspect(KBReviewTask).relationships.keys())
    except Exception:
        pass

    app = create_app()
    wrapped = StripPathPrefix(app, "/ask")

    print(f"Starting production server on {WEB_HOST}:{WEB_PORT}")
    print(f"Access: https://www.inhe.ccwu.cc/ask/real-test")
    print(f"  or:   https://www.inhe.ccwu.cc/ask/training-samples")
    print(f"  or:   https://www.inhe.ccwu.cc/ask/kb-admin/")
    try:
        from waitress import serve
        serve(wrapped, host=WEB_HOST, port=WEB_PORT, threads=8)
    except ImportError:
        print("waitress not installed, falling back to Flask dev server")
        app.run(host=WEB_HOST, port=WEB_PORT)


if __name__ == "__main__":
    main()
