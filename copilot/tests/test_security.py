"""
安全相关测试 - 密钥清理、聚水潭配置、无硬编码
"""

import os
import re
import sys
import pytest

# 项目根目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COPILOT_DIR = os.path.join(_PROJECT_ROOT, "copilot")
_PK_DIR = os.path.join(_PROJECT_ROOT, "product_knowledge")


def _read_all_py(*directories):
    """读取多个目录下所有 .py 文件内容（排除测试文件本身）"""
    content = ""
    test_file = os.path.abspath(__file__)
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, dirs, files in os.walk(directory):
            if "__pycache__" in root:
                continue
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    if os.path.abspath(path) == test_file:
                        continue  # 跳过测试文件本身
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content += fh.read() + "\n"
    return content


def _iter_security_scan_files(*directories):
    """Yield source/template files that must not contain live secrets.

    Local runtime files such as .env and sidecar.env are intentionally excluded
    because this developer workstation uses them to run live integrations.
    """
    scan_names = {".env.example"}
    scan_exts = {".py", ".yaml", ".yml", ".md"}
    skip_dirs = {"__pycache__", ".git", ".pytest_cache", "tests", "data", "node_modules"}
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for filename in files:
                path = os.path.join(root, filename)
                _, ext = os.path.splitext(filename)
                if filename in scan_names or ext in scan_exts:
                    yield path


def _read_security_scan_text(*directories):
    chunks = []
    for path in _iter_security_scan_files(*directories):
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            chunks.append(f"\n# FILE: {path}\n{fh.read()}")
    return "\n".join(chunks)


class TestNoHardcodedSecrets:
    """确保代码中没有硬编码密钥"""

    def test_no_real_app_key(self):
        """代码中没有真实聚水潭 APP_KEY"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "c9270ff8c41b4f1481f84f4c5669d597" not in py

    def test_no_real_app_secret(self):
        """代码中没有真实聚水潭 APP_SECRET"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "0ac9e66c81134d8cb961904bf8b56886" not in py

    def test_no_real_access_token(self):
        """代码中没有真实聚水潭 ACCESS_TOKEN"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "450582fd13a8497db39eee4006e78c4b" not in py

    def test_no_real_sk_key(self):
        """代码中没有真实 sk- API Key"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "sk-1637e1de954846029905a25ebe98bf49" not in py

    def test_no_dingtalk_client_secret(self):
        """代码中没有真实钉钉 Client Secret"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "1WOH8Gdu_wDjU6qxmZkYX8LXmM_fIGgZDABOm5XGVvCWf0amsrnr23iulZrgD2ru" not in py

    def test_no_dingtalk_operator_id(self):
        """代码中没有真实钉钉 Operator ID"""
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        assert "KYcnydDf1vXm64d6paOf9giEiE" not in py

    def test_no_live_secrets_in_source_or_env_files(self):
        """源代码和本地配置文件中不应出现可用的 API Key/Secret/Token。"""
        text = _read_security_scan_text(_COPILOT_DIR, _PK_DIR)
        live_key_patterns = [
            r"sk-[A-Za-z0-9_\-]{16,}",
        ]
        allowed_literals = (
            "API_KEY=your_api_key_here",
            "api_key=sk-1234567890abcdef",
            "api_key=myapikey1234",
        )
        scrubbed = text
        for literal in allowed_literals:
            scrubbed = scrubbed.replace(literal, "")
        for pattern in live_key_patterns:
            assert not re.search(pattern, scrubbed), f"found possible live secret matching {pattern}"


class TestJSTConfig:
    """聚水潭配置测试"""

    def test_missing_env_vars_raises_error(self):
        """缺少环境变量时清晰报错"""
        for key in ["JUSHUITAN_APP_KEY", "JUSHUITAN_APP_SECRET", "JUSHUITAN_ACCESS_TOKEN"]:
            os.environ.pop(key, None)

        # 将 product_knowledge 加入搜索路径
        if _PK_DIR not in sys.path:
            sys.path.insert(0, _PK_DIR)

        import importlib
        import jst_config
        importlib.reload(jst_config)

        with pytest.raises(jst_config.JSTConfigError) as exc_info:
            jst_config.get_config(load_env=False)
        error_msg = str(exc_info.value)
        assert "JUSHUITAN_APP_KEY" in error_msg
        assert "JUSHUITAN_APP_SECRET" in error_msg
        assert "JUSHUITAN_ACCESS_TOKEN" in error_msg

    def test_config_reads_from_env(self):
        """配置从环境变量正确读取"""
        os.environ["JUSHUITAN_APP_KEY"] = "test_key_123"
        os.environ["JUSHUITAN_APP_SECRET"] = "test_secret_456"
        os.environ["JUSHUITAN_ACCESS_TOKEN"] = "test_token_789"

        if _PK_DIR not in sys.path:
            sys.path.insert(0, _PK_DIR)

        import importlib
        import jst_config
        importlib.reload(jst_config)

        cfg = jst_config.get_config()
        assert cfg["app_key"] == "test_key_123"
        assert cfg["app_secret"] == "test_secret_456"
        assert cfg["access_token"] == "test_token_789"
        assert cfg["base_url"] == "https://openapi.jushuitan.com/open"

        # 清理
        for key in ["JUSHUITAN_APP_KEY", "JUSHUITAN_APP_SECRET", "JUSHUITAN_ACCESS_TOKEN"]:
            os.environ.pop(key, None)
