from __future__ import annotations

from scripts.sidecar.uia_sidebar_extractor import (
    CandidateItem,
    UIASidebarResult,
    _extract_tracking_candidates,
    _extract_order_candidates,
    _extract_product_candidates,
    extract_sidebar,
)


class TestExtractTrackingCandidates:
    def test_sf_tracking_number(self):
        text = "顺丰速运,SF5196840812297"
        lines = [text]
        result = _extract_tracking_candidates(text, lines)
        assert len(result) >= 1
        assert result[0].value == "SF5196840812297"
        assert result[0].source == "uia_sidebar"
        assert result[0].confidence == 0.99
        assert result[0].type == "tracking_no_candidate"

    def test_sf_with_carrier(self):
        text = "顺丰速运,SF5196840812297"
        lines = [text]
        result = _extract_tracking_candidates(text, lines)
        assert any(c.carrier == "顺丰速运" for c in result)

    def test_yto_tracking(self):
        text = "YT1234567890123"
        lines = [text]
        result = _extract_tracking_candidates(text, lines)
        assert any(c.value == "YT1234567890123" for c in result)

    def test_no_duplicates(self):
        text = "顺丰速运,SF5196840812297 SF5196840812297"
        lines = [text]
        result = _extract_tracking_candidates(text, lines)
        values = [c.value for c in result]
        assert values.count("SF5196840812297") == 1


class TestExtractOrderCandidates:
    def test_18digit_order(self):
        text = "5116887975001001001"
        result = _extract_order_candidates(text)
        assert len(result) >= 1
        assert result[0].value == "5116887975001001001"
        assert result[0].type == "platform_trade_id_candidate"
        assert result[0].source == "uia_sidebar"

    def test_no_order_short_number(self):
        text = "12345"
        result = _extract_order_candidates(text)
        assert len(result) == 0


class TestExtractProductCandidates:
    def test_product_from_consult_line(self):
        text = "咨询宝贝 INHE智能感应垃圾桶"
        result = _extract_product_candidates(text)
        assert len(result) >= 1
        assert result[0].source == "uia_sidebar"

    def test_no_product_without_keyword(self):
        text = "普通文本内容"
        result = _extract_product_candidates(text)
        assert len(result) == 0


class TestUIASidebarResult:
    def test_to_dict(self):
        result = UIASidebarResult(
            success=True,
            controls_count=235,
            text_count=205,
            tracking_candidates=[
                CandidateItem(
                    value="SF5196840812297",
                    type="tracking_no_candidate",
                    source="uia_sidebar",
                    confidence=0.99,
                    carrier="顺丰速运",
                )
            ],
        )
        d = result.to_dict()
        assert d["extract_method"] == "uia_sidebar"
        assert d["success"] is True
        assert len(d["tracking_candidates"]) == 1
        assert d["tracking_candidates"][0]["carrier"] == "顺丰速运"

    def test_extract_sidebar_none_window(self):
        result = extract_sidebar(None)
        assert result.success is False
        assert "window is None" in result.warnings

    def test_uia_does_not_produce_customer_message(self):
        result = UIASidebarResult(success=True)
        d = result.to_dict()
        assert "customer_message" not in d
        assert "chat_text" not in d


class TestSystemTextNotCustomerMessage:
    def test_system_prompt_not_extracted_as_tracking(self):
        text = "1天内暂无导入或导出的文件"
        result = _extract_tracking_candidates(text, [text])
        assert all(c.value != "1天内暂无导入或导出的文件" for c in result)

    def test_system_labels_not_extracted(self):
        text = "咨询宝贝\n发送宝贝\n模块可以手动展开收起"
        orders = _extract_order_candidates(text)
        for order in orders:
            assert order.value not in ("咨询宝贝", "发送宝贝")
