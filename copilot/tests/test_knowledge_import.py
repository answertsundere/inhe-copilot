"""
测试 Excel/CSV 导入：预览、字段映射、去重、默认 draft、高风险强制审核
"""

import os
import tempfile
import uuid
import csv
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_knowledge_import_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.services.knowledge_import_service import KnowledgeImportService, _resolve_source_type, _bool_from_cell, _risk_from_cell, _build_preview_item
from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository


class TestSheetMapping:
    """Sheet → source_type 映射"""

    def test_exact_match(self):
        assert _resolve_source_type("金牌客服问答（增强版）") == "faq"
        assert _resolve_source_type("物流发货常见问答（增强版）") == "shipping_policy"
        assert _resolve_source_type("高风险SOP手册") == "high_risk_sop"

    def test_fuzzy_match(self):
        assert _resolve_source_type("物流发货问答") == "shipping_policy"
        assert _resolve_source_type("客诉处理手册") == "high_risk_sop"
        assert _resolve_source_type("平台规则速查表") == "forbidden_rules"

    def test_no_match(self):
        assert _resolve_source_type("未知Sheet") == ""


class TestFieldHelpers:
    """字段解析辅助函数"""

    def test_bool_from_cell(self):
        assert _bool_from_cell("是") is True
        assert _bool_from_cell("否") is False
        assert _bool_from_cell("yes") is True
        assert _bool_from_cell(None) is False
        assert _bool_from_cell("") is False
        assert _bool_from_cell(True) is True

    def test_risk_from_cell(self):
        assert _risk_from_cell("高", "faq") == "high"
        assert _risk_from_cell("中", "faq") == "medium"
        assert _risk_from_cell("低", "faq") == "low"
        assert _risk_from_cell(None, "faq") == "low"
        # 高风险 source_type 强制 high
        assert _risk_from_cell("低", "high_risk_sop") == "high"


class TestBuildPreviewItem:
    """预览项构建"""

    def test_faq_fields(self):
        raw = {"客户问题": "书架是什么材质？", "金牌回答": "实木材质", "意图": "product_question", "风险等级": "低", "可自动回复": "是", "需人工审核": "否"}
        item, err = _build_preview_item(raw, 2, "金牌客服问答", "faq", "batch_001")
        assert item["title"] == "书架是什么材质？"
        assert item["content"] == "实木材质"
        assert item["intent"] == "product_question"
        assert item["risk_level"] == "low"
        assert item["auto_reply_allowed"] is True
        assert item["human_review_required"] is False
        assert item["source_sheet"] == "金牌客服问答"
        assert item["row_number"] == 2
        assert item["content_hash"]
        assert not item["errors"]

    def test_sop_fields(self):
        raw = {"SOP编号": "SOP-01", "场景描述": "客诉处理", "步骤1：第一时间响应": "安抚客户", "步骤2：信息收集": "记录问题", "风险等级": "中"}
        item, err = _build_preview_item(raw, 3, "高风险SOP手册", "high_risk_sop", "batch_002")
        assert item["title"] == "客诉处理"
        assert "安抚客户" in item["content"]
        assert item["risk_level"] == "high"  # 强制 high
        assert item["auto_reply_allowed"] is False  # 强制
        assert item["human_review_required"] is True  # 强制
        assert not item["errors"]

    def test_product_overview_fields(self):
        raw = {"商品名称": "三层火箭书架", "材质": "E1级板材", "尺寸": "60x30x90cm", "风险等级": "低"}
        item, err = _build_preview_item(raw, 2, "商品总览", "product_facts", "batch_003")
        assert item["title"] == "三层火箭书架"
        assert "E1级板材" in item["content"]
        assert not item["errors"]

    def test_missing_title(self):
        raw = {"金牌回答": "只有答案没有问题"}
        item, err = _build_preview_item(raw, 2, "FAQ", "faq", "batch_004")
        assert any("缺少标题" in e for e in item["errors"])

    def test_missing_content(self):
        raw = {"客户问题": "只有问题没有答案"}
        item, err = _build_preview_item(raw, 2, "FAQ", "faq", "batch_005")
        assert any("缺少内容" in e for e in item["errors"])


