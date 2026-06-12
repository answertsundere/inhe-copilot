"""
[已废弃] 旧命令行入口 - 仅为参考保留。

请使用新入口:
    python run_cli.py

新架构说明:
    - 配置: app/config.py
    - 服务: app/services/*.py
    - LLM:  app/llm/client.py
"""

import warnings

warnings.warn(
    "main.py (旧) 已废弃，请使用 run_cli.py 启动命令行。",
    DeprecationWarning,
    stacklevel=2,
)

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 迁移：直接调用新入口
if __name__ == "__main__":
    print("[注意] 此入口已废弃，推荐使用: python run_cli.py")
    # 代理到新入口
    from run_cli import main as cli_main
    cli_main()
