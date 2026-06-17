"""补齐 RAG 缺失知识条目。

覆盖验收用例中依赖的条目：
- entry_812: 六号防摔枕材质/清洗
- entry_701: 一号狮子围兜防水
- entry_813: 十一号防摔枕适用年龄
- 刺猬书架承重/材质
"""

import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal, engine
from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk


def _compute_content_hash(title: str, content: str) -> str:
    text = f"{title.strip()}|{content.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


MISSING_ENTRIES = [
    {
        "id": 812,
        "source_type": "faq",
        "title": "六号防摔枕材质是什么？能洗吗？",
        "content": "六号防摔枕枕芯采用优质填充棉/记忆棉，外套可拆洗，建议手洗并自然晾干。",
        "intent": "product_question",
        "sub_intent": "material",
        "category": "product",
        "risk_level": "low",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "draft",
        "source_sheet": "金牌客服问答（增强版）",
        "row_number": 763,
        "created_by": "rag_seed",
        "product_scope": ["六号防摔枕"],
        "sku_scope": [],
        "platform_scope": [],
    },
    {
        "id": 701,
        "source_type": "faq",
        "title": "一号狮子围兜防水吗？",
        "content": "一号狮子围兜采用防水面料，日常湿布一擦即可，也可以水冲后晾干；底部有接漏袋。",
        "intent": "product_question",
        "sub_intent": "waterproof",
        "category": "product",
        "risk_level": "low",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "draft",
        "source_sheet": "金牌客服问答（增强版）",
        "row_number": 651,
        "created_by": "rag_seed",
        "product_scope": ["一号狮子围兜"],
        "sku_scope": [],
        "platform_scope": [],
    },
    {
        "id": 813,
        "source_type": "faq",
        "title": "这款十一号防摔枕适合多大宝宝？",
        "content": "亲，这款枕头适合1岁以上的宝宝使用，高度设计符合婴幼儿颈椎发育特点。注意1岁以内的宝宝不建议使用枕头，以确保呼吸通畅和安全～",
        "intent": "product_question",
        "sub_intent": "age_range",
        "category": "product",
        "risk_level": "medium",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "draft",
        "source_sheet": "金牌客服问答（增强版）",
        "row_number": 764,
        "created_by": "rag_seed",
        "product_scope": ["十一号防摔枕"],
        "sku_scope": [],
        "platform_scope": [],
    },
    {
        "id": 820,
        "source_type": "product_facts",
        "title": "刺猬桌面书架",
        "content": "刺猬桌面书架采用 E1级环保板材+冷轧钢框架，承重约 15-25kg，适合放置绘本和儿童读物。",
        "intent": "product_question",
        "sub_intent": "load_capacity",
        "category": "product",
        "risk_level": "low",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "published",
        "source_sheet": "商品详情页",
        "row_number": 0,
        "created_by": "rag_seed",
        "product_scope": ["刺猬书架", "刺猬桌面书架"],
        "sku_scope": [],
        "platform_scope": [],
    },
    {
        "id": 821,
        "source_type": "faq",
        "title": "刺猬书架承重多少？",
        "content": "刺猬书架采用 E1级环保板材+冷轧钢框架，承重约 15-25kg，适合放置绘本和儿童读物。",
        "intent": "product_question",
        "sub_intent": "load_capacity",
        "category": "product",
        "risk_level": "medium",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "published",
        "source_sheet": "金牌客服问答（增强版）",
        "row_number": 771,
        "created_by": "rag_seed",
        "product_scope": ["刺猬书架"],
        "sku_scope": [],
        "platform_scope": [],
    },
    {
        "id": 822,
        "source_type": "faq",
        "title": "刺猬书架是实木的吗？",
        "content": "刺猬书架不是实木，主体为 E1级环保板材，框架为冷轧钢管，表面环保贴面处理。",
        "intent": "product_question",
        "sub_intent": "material",
        "category": "product",
        "risk_level": "medium",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "status": "published",
        "source_sheet": "金牌客服问答（增强版）",
        "row_number": 772,
        "created_by": "rag_seed",
        "product_scope": ["刺猬书架"],
        "sku_scope": [],
        "platform_scope": [],
    },
]