class TestImportPreview:
    """导入预览端到端"""

    def _create_csv(self, rows: list) -> str:
        """创建临时 CSV 文件"""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            for r in rows:
                writer.writerow(r)
        return path

    def test_csv_preview_items_gt_0(self):
        path = self._create_csv([
            ["客户问题", "金牌回答", "意图", "风险等级"],
            ["多久发货？", "48小时内", "物流发货", "低"],
            ["", "", "", ""],  # 空行，应跳过
            ["能退货吗？", "7天无理由", "售后", "中"],
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="faq")
        os.unlink(path)
        assert result["total_rows"] == 3
        assert result["valid_count"] == 2
        assert result["failed_count"] == 0
        assert len(result["preview_items"]) == 2
        assert result["preview_items"][0]["title"] == "多久发货？"
        assert result["preview_items"][1]["title"] == "能退货吗？"
        assert result["batch_id"].startswith("import_")

    def test_csv_empty_skipped(self):
        path = self._create_csv([
            ["客户问题", "金牌回答"],
            ["", ""],
            ["问题A", "答案A"],
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="faq")
        os.unlink(path)
        assert result["valid_count"] == 1
        assert result["preview_items"][0]["title"] == "问题A"

    def test_csv_missing_fields_return_errors(self):
        path = self._create_csv([
            ["客户问题", "金牌回答"],
            ["只有问题", ""],
            ["", "只有答案"],
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="faq")
        os.unlink(path)
        assert result["failed_count"] == 2
        assert result["valid_count"] == 0
        # errors 列表中应有错误描述
        assert len(result["errors"]) > 0 or any(item.get("errors") for item in result["preview_items"])

    def test_high_risk_sheet_auto_human_review(self):
        path = self._create_csv([
            ["场景描述", "标准回复模板", "风险等级"],
            ["客诉处理", "安抚客户", "中"],
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="high_risk_sop")
        os.unlink(path)
        item = result["preview_items"][0]
        assert item["risk_level"] == "high"
        assert item["auto_reply_allowed"] is False
        assert item["human_review_required"] is True
        assert "高风险" in item["warnings"][0]


class TestImportExecute:
    """执行导入"""

    def test_import_draft_status(self):
        preview = [
            {
                "row_number": 2, "source_sheet": "FAQ", "source_type": "faq",
                "title": "测试问题", "content": "测试回答", "content_preview": "测试回答",
                "intent": "product_question", "risk_level": "low",
                "auto_reply_allowed": True, "human_review_required": False,
                "warnings": [], "errors": [], "duplicate_candidate": False,
                "content_hash": "abc123", "import_batch_id": "batch_001",
            }
        ]
        result = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="batch_001")
        assert result["success"] == 1
        assert result["failed"] == 0
        entry = KnowledgeEntryRepository.get_by_id(result["created_ids"][0])
        assert entry.status == "draft"
        assert entry.import_batch_id == "batch_001"
        assert entry.source_sheet == "FAQ"
        assert entry.row_number == 2

    def test_duplicate_skipped_by_default(self):
        preview = [
            {
                "row_number": 2, "source_sheet": "FAQ", "source_type": "faq",
                "title": "重复问题", "content": "重复回答", "content_preview": "重复回答",
                "intent": "general", "risk_level": "low",
                "auto_reply_allowed": True, "human_review_required": False,
                "warnings": [], "errors": [], "duplicate_candidate": False,
                "content_hash": "dup_hash_001", "import_batch_id": "batch_002",
            }
        ]
        r1 = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="b1")
        assert r1["success"] == 1

        # 第二次导入相同内容（content_hash 会触发去重）
        r2 = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="b2")
        assert r2["success"] == 0
        assert r2["failed"] == 1
        assert "重复" in r2["errors"][0]["reason"]

    def test_duplicate_allowed_with_flag(self):
        # 第一次导入成功
        preview = [
            {
                "row_number": 2, "source_sheet": "FAQ", "source_type": "faq",
                "title": "允许重复", "content": "允许重复回答", "content_preview": "允许重复回答",
                "intent": "general", "risk_level": "low",
                "auto_reply_allowed": True, "human_review_required": False,
                "warnings": [], "errors": [], "duplicate_candidate": False,
                "content_hash": "dup_hash_allow", "import_batch_id": "batch_003",
            }
        ]
        r1 = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="b1", allow_duplicates=False)
        assert r1["success"] == 1

        # 第二次导入相同内容，但 allow_duplicates=True 应绕过数据库去重
        preview2 = [dict(preview[0], content="允许重复回答", content_hash="dup_hash_allow")]
        r2 = KnowledgeImportService.import_from_preview(preview2, user="op", batch_id="b2", allow_duplicates=True)
        assert r2["success"] == 1

    def test_high_risk_forces_review(self):
        preview = [
            {
                "row_number": 2, "source_sheet": "高风险SOP", "source_type": "high_risk_sop",
                "title": "客诉SOP", "content": "处理步骤", "content_preview": "处理步骤",
                "intent": "complaint", "risk_level": "medium",
                "auto_reply_allowed": True, "human_review_required": False,
                "warnings": [], "errors": [], "duplicate_candidate": False,
                "content_hash": "hr_001", "import_batch_id": "batch_004",
            }
        ]
        result = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="b3")
        entry = KnowledgeEntryRepository.get_by_id(result["created_ids"][0])
        assert entry.auto_reply_allowed is False
        assert entry.human_review_required is True
        assert entry.risk_level == "high"

    def test_import_report_format(self):
        preview = [
            {
                "row_number": 2, "source_sheet": "FAQ", "source_type": "faq",
                "title": "Q1", "content": "A1", "content_preview": "A1",
                "intent": "general", "risk_level": "low",
                "auto_reply_allowed": True, "human_review_required": False,
                "warnings": [], "errors": [], "duplicate_candidate": False,
                "content_hash": "rep_001", "import_batch_id": "batch_005",
            }
        ]
        result = KnowledgeImportService.import_from_preview(preview, user="op", batch_id="batch_005")
        assert "batch_id" in result
        assert "success" in result
        assert "failed" in result
        assert "errors" in result
        assert "created_ids" in result
        assert "audit_logs" in result
        assert result["success"] == 1
        assert result["failed"] == 0


