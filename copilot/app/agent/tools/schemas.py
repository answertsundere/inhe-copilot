"""
工具输入/输出 schema 定义

每个工具声明 input_schema 和 output_schema 为纯 dict（JSON Schema 子集）。
不做运行时校验，只做声明和文档用途。
"""


def make_input_schema(**fields):
    """快速构造 input_schema dict。
    fields: name -> {"type": str, "required": bool, "description": str}
    """
    properties = {}
    required = []
    for name, spec in fields.items():
        properties[name] = {
            "type": spec.get("type", "string"),
            "description": spec.get("description", ""),
        }
        if spec.get("required", False):
            required.append(name)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# ========== JST 订单查询 ==========
JST_ORDER_INPUT = make_input_schema(
    identifier={"type": "string", "required": True, "description": "订单号或平台订单号"},
    identifier_type={"type": "string", "required": False, "description": "internal_order_id / platform_order_id"},
    shop_id={"type": "string", "required": False, "description": "侧边栏提供的聚水潭店铺编号，仅用于查询范围"},
    shop_name={"type": "string", "required": False, "description": "侧边栏提供的店铺显示名，仅用于精确解析查询范围"},
)
JST_ORDER_OUTPUT = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "o_id": {"type": "string"},
        "so_id": {"type": "string"},
        "outer_so_id": {"type": "string"},
        "status": {"type": "string"},
        "logistics_company": {"type": "string"},
        "l_id": {"type": "string"},
        "send_date": {"type": "string"},
        "sign_time": {"type": "string"},
        "endpoint": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "error_code": {"type": "string"},
        "safe_fallback_reason": {"type": "string"},
    },
}

# ========== JST 销售出库查询 ==========
JST_OUTBOUND_INPUT = make_input_schema(
    outer_so_id={"type": "string", "required": True, "description": "外部交易单号 / 平台交易号"},
    shop_id={"type": "string", "required": False, "description": "侧边栏提供的聚水潭店铺编号，仅用于查询范围"},
    shop_name={"type": "string", "required": False, "description": "侧边栏提供的店铺显示名，仅用于精确解析查询范围"},
)
JST_OUTBOUND_OUTPUT = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "o_id": {"type": "string"},
        "status": {"type": "string"},
        "logistics_company": {"type": "string"},
        "l_id": {"type": "string"},
        "send_date": {"type": "string"},
        "sign_time": {"type": "string"},
        "endpoint": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "error_code": {"type": "string"},
        "safe_fallback_reason": {"type": "string"},
    },
}

# ========== JST 快递单号查询 ==========
JST_TRACKING_INPUT = make_input_schema(
    tracking_no={"type": "string", "required": True, "description": "快递单号"},
)
JST_TRACKING_OUTPUT = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "o_id": {"type": "string"},
        "logistics_company": {"type": "string"},
        "l_id": {"type": "string"},
        "send_date": {"type": "string"},
        "endpoint": {"type": "string"},
        "duration_ms": {"type": "integer"},
        "error_code": {"type": "string"},
        "safe_fallback_reason": {"type": "string"},
    },
}

# ========== RAG 搜索 ==========
RAG_SEARCH_INPUT = make_input_schema(
    query={"type": "string", "required": True, "description": "检索文本"},
    source_types={"type": "array", "required": False, "description": "允许的 source_type 列表"},
    intent={"type": "string", "required": False, "description": "意图标签"},
    product_scope={"type": "array", "required": False, "description": "商品范围"},
)
RAG_SEARCH_OUTPUT = {
    "type": "object",
    "properties": {
        "chunks": {"type": "array", "description": "检索到的知识分片"},
        "count": {"type": "integer"},
    },
}

# ========== 商品识别 ==========
PRODUCT_RESOLVER_INPUT = make_input_schema(
    message={"type": "string", "required": True, "description": "客户消息"},
)
PRODUCT_RESOLVER_OUTPUT = {
    "type": "object",
    "properties": {
        "matched_product_name": {"type": "string"},
        "candidates": {"type": "array"},
        "need_clarification": {"type": "boolean"},
    },
}

# ========== SOP 查询 ==========
SOP_LOOKUP_INPUT = make_input_schema(
    message={"type": "string", "required": True, "description": "客户消息"},
    intent={"type": "string", "required": False, "description": "意图标签"},
)
SOP_LOOKUP_OUTPUT = {
    "type": "object",
    "properties": {
        "sops": {"type": "array"},
        "forbidden_claims": {"type": "array"},
    },
}

# ========== 模板选择 ==========
TEMPLATE_SELECT_INPUT = make_input_schema(
    message={"type": "string", "required": True, "description": "客户消息"},
    intent={"type": "string", "required": False, "description": "意图标签"},
)
TEMPLATE_SELECT_OUTPUT = {
    "type": "object",
    "properties": {
        "templates": {"type": "array"},
    },
}
