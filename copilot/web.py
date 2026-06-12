"""
[已废弃] 旧 Web 入口 - 仅为参考保留。

请使用新入口:
    python run_web.py

新架构说明:
    - 配置: app/config.py
    - 路由: app/api/*.py
    - 服务: app/services/*.py
    - 模板: web/templates/index.html
"""

import warnings

warnings.warn(
    "web.py (旧) 已废弃，请使用 run_web.py 启动 Web 服务。",
    DeprecationWarning,
    stacklevel=2,
)

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 迁移：直接启动新架构
from app.main import create_app
from app.config import WEB_HOST, WEB_PORT

app = create_app()

if __name__ == "__main__":
    print("[注意] 此入口已废弃，推荐使用: python run_web.py")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
