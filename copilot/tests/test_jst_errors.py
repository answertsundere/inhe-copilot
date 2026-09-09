from app.integrations.jst.errors import JSTAPIError


def test_code_110_is_an_ip_allowlist_block_not_a_credential_failure():
    error = JSTAPIError(code=110, message="redacted", endpoint="shops/query")

    assert error.is_ip_allowlist_error is True
    assert error.is_auth_error is False
    assert error.classify() == "聚水潭出口 IP 未在白名单中"
