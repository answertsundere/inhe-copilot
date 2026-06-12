"""
INHE 客服 Copilot - Web 服务启动入口

用法:
    python run_web.py

环境变量:
    COPILOT_LLM_API_KEY   - LLM API Key (必需)
    COPILOT_LLM_API_BASE  - LLM API 地址 (默认: 通义千问)
    COPILOT_LLM_MODEL     - 模型名称 (默认: qwen-plus)
"""

import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass  # 没有 python-dotenv 也可以运行

from app.config import WEB_HOST, WEB_PORT, WEB_DEBUG, LLM_API_KEY
from app.logging_config import setup_logging


def main():
    setup_logging()

    # Port conflict detection
    import socket
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1)
        result = test_sock.connect_ex((WEB_HOST, WEB_PORT))
        test_sock.close()
        if result == 0:
            print(f"\n[错误] 端口 {WEB_PORT} 已被占用！")
            print(f"  可能已有 Copilot 进程在运行。")
            print(f"  请先停止旧进程（检查 PID）或使用其他端口。")
            print(f"  设置环境变量 COPILOT_WEB_PORT 可更改端口。\n")
            import sys
            sys.exit(1)
    except Exception:
        pass

    print("=" * 50)
    print("  INHE 客服 Copilot")
    print("  AI 客服建议生成器")
    print("=" * 50)

    if not LLM_API_KEY:
        print("\n[警告] 未配置 COPILOT_LLM_API_KEY")
        print("  AI 建议功能不可用，但查询功能仍可使用")
        print("  请设置环境变量或创建 .env 文件\n")

    from app.main import create_app
    from sqlalchemy import inspect as sa_inspect
    from app.models.kb_tables import KBQA, KBReviewTask
    # Force mapper initialization before Flask forks
    try:
        list(sa_inspect(KBQA).relationships.keys())
        list(sa_inspect(KBReviewTask).relationships.keys())
    except Exception:
        pass

    app = create_app()

    print(f"\n启动 Web 服务: http://{WEB_HOST}:{WEB_PORT}")
    print("按 Ctrl+C 停止\n")

    app.run(host=WEB_HOST, port=WEB_PORT, debug=WEB_DEBUG)


if __name__ == "__main__":
    main()
