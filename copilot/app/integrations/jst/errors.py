"""聚水潭 API 错误分类"""

import logging

logger = logging.getLogger(__name__)


class JSTError(Exception):
    """聚水潭查询基础异常"""


class JSTConfigError(JSTError):
    """凭证缺失"""


class JSTTimeoutError(JSTError):
    """API 超时"""


class JSTAPIError(JSTError):
    """API 返回非 0 code"""

    # Known error code meanings for classification
    _AUTH_ERROR_CODES = {110, 111, 112, 113}
    _RATE_LIMIT_CODES = {100, 101}

    def __init__(self, code, message="", endpoint=""):
        self.code = code
        self.api_message = message
        self.endpoint = endpoint
        super().__init__(f"JST API error: code={code}, msg={message}, endpoint={endpoint}")

    @property
    def is_auth_error(self) -> bool:
        """Check if this is an authentication/authorization error."""
        try:
            return int(self.code) in self._AUTH_ERROR_CODES
        except (ValueError, TypeError):
            return False

    @property
    def is_rate_limit(self) -> bool:
        """Check if this is a rate limiting error."""
        try:
            return int(self.code) in self._RATE_LIMIT_CODES
        except (ValueError, TypeError):
            return False

    def classify(self) -> str:
        """Return a human-readable error classification."""
        if self.is_auth_error:
            return "认证失败：access_token 可能已过期或无效，请检查环境变量 JUSHUITAN_ACCESS_TOKEN"
        if self.is_rate_limit:
            return "请求频率超限，请稍后重试"
        return f"API 返回错误码 {self.code}: {self.api_message}"


class JSTEndpointBlockedError(JSTError):
    """非白名单 endpoint"""
