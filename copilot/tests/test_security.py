import hashlib
import os
import re
import sys

import pytest


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COPILOT_DIR = os.path.join(_PROJECT_ROOT, "copilot")
_PK_DIR = os.path.join(_PROJECT_ROOT, "product_knowledge")
_LIVE_SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{16,}")


def _read_all_py(*directories):
    content = ""
    test_file = os.path.abspath(__file__)
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for root, dirs, files in os.walk(directory):
            if "__pycache__" in root:
                continue
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                if os.path.abspath(path) == test_file:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    content += fh.read() + "\n"
    return content


def _iter_security_scan_files(*directories):
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


def _assert_forbidden_token_digest_absent(text: str, forbidden_sha256: str):
    candidates = re.findall(r"[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9_\-]{12,}", text or "")
    digests = {hashlib.sha256(item.encode("utf-8")).hexdigest() for item in candidates}
    assert forbidden_sha256 not in digests


class TestNoHardcodedSecrets:
    def test_no_real_app_key(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "e510269fb74a3b5e32cf02e21b40eb50bf5d6acb19c5c695e9bad9205923fd91")

    def test_no_real_app_secret(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "c92e967085df9e3858ba5a019871543a463b1516ebf06ae2ee5a052280558c58")

    def test_no_real_access_token(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "511647f28da5aeef46dca2487277d70ed6bb9ebf3373bfc04ea56dd00bbb2108")

    def test_no_real_sk_key(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "80e4baec2f954818ac318e0c947da79f2cb412205af46ab21b4a3e8d410e8f16")

    def test_no_dingtalk_client_secret(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "0fa29ae08b6c637c75326fc67b93e48b0e5b42b56c4fa161546c7de664913f63")

    def test_no_dingtalk_operator_id(self):
        py = _read_all_py(_COPILOT_DIR, _PK_DIR)
        _assert_forbidden_token_digest_absent(py, "ef773141c03533725803ebcbf5830024efb0aaf9067e73e8d2e27e5cfc40d234")

    def test_no_live_secrets_in_source_or_env_files(self):
        text = _read_security_scan_text(_COPILOT_DIR, _PK_DIR)
        allowed_literals = (
            "API_KEY=your_api_key_here",
            "api_key=sk-1234567890abcdef",
            "api_key=myapikey1234",
            "sk-1234567890abcdef",
            "COPILOT_LLM_API_KEY=sk-xxx",
        )
        scrubbed = text
        for literal in allowed_literals:
            scrubbed = scrubbed.replace(literal, "")
        assert not _LIVE_SK_KEY_RE.search(scrubbed)

    def test_live_key_scan_requires_a_token_boundary(self):
        assert not _LIVE_SK_KEY_RE.search("risk-tier-fast-path-qualification")
        assert _LIVE_SK_KEY_RE.search("COPILOT_LLM_API_KEY=sk-abcdefghijklmnop")


class TestJSTConfig:
    def test_missing_env_vars_raises_error(self):
        for key in ["JUSHUITAN_APP_KEY", "JUSHUITAN_APP_SECRET", "JUSHUITAN_ACCESS_TOKEN"]:
            os.environ.pop(key, None)

        sys.path.insert(0, _PROJECT_ROOT)
        try:
            from product_knowledge.jst_config import JSTConfigError, get_config

            with pytest.raises(JSTConfigError) as exc_info:
                get_config(load_env=False)
            assert "JUSHUITAN_APP_KEY" in str(exc_info.value)
        finally:
            if _PROJECT_ROOT in sys.path:
                sys.path.remove(_PROJECT_ROOT)

    def test_config_uses_env_vars(self):
        os.environ["JUSHUITAN_APP_KEY"] = "test_key"
        os.environ["JUSHUITAN_APP_SECRET"] = "test_secret"
        os.environ["JUSHUITAN_ACCESS_TOKEN"] = "test_token"

        sys.path.insert(0, _PROJECT_ROOT)
        try:
            from product_knowledge.jst_config import get_config

            config = get_config(load_env=False)
            assert config["app_key"] == "test_key"
            assert config["app_secret"] == "test_secret"
            assert config["access_token"] == "test_token"
        finally:
            for key in ["JUSHUITAN_APP_KEY", "JUSHUITAN_APP_SECRET", "JUSHUITAN_ACCESS_TOKEN"]:
                os.environ.pop(key, None)
            if _PROJECT_ROOT in sys.path:
                sys.path.remove(_PROJECT_ROOT)
