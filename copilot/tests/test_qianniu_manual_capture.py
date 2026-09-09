from copy import deepcopy

import pytest

from scripts.sidecar.uia_sidebar_extractor import build_native_preview


def node(depth, role, name="", automation_id="", selected=False):
    return {"depth": depth, "role": role, "name": name, "automation_id": automation_id, "selected": selected}


def capture():
    return [
        node(0, "Window"), node(1, "TabItem", "示例店:当前客服", selected=True),
        node(1, "TreeItem", "测试买家", selected=True), node(1, "Document"),
        node(2, "Group", automation_id="J_msgContainer"),
        node(3, "Heading"), node(4, "Text", "测试买家 --> 示例店:历史客服"),
        node(4, "Text", "2026-9-9 09:10:00"),
        node(3, "Group", "之前的尺寸呢？"), node(4, "Text", "之前的尺寸呢？"),
        node(3, "Group", "\ue123"), node(4, "Text", "\ue123"),
        node(3, "Heading"), node(4, "Text", "2026-9-9 09:10:01"),
        node(4, "Text", "示例店:另一位客服"), node(3, "Group", "请看图片"),
        node(3, "Image", "https://invalid.example/image"), node(3, "Group", "\ue123"),
        node(3, "Heading"), node(4, "Text", "测试买家 --> 示例店:当前客服"),
        node(4, "Text", "2026-9-9 09:10:02"), node(3, "Group", "之前的尺寸呢？"),
        node(1, "Document"), node(2, "Text", "客户订单"),
        node(2, "Text", "100000000000000001"), node(2, "Text", "100000000000000002"),
        node(2, "Text", "SKU："), node(2, "Text", "蓝色 / 两件"),
        node(2, "Text", "编号："), node(2, "Text", "TEST-CODE-1"),
    ]


def test_native_preview_keeps_roles_repetition_but_omits_unbound_orders():
    result = build_native_preview(capture(), capture(), 42)
    assert result["status"] == "preview_ready"
    assert result["diagnostics"]["turn_count"] == 3
    context = result["context"]
    assert context["customer_message"] == "之前的尺寸呢？"
    assert [t["role"] for t in context["conversation_history"]] == ["customer", "agent"]
    assert context["conversation_history"][0]["content"] == "之前的尺寸呢？"
    assert context["conversation_history"][1]["content"] == "请看图片 [IMAGE]"
    assert context["order_candidates"] == []
    assert context["product_candidates"] == []
    assert result["diagnostics"]["unbound_order_documents_omitted"] == 1
    assert "sku" not in context and "order_id" not in context
    assert context["can_send"] is False


@pytest.mark.parametrize("mutation,reason", [
    (lambda n: n.__setitem__(14, node(4, "Text", "其他店:客服")), "speaker_unresolved"),
    (lambda n: n.__setitem__(1, node(1, "TabItem", "其他店:客服")), "shop_binding_missing"),
    (lambda n: n.__setitem__(2, node(1, "TreeItem", "其他买家")), "buyer_binding_missing"),
    (lambda n: n.__setitem__(7, node(4, "Text", "bad time")), "header_structure_invalid"),
    (lambda n: n.__setitem__(20, node(4, "Text", "2026-9-9 08:00:00")), "timestamp_out_of_order"),
    (lambda n: n.__setitem__(4, node(2, "Group")), "conversation_document_missing"),
])
def test_native_preview_fail_closed(mutation, reason):
    nodes = capture()
    mutation(nodes)
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert result["ok"] is False
    assert result["error"] == reason
    assert "context" not in result


def test_read_binding_includes_sidebar_and_text_not_only_handle():
    changed = capture()
    changed[-1]["name"] = "OTHER-CODE"
    assert build_native_preview(capture(), changed, 42)["error"] == "capture_binding_changed"


def test_seller_tail_never_becomes_current_customer_question():
    nodes = capture()
    del nodes[18:22]
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert result["context"]["customer_message"] == ""
    assert len(result["context"]["conversation_history"]) == 2
    assert result["context"]["conversation_history"][-1]["content"] == "请看图片 [IMAGE]"


def test_second_conversation_document_is_ambiguous():
    nodes = capture() + capture()[3:21]
    assert build_native_preview(nodes, deepcopy(nodes), 42)["error"] == "conversation_document_ambiguous"


def test_platform_media_role_is_token_not_buyer_text_classifier():
    nodes = capture()
    nodes[8] = node(3, "Main", "图片消息")
    del nodes[9]
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert result["context"]["conversation_history"][0]["content"] == "[IMAGE]"
    nodes[8] = node(3, "Main", "unknown media")
    assert build_native_preview(nodes, deepcopy(nodes), 42)["error"] == "message_part_type_unknown"


def test_status_badges_after_action_toolbar_are_not_message_parts():
    nodes = capture()
    nodes.insert(12, node(3, "Image", "badge"))
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert result["context"]["conversation_history"][0]["content"] == "之前的尺寸呢？"


def test_unselected_buyer_exists_but_another_buyer_is_active():
    nodes = capture()
    nodes[2]["selected"] = False
    nodes.append(node(1, "TreeItem", "另一买家", selected=True))
    assert build_native_preview(nodes, deepcopy(nodes), 42)["error"] == "buyer_binding_missing"


def test_multiple_order_documents_cannot_merge_between_buyers():
    nodes = capture() + [node(1, "Document"), node(2, "Text", "客户订单"), node(2, "Text", "200000000000000001")]
    assert build_native_preview(nodes, deepcopy(nodes), 42)["error"] == "order_document_ambiguous"


def test_single_stale_order_panel_does_not_supply_current_customer_identity():
    nodes = capture()
    nodes[-6]["name"] = "200000000000000001"
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert result["ok"] is True
    assert result["context"]["order_candidates"] == []
    assert result["context"]["product_candidates"] == []


def test_unknown_content_subtree_fails_closed_and_mixed_icon_does_not_drop_text():
    nodes = capture()
    nodes.insert(10, node(3, "Custom", "body must survive"))
    assert build_native_preview(nodes, deepcopy(nodes), 42)["error"] == "message_part_type_unknown"
    nodes[10] = node(3, "Group", "正文\ue123")
    result = build_native_preview(nodes, deepcopy(nodes), 42)
    assert "正文" in result["context"]["conversation_history"][0]["content"]
