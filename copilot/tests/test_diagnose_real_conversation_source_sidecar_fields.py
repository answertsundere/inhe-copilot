import json

import openpyxl

from scripts.diagnose_real_conversation_source_sidecar_fields import diagnose_source_sidecar_fields


def test_source_sidecar_diagnostics_detects_explicit_xlsx_fields(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "chat.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "聊天记录"
    ws.append(["会话ID", "说话人类型", "消息内容", "商品标题", "商家编码", "订单号", "商品链接"])
    ws.append(["conv-1", "客户", "尺寸多少", "测试商品", "SKU-1", "ORDER-1", "https://item.example/1"])
    ws.append(["conv-1", "客服", "稍等", "", "", "", ""])
    wb.save(path)

    result = diagnose_source_sidecar_fields(source_dir=str(source))

    assert result["file_count"] == 1
    assert result["readable_file_count"] == 1
    assert result["product_title_field_found_count"] == 1
    assert result["sku_field_found_count"] == 1
    assert result["order_id_field_found_count"] == 1
    assert result["product_url_field_found_count"] == 1
    assert result["sidecar_complete_candidate_count"] == 1
    assert "商品标题" in result["detected_field_aliases"]["product_title"]
    assert result["sample_rows_with_sidecar"][0]["order_id_hash"]


def test_source_sidecar_diagnostics_keeps_product_url_supplemental(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "chat.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "聊天记录"
    ws.append(["会话ID", "说话人类型", "消息内容", "商品链接"])
    ws.append(["conv-1", "客户", "https://item.example/1", "https://item.example/1"])
    wb.save(path)

    result = diagnose_source_sidecar_fields(source_dir=str(source))

    assert result["product_url_field_found_count"] == 1
    assert result["sidecar_complete_candidate_count"] == 0
    assert result["sidecar_partial_candidate_count"] == 0
    assert result["sidecar_missing_candidate_count"] == 1
    assert result["sample_rows_with_sidecar"][0]["product_url_present"] is True


def test_source_sidecar_diagnostics_writes_json_only_when_requested(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "rows.json").write_text(
        json.dumps([{"product_title": "Product", "sku_code": "SKU-1"}]),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    result = diagnose_source_sidecar_fields(source_dir=str(source), json_output=str(output))

    assert output.exists()
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["sidecar_partial_candidate_count"] == 1
    assert result["sku_field_found_count"] == 1
