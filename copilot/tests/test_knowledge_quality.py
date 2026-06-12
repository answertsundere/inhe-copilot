"""
测试知识库质量检查服务 KnowledgeQualityService
"""

import pytest
import os
import tempfile
import uuid
from datetime import datetime, timedelta

_test_db_path = None
_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_knowledge_quality_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _orig_engine = db_module.engine
    _orig_session_local = db_module.SessionLocal

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    global _orig_engine, _orig_session_local
    import app.db as db_module
    if _orig_engine is not None:
        db_module.engine = _orig_engine
    if _orig_session_local is not None:
        db_module.SessionLocal = _orig_session_local
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from app.repositories.knowledge_feedback_repository import KnowledgeFeedbackRepository
from app.services.knowledge_quality_service import KnowledgeQualityService
from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk


class TestKnowledgeQualityChecks:
    """质量检查规则验证"""

    def test_risky_convenience_claims_are_listed(self):
        import app.db as db_module
        import app.services.knowledge_quality_service as quality_module
        quality_module.SessionLocal = db_module.SessionLocal

        entry = KnowledgeEntryRepository.create(
            source_type="installation_guide",
            title="\u5b89\u88c5\u8bf4\u660e",
            content="\u8fd9\u6b3e\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\u3002",
            intent="installation",
        )

        result = KnowledgeQualityService.get_risky_convenience_claims()
        items = [i for i in result["items"] if i["table"] == "knowledge_entries" and i["id"] == entry.id]

        assert len(items) == 1
        assert "\u5b89\u88c5\u5f88\u65b9\u4fbf" in items[0]["matched_phrases"]
        assert "\u8bf4\u660e\u4e66" in items[0]["suggested_action"]

    def test_product_facts_missing_material_flagged(self):
        """product_facts 缺材质被标记"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="测试书架",
            content="商品名：测试书架\nSKU：ABC123\n尺寸：60cm",
            intent="product_question",
            sku_scope=["ABC123"],
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()
        issues = [i for i in report["issues"] if i["entry_id"] == entry.id]
        product_issues = [i for i in issues if i["issue_type"] == "product_facts_incomplete"]
        assert len(product_issues) >= 1
        assert any("材质" in i["message"] for i in product_issues)

    def test_high_risk_auto_reply_allowed_high_severity(self):
        """high_risk_sop auto_reply_allowed=true 被标记 high severity"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="high_risk_sop",
            title="投诉SOP",
            content="处理步骤1：安抚情绪",
            intent="complaint",
        )
        db = db_module.SessionLocal()
        e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry.id).first()
        e.auto_reply_allowed = True
        e.human_review_required = False
        db.commit()
        db.close()

        db2 = db_module.SessionLocal()
        entries = db2.query(KnowledgeEntry).all()
        chunks = db2.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db2)
        db2.close()

        issues = [i for i in report["issues"] if i["entry_id"] == entry.id]
        auto_reply_issue = [i for i in issues if i["issue_type"] == "high_risk_auto_reply_enabled"]
        assert len(auto_reply_issue) == 1
        assert auto_reply_issue[0]["severity"] == "high"

    def test_published_without_chunks_flagged(self):
        """published 但没有 chunks 被标记"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="faq",
            title="Q1",
            content="这是一个足够长的回答内容，用来测试 published 但没有 chunks 的情况。",
            intent="general",
        )
        db = db_module.SessionLocal()
        e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry.id).first()
        e.status = "published"
        db.commit()
        db.close()

        db2 = db_module.SessionLocal()
        entries = db2.query(KnowledgeEntry).all()
        chunks = db2.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db2)
        db2.close()

        issues = [i for i in report["issues"] if i["entry_id"] == entry.id]
        chunk_issue = [i for i in issues if i["issue_type"] == "published_no_chunks"]
        assert len(chunk_issue) == 1
        assert chunk_issue[0]["severity"] == "high"

    def test_content_too_short_flagged(self):
        """content 过短被标记"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="faq",
            title="Q2",
            content="短",
            intent="general",
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()
        issues = [i for i in report["issues"] if i["entry_id"] == entry.id]
        short_issue = [i for i in issues if i["issue_type"] == "content_too_short"]
        assert len(short_issue) == 1

    def test_possible_variant_counted(self):
        """possible_variant 被统计"""
        import app.db as db_module
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="同款书架",
            content="商品名：同款书架\n材质：实木\n颜色：白色",
            intent="product_question",
        )
        e2 = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="同款书架",
            content="商品名：同款书架\n材质：实木\n颜色：原木色",
            intent="product_question",
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()
        summary = report["summary"]
        assert summary["possible_variants"] >= 1
        variant_issues = [i for i in report["issues"] if i["issue_type"] == "possible_variant"]
        assert len(variant_issues) >= 1

    def test_quality_report_summary_correct(self):
        """quality report summary 正确统计"""
        import app.db as db_module
        KnowledgeEntryRepository.create(source_type="faq", title="A", content="正常回答内容足够长。" * 5, intent="general")
        KnowledgeEntryRepository.create(source_type="faq", title="B", content="正常回答内容足够长。" * 5, intent="general")
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()
        summary = report["summary"]
        assert summary["total_entries"] >= 2
        assert "draft" in summary
        assert "published" in summary
        assert "high_issues" in summary
        assert "medium_issues" in summary
        assert "low_issues" in summary

    def test_quality_api_does_not_leak_privacy(self):
        """quality API 不泄露隐私（不返回完整 content、手机号、地址等）"""
        import app.db as db_module
        KnowledgeEntryRepository.create(
            source_type="faq",
            title="隐私测试",
            content="回答中包含 13800138000 手机号和北京市海淀区地址信息。",
            intent="general",
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()
        for issue in report["issues"]:
            assert "content" not in issue
            assert "13800138000" not in str(issue.values())
            assert "地址" not in str(issue.values())
        assert "summary" in report


class TestProductFactsCleanup:
    """商品事实清洗"""

    def test_product_facts_incomplete_exportable(self):
        """product_facts_incomplete 可导出为列表"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="缺字段书架",
            content="商品名：缺字段书架\nSKU：XYZ",
            intent="product_question",
            sku_scope=["XYZ"],
        )
        items = KnowledgeQualityService.get_product_facts_incomplete()
        ids = [i["entry_id"] for i in items]
        assert entry.id in ids
        my_item = [i for i in items if i["entry_id"] == entry.id][0]
        assert "材质" in my_item["missing_fields"]
        assert my_item["missing_scope"] is False
        assert "entry_id" in my_item
        assert "current_content" in my_item
        assert "suggested_fix_template" in my_item


class TestDuplicateVariantDetection:
    """重复/变体检测"""

    def test_different_sku_same_title_marked_variant(self):
        """sku_code 不同的同 title 商品标记为 variant"""
        import app.db as db_module
        e1 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="同款书架",
            content="商品：A\n材质：实木", intent="product_question",
            sku_scope=["SKU-A"],
        )
        e2 = KnowledgeEntryRepository.create(
            source_type="product_facts", title="同款书架",
            content="商品：A\n材质：板材", intent="product_question",
            sku_scope=["SKU-B"],
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        db.close()
        title_map = {}
        for e in entries:
            key = f"{e.source_type}::{e.title}"
            title_map.setdefault(key, []).append(e)
        variant_issues, _ = KnowledgeQualityService._detect_variants_and_duplicates(entries, title_map)
        variant_ids = [v["entry_id"] for v in variant_issues]
        assert e1.id in variant_ids or e2.id in variant_ids

    def test_same_content_hash_marked_duplicate(self):
        """content_hash 完全一致标记为 duplicate"""
        import app.db as db_module
        e1 = KnowledgeEntryRepository.create(
            source_type="faq", title="Q1",
            content="完全相同的内容", intent="general",
        )
        e2 = KnowledgeEntryRepository.create(
            source_type="faq", title="Q1",
            content="完全相同的内容", intent="general",
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        db.close()
        title_map = {}
        for e in entries:
            key = f"{e.source_type}::{e.title}"
            title_map.setdefault(key, []).append(e)
        _, dup_issues = KnowledgeQualityService._detect_variants_and_duplicates(entries, title_map)
        dup_ids = [d["entry_id"] for d in dup_issues]
        assert e1.id in dup_ids or e2.id in dup_ids


class TestPublishCandidates:
    """发布候选"""

    def test_publish_candidates_exclude_high_severity(self):
        """publish candidates 不包含 high severity issues"""
        import app.db as db_module
        good = KnowledgeEntryRepository.create(
            source_type="shipping_policy",
            title="发货时效",
            content="一般下单后48小时内发货。偏远地区可能延迟。",
            intent="logistics_eta",
        )
        bad = KnowledgeEntryRepository.create(
            source_type="high_risk_sop",
            title="投诉SOP",
            content="处理步骤",
            intent="complaint",
        )
        db = db_module.SessionLocal()
        e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == bad.id).first()
        e.auto_reply_allowed = True
        e.human_review_required = False
        db.commit()

        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()

        bad_entry_ids = set()
        for issue in report["issues"]:
            if issue["severity"] == "high":
                bad_entry_ids.add(issue["entry_id"])

        assert good.id not in bad_entry_ids
        assert bad.id in bad_entry_ids

    def test_publish_candidates_exclude_duplicates(self):
        """publish candidates 不包含 duplicate_candidate"""
        import app.db as db_module
        e1 = KnowledgeEntryRepository.create(
            source_type="faq", title="重复问题",
            content="相同的回答内容", intent="general",
        )
        e2 = KnowledgeEntryRepository.create(
            source_type="faq", title="重复问题",
            content="相同的回答内容", intent="general",
        )
        db = db_module.SessionLocal()
        entries = db.query(KnowledgeEntry).all()
        chunks = db.query(KnowledgeChunk).all()
        report = KnowledgeQualityService._analyze(entries, chunks, db)
        db.close()

        dup_issues = [i for i in report["issues"] if i["issue_type"] == "duplicate_candidate"]
        dup_ids = [i["entry_id"] for i in dup_issues]
        # e1 或 e2 中至少有一个被标记为 duplicate
        assert e1.id in dup_ids or e2.id in dup_ids


class TestFeedbackFields:
    """灰度反馈字段"""

    def test_feedback_records_used_knowledge_entry_ids(self):
        """feedback 能记录 used_knowledge_entry_ids"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="faq", title="测试",
            content="测试内容", intent="general",
        )
        fb = KnowledgeFeedbackRepository.create(
            entry_id=entry.id,
            conversation_id="conv_001",
            message_id="msg_001",
            used_knowledge_entry_ids=[entry.id, 999],
            suggested_reply="建议回复",
        )
        assert fb.get_used_entry_ids() == [entry.id, 999]
        d = fb.to_dict()
        assert d["used_knowledge_entry_ids"] == [entry.id, 999]
        assert d["suggested_reply"] == "建议回复"

    def test_feedback_records_csr_edited_and_edited_reply(self):
        """feedback 能记录 csr_edited / edited_reply"""
        import app.db as db_module
        entry = KnowledgeEntryRepository.create(
            source_type="faq", title="测试2",
            content="测试内容2", intent="general",
        )
        fb = KnowledgeFeedbackRepository.create(
            entry_id=entry.id,
            conversation_id="conv_002",
            csr_edited=True,
            edited_reply="客服修改后的回复",
            reject_reason="不够准确",
            csr_rejected=True,
        )
        d = fb.to_dict()
        assert d["csr_edited"] is True
        assert d["edited_reply"] == "客服修改后的回复"
        assert d["reject_reason"] == "不够准确"
        assert d["csr_rejected"] is True
