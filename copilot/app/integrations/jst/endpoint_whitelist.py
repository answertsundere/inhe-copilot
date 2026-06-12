"""聚水潭 API 白名单 — 只允许查询类 endpoint，严禁任何修改类接口"""

READONLY_ENDPOINTS = frozenset({
    "orders/single/query",
    "orders/out/simple/query",
    "logistic/query",
    "sku/query",
    "skumap/query",
    "mall/item/query",
    "shops/query",
    "logisticscompany/query",
    "inventory/query",
    "wms/partner/query",
    "category/query",
    "refund/single/query",
})

BLOCKED_KEYWORDS = frozenset({
    "upload", "update", "delete", "confirm", "cancel",
    "ship", "refund", "create", "modify", "batch",
    "out", "in", "audit", "reject", "approve",
})


def is_endpoint_allowed(endpoint: str) -> bool:
    if endpoint in READONLY_ENDPOINTS:
        return True
    parts = endpoint.lower().split("/")
    return not any(kw in parts for kw in BLOCKED_KEYWORDS)


def validate_endpoint(endpoint: str) -> None:
    from app.integrations.jst.errors import JSTEndpointBlockedError
    if not is_endpoint_allowed(endpoint):
        raise JSTEndpointBlockedError(f"endpoint '{endpoint}' 不在白名单中，严禁调用")
