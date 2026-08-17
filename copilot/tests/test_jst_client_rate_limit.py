from unittest import mock

import pytest

from app.integrations.jst.client import JSTClient
from app.integrations.jst.errors import JSTAPIError


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _configured_client():
    client = JSTClient()
    client._app_key = "test-app"
    client._app_secret = "test-secret"
    client._access_token = "test-token"
    client._base_url = "https://provider.invalid/open"
    return client


@mock.patch("app.integrations.jst.client.time.sleep")
@mock.patch("app.integrations.jst.client.requests.post")
def test_rate_limit_is_retried_once_with_bounded_backoff(post, sleep):
    post.side_effect = [
        _Response({"code": 199, "msg": "rate limited"}),
        _Response({"code": 0, "data": {"datas": [{"o_id": "order-ref"}]}}),
    ]

    result = _configured_client().call("orders/out/simple/query", {"so_ids": ["order-ref"]})

    assert result["code"] == 0
    assert post.call_count == 2
    sleep.assert_called_once()
    assert 0 < sleep.call_args.args[0] <= 2


@mock.patch("app.integrations.jst.client.time.sleep")
@mock.patch("app.integrations.jst.client.requests.post")
def test_rate_limit_retry_is_not_unbounded(post, sleep):
    post.side_effect = [
        _Response({"code": 199, "msg": "rate limited"}),
        _Response({"code": 199, "msg": "rate limited again"}),
    ]

    with pytest.raises(JSTAPIError) as exc_info:
        _configured_client().call("orders/out/simple/query", {"so_ids": ["order-ref"]})

    assert exc_info.value.code == 199
    assert post.call_count == 2
    sleep.assert_called_once()


@mock.patch("app.integrations.jst.client.time.sleep")
@mock.patch("app.integrations.jst.client.requests.post")
def test_non_rate_limit_api_error_is_not_retried(post, sleep):
    post.return_value = _Response({"code": 190, "msg": "not authorized"})

    with pytest.raises(JSTAPIError) as exc_info:
        _configured_client().call("orders/out/simple/query", {"so_ids": ["order-ref"]})

    assert exc_info.value.code == 190
    assert post.call_count == 1
    sleep.assert_not_called()