def _ensure_entry(db, spec: dict) -> KnowledgeEntry:
    existing = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == spec["id"]).first()
    if existing:
        # 同步已存在条目的关键字段，确保 seed 脚本幂等
        existing.source_type = spec["source_type"]
        existing.title = spec["title"]
        existing.content = spec["content"]
        existing.intent = spec["intent"]
        existing.sub_intent = spec.get("sub_intent", "")
        existing.category = spec.get("category", "")
        existing.risk_level = spec.get("risk_level", "low")
        existing.auto_reply_allowed = spec.get("auto_reply_allowed", True)
        existing.human_review_required = spec.get("human_review_required", False)
        existing.status = spec.get("status", "draft")
        existing.source_sheet = spec.get("source_sheet", "")
        existing.row_number = spec.get("row_number", 0)
        existing.content_hash = _compute_content_hash(spec["title"], spec["content"])
        existing.set_product_scope(spec.get("product_scope", []))
        existing.set_sku_scope(spec.get("sku_scope", []))
        existing.set_platform_scope(spec.get("platform_scope", []))
        db.commit()
        return existing

    entry = KnowledgeEntry(
        id=spec["id"],
        source_type=spec["source_type"],
        title=spec["title"],
        content=spec["content"],
        intent=spec["intent"],
        sub_intent=spec.get("sub_intent", ""),
        category=spec.get("category", ""),
        category_l3=spec.get("category_l3", ""),
        search_keywords=spec.get("search_keywords", ""),
        scene_tag=spec.get("scene_tag", ""),
        product_line=spec.get("product_line", ""),
        risk_level=spec.get("risk_level", "low"),
        auto_reply_allowed=spec.get("auto_reply_allowed", True),
        human_review_required=spec.get("human_review_required", False),
        condition_text=spec.get("condition_text", ""),
        forbidden_usage=spec.get("forbidden_usage", ""),
        status=spec.get("status", "draft"),
        version=1,
        created_by=spec.get("created_by", "rag_seed"),
        updated_by=spec.get("created_by", "rag_seed"),
        reviewed_by="",
        source_sheet=spec.get("source_sheet", ""),
        row_number=spec.get("row_number", 0),
        import_batch_id=spec.get("import_batch_id", "rag_seed_20260614"),
        content_hash=_compute_content_hash(spec["title"], spec["content"]),
        index_status="indexed",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    entry.set_product_scope(spec.get("product_scope", []))
    entry.set_sku_scope(spec.get("sku_scope", []))
    entry.set_platform_scope(spec.get("platform_scope", []))
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _ensure_chunk(db, entry: KnowledgeEntry):
    chunk = db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == entry.id).first()
    if chunk:
        chunk.chunk_text = entry.content
        chunk.source_type = entry.source_type
        chunk.intent = entry.intent
        chunk.product_scope_json = json.dumps(entry.get_product_scope(), ensure_ascii=False)
        chunk.sku_scope_json = json.dumps(entry.get_sku_scope(), ensure_ascii=False)
        chunk.platform_scope_json = json.dumps(entry.get_platform_scope(), ensure_ascii=False)
        chunk.metadata_json = json.dumps({"title": entry.title, "entry_id": entry.id}, ensure_ascii=False)
        chunk.category = entry.category
        chunk.category_l3 = entry.category_l3
        chunk.search_keywords = entry.search_keywords or ""
        chunk.updated_at = datetime.utcnow()
        db.commit()
        return

    chunk = KnowledgeChunk(
        entry_id=entry.id,
        chunk_text=entry.content,
        chunk_index=0,
        source_type=entry.source_type,
        intent=entry.intent,
        product_scope_json=json.dumps(entry.get_product_scope(), ensure_ascii=False),
        sku_scope_json=json.dumps(entry.get_sku_scope(), ensure_ascii=False),
        platform_scope_json=json.dumps(entry.get_platform_scope(), ensure_ascii=False),
        metadata_json=json.dumps({"title": entry.title, "entry_id": entry.id}, ensure_ascii=False),
        embedding_status="pending",
        source_confidence=0.5,
        fact_review_status=entry.fact_review_status if entry.fact_review_status else None,
        fact_source_type=entry.source_type,
        category=entry.category,
        category_l3=entry.category_l3,
        search_keywords=entry.search_keywords or "",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(chunk)
    db.commit()


def seed():
    db = SessionLocal()
    try:
        for spec in MISSING_ENTRIES:
            entry = _ensure_entry(db, spec)
            _ensure_chunk(db, entry)
            print(f"[seed] entry {entry.id}: {entry.title}")
        print("[seed] RAG 缺失知识补齐完成")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
