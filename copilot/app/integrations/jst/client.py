"""
聚水潭 API 客户端 — 仅查询，带签名、超时、白名单校验
"""

import hashlib
import json
import logging
import os
import time

import requests

from app.integrations.jst.endpoint_whitelist import validate_endpoint
from app.integrations.jst.errors import JSTAPIError, JSTConfigError, JSTTimeoutError

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 2.5


class JSTClient:
    """聚水潭只读 API 客户端"""

    def __init__(self):
        self._app_key = os.environ.get("JUSHUITAN_APP_KEY", "")
        self._app_secret = os.environ.get("JUSHUITAN_APP_SECRET", "")
        self._access_token = os.environ.get("JUSHUITAN_ACCESS_TOKEN", "")
        self._base_url = os.environ.get(
            "JUSHUITAN_BASE_URL", "https://openapi.jushuitan.com/open"
        )

    def is_configured(self) -> bool:
        return bool(self._app_key and self._app_secret and self._access_token)

    def _sign(self, params: dict) -> str:
        sorted_params = sorted(params.items())
        sign_str = self._app_secret + "".join(f"{k}{v}" for k, v in sorted_params)
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    def call(self, endpoint: str, biz: dict = None, timeout: float = _DEFAULT_TIMEOUT) -> dict:
        """调用聚水潭 API（仅白名单 endpoint）"""
        validate_endpoint(endpoint)

        if not self.is_configured():
            raise JSTConfigError("聚水潭 API 凭证未配置")

        ts = str(int(time.time()))
        biz_str = json.dumps(biz or {}, separators=(",", ":"), ensure_ascii=False)
        params = {
            "access_token": self._access_token,
            "app_key": self._app_key,
            "biz": biz_str,
            "charset": "utf-8",
            "timestamp": ts,
            "version": "2",
        }
        params["sign"] = self._sign(params)

        try:
            resp = requests.post(
                f"{self._base_url}/{endpoint}",
                data=params,
                timeout=timeout,
            )
            result = resp.json()
        except requests.Timeout:
            raise JSTTimeoutError(f"聚水潭 API 超时 ({timeout}s): {endpoint}")
        except requests.RequestException as e:
            raise JSTTimeoutError(f"聚水潭请求失败: {e}")

        code = result.get("code", -1)
        if code != 0:
            raise JSTAPIError(
                code=code,
                message=result.get("msg", ""),
                endpoint=endpoint,
            )

        return result
