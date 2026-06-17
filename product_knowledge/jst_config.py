"""
聚水潭 (JuShuiTan) API 统一配置

所有凭证必须通过环境变量设置，不硬编码任何密钥。

环境变量:
    JUSHUITAN_APP_KEY       - 应用 Key (必需)
    JUSHUITAN_APP_SECRET    - 应用 Secret (必需)
    JUSHUITAN_ACCESS_TOKEN  - 访问令牌 (必需)
    JUSHUITAN_BASE_URL      - API 地址 (可选, 默认 https://openapi.jushuitan.com/open)
"""

import os
import sys


class JSTConfigError(Exception):
    """聚水潭配置缺失错误"""
    pass


def _load_env_file():
    """尝试加载 .env 文件"""
    try:
        from dotenv import load_dotenv
        # 尝试多个位置
        for env_path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "copilot", ".env"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        ]:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                return
    except ImportError:
        pass


def get_config(load_env: bool = True) -> dict:
    """
    获取聚水潭 API 配置。
    缺少必需变量时抛出 JSTConfigError，不会继续调用接口。

    参数:
        load_env: 是否尝试加载 .env 文件（测试中可传 False 隔离）

    返回 dict:
        app_key, app_secret, access_token, base_url
    """
    if load_env:
        _load_env_file()

    app_key = os.environ.get("JUSHUITAN_APP_KEY", "").strip()
    app_secret = os.environ.get("JUSHUITAN_APP_SECRET", "").strip()
    access_token = os.environ.get("JUSHUITAN_ACCESS_TOKEN", "").strip()
    base_url = os.environ.get(
        "JUSHUITAN_BASE_URL",
        "https://openapi.jushuitan.com/open",
    ).strip()

    missing = []
    if not app_key:
        missing.append("JUSHUITAN_APP_KEY")
    if not app_secret:
        missing.append("JUSHUITAN_APP_SECRET")
    if not access_token:
        missing.append("JUSHUITAN_ACCESS_TOKEN")

    if missing:
        raise JSTConfigError(
            f"缺少聚水潭 API 必需环境变量: {', '.join(missing)}\n"
            f"请在 .env 文件或环境变量中设置。参考 .env.example。"
        )

    return {
        "app_key": app_key,
        "app_secret": app_secret,
        "access_token": access_token,
        "base_url": base_url,
    }