class TestProductFactsStructuredImport:
    """product_facts 结构化导入优化"""

    def test_product_facts_generates_content_from_structure(self):
        """无 answer 字段但有结构化字段时应生成 content"""
        raw = {
            "商品名称": "三层火箭书架",
            "SKU": "YH04K14B01S03",
            "材质": "E1级环保板材",
            "尺寸": "60x30x90cm",
            "承重": "15-25kg/层",
            "适用年龄": "0-6岁",
            "配件": "防倾倒配件×1",
            "安装方式": "简易安装",
            "质保": "1年",
            "物流属性": "中通快递",
        }
        item, err = _build_preview_item(raw, 2, "商品总览", "product_facts", "batch_006")
        assert not item["errors"]
        assert item["content_generated"] is True
        assert "三层火箭书架" in item["content"]
        assert "材质：E1级环保板材" in item["content"]
        assert "SKU：YH04K14B01S03" in item["content"]

    def test_product_facts_only_fails_when_all_empty(self):
        """全字段为空才 failed"""
        raw = {"商品名称": "", "材质": "", "尺寸": ""}
        item, err = _build_preview_item(raw, 2, "商品总览", "product_facts", "batch_007")
        assert item["errors"]  # 应该失败

    def test_product_facts_not_fail_with_partial_fields(self):
        """只有部分字段时也能生成 content"""
        raw = {"商品名称": "测试书架", "材质": "实木", "尺寸": ""}
        item, err = _build_preview_item(raw, 2, "商品总览", "product_facts", "batch_008")
        assert not item["errors"]
        assert "商品名：测试书架" in item["content"]
        assert "材质：实木" in item["content"]


class TestDeduplicationOptimization:
    """去重逻辑优化"""

    def test_same_title_different_sku_not_duplicate(self):
        """同 title 不同 sku_code 不判重"""
        raw1 = {"商品名称": "儿童书架", "SKU": "SKU-A", "材质": "实木"}
        raw2 = {"商品名称": "儿童书架", "SKU": "SKU-B", "材质": "板材"}
        item1, _ = _build_preview_item(raw1, 2, "商品总览", "product_facts", "batch_009")
        item2, _ = _build_preview_item(raw2, 3, "商品总览", "product_facts", "batch_009")
        items = [item1, item2]
        from app.services.knowledge_import_service import _deduplicate_preview
        _deduplicate_preview(items)
        assert not item1.get("duplicate_candidate")
        assert not item2.get("duplicate_candidate")

    def test_same_title_different_content_marked_variant(self):
        """同 title 不同颜色/规格标记 possible_variant"""
        raw1 = {"商品名称": "儿童书架", "颜色": "白色", "材质": "实木"}
        raw2 = {"商品名称": "儿童书架", "颜色": "原木色", "材质": "实木"}
        item1, _ = _build_preview_item(raw1, 2, "商品总览", "product_facts", "batch_010")
        item2, _ = _build_preview_item(raw2, 3, "商品总览", "product_facts", "batch_010")
        items = [item1, item2]
        from app.services.knowledge_import_service import _deduplicate_preview
        _deduplicate_preview(items)
        assert item2.get("possible_variant") is True

    def test_same_content_hash_is_duplicate(self):
        """content_hash 完全一致才 duplicate"""
        raw1 = {"商品名称": "书架", "材质": "实木"}
        raw2 = {"商品名称": "书架", "材质": "实木"}
        item1, _ = _build_preview_item(raw1, 2, "商品总览", "product_facts", "batch_011")
        item2, _ = _build_preview_item(raw2, 3, "商品总览", "product_facts", "batch_011")
        items = [item1, item2]
        from app.services.knowledge_import_service import _deduplicate_preview
        _deduplicate_preview(items)
        assert not item1.get("duplicate_candidate")
        assert item2.get("duplicate_candidate") is True


class TestPreviewStatistics:
    """import-preview 统计增强"""

    def _create_csv(self, rows: list) -> str:
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            for r in rows:
                writer.writerow(r)
        return path

    def test_preview_returns_product_facts_generated_count(self):
        path = self._create_csv([
            ["商品名称", "材质", "尺寸"],
            ["书架A", "实木", "60cm"],
            ["", "", ""],  # 全空行，会被跳过
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="product_facts")
        os.unlink(path)
        assert "product_facts_generated_content_count" in result
        assert result["product_facts_generated_content_count"] == 1
        assert result["failed_count"] == 0

    def test_preview_returns_sheets_summary(self):
        path = self._create_csv([
            ["客户问题", "金牌回答"],
            ["Q1", "A1"],
            ["Q2", "A2"],
        ])
        result = KnowledgeImportService.parse_excel_preview(path, source_type_override="faq")
        os.unlink(path)
        assert "sheets_summary" in result
        assert result["sheets_summary"]["CSV"]["total"] == 2
        assert result["sheets_summary"]["CSV"]["valid"] == 2
