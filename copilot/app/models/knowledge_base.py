"""
客服知识库数据模型 - SQLAlchemy ORM
"""

import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey,
    Index, event,
)
from sqlalchemy.orm import relationship

from app.db import Base


class KnowledgeEntry(Base):
    """知识条目主表"""
    __tablename__ = "knowledge_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(32), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    intent = Column(String(64), nullable=False, default="general", index=True)
    sub_intent = Column(String(64), nullable=False, default="")
    category = Column(String(64), nullable=False, default="")
    category_l3 = Column(String(64), nullable=False, default="")
    search_keywords = Column(Text, nullable=False, default="")
    scene_tag = Column(String(32), nullable=False, default="")
    product_line = Column(String(64), nullable=False, default="")

    # 适用范围 - JSON 字符串存储
    product_scope_json = Column(Text, nullable=False, default="[]")
    sku_scope_json = Column(Text, nullable=False, default="[]")
    platform_scope_json = Column(Text, nullable=False, default="[]")

    risk_level = Column(String(16), nullable=False, default="low", index=True)
    auto_reply_allowed = Column(Boolean, nullable=False, default=True)
    human_review_required = Column(Boolean, nullable=False, default=False)
    condition_text = Column(Text, nullable=False, default="")
    forbidden_usage = Column(Text, nullable=False, default="")

    status = Column(
        String(16),
        nullable=False,
        default="draft",
        index=True,
    )
    version = Column(Integer, nullable=False, default=1)

    # 操作人
    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    reviewed_by = Column(String(64), nullable=False, default="")

    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 导入溯源
    source_sheet = Column(String(128), nullable=False, default="")
    row_number = Column(Integer, nullable=False, default=0)
    import_batch_id = Column(String(64), nullable=False, default="")
    content_hash = Column(String(64), nullable=False, default="", index=True)

    # Revision 版本关系
    parent_entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=True, index=True)

    # 结构化业务键（商品知识导入专用）
    business_key = Column(String(128), nullable=True, index=True)
    product_id = Column(String(64), nullable=True, index=True)
    sku_id = Column(String(64), nullable=True, index=True)
    fact_type = Column(String(64), nullable=True, index=True)
    fact_scope = Column(String(32), nullable=True, default="")

    # RAG 事实审核字段
    source_confidence = Column(Float, nullable=True, default=0.5)
    fact_review_status = Column(String(32), nullable=True)

    # 索引状态
    index_status = Column(String(32), nullable=False, default="pending")

    # 关系
    chunks = relationship("KnowledgeChunk", back_populates="entry", cascade="all, delete-orphan")
    versions = relationship("KnowledgeVersion", back_populates="entry", cascade="all, delete-orphan")
    feedbacks = relationship("KnowledgeFeedback", back_populates="entry", cascade="all, delete-orphan")
    audit_logs = relationship("KnowledgeAuditLog", back_populates="entry", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_entry_source_intent_status", "source_type", "intent", "status"),
        Index("idx_entry_title", "title"),
    )

    def get_product_scope(self):
        try:
            return json.loads(self.product_scope_json or "[]")
        except Exception:
            return []

    def set_product_scope(self, value):
        self.product_scope_json = json.dumps(value if isinstance(value, list) else [value], ensure_ascii=False)

    def get_sku_scope(self):
        try:
            return json.loads(self.sku_scope_json or "[]")
        except Exception:
            return []

    def set_sku_scope(self, value):
        self.sku_scope_json = json.dumps(value if isinstance(value, list) else [value], ensure_ascii=False)

    def get_platform_scope(self):
        try:
            return json.loads(self.platform_scope_json or "[]")
        except Exception:
            return []

    def set_platform_scope(self, value):
        self.platform_scope_json = json.dumps(value if isinstance(value, list) else [value], ensure_ascii=False)

    def to_dict(self, include_content=True):
        d = {
            "id": self.id,
            "source_type": self.source_type,
            "title": self.title,
            "intent": self.intent,
            "sub_intent": self.sub_intent,
            "category": self.category,
            "product_scope": self.get_product_scope(),
            "sku_scope": self.get_sku_scope(),
            "platform_scope": self.get_platform_scope(),
            "risk_level": self.risk_level,
            "auto_reply_allowed": self.auto_reply_allowed,
            "human_review_required": self.human_review_required,
            "condition_text": self.condition_text,
            "forbidden_usage": self.forbidden_usage,
            "status": self.status,
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "reviewed_by": self.reviewed_by,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "source_sheet": self.source_sheet,
            "row_number": self.row_number,
            "import_batch_id": self.import_batch_id,
            "parent_entry_id": self.parent_entry_id,
            "business_key": self.business_key,
            "product_id": self.product_id,
            "sku_id": self.sku_id,
            "fact_type": self.fact_type,
            "fact_scope": self.fact_scope,
            "index_status": self.index_status,
            "source_confidence": self.source_confidence,
        }
        if include_content:
            d["content"] = self.content
        return d


class KnowledgeChunk(Base):
    """知识分片表 - 用于检索"""
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=False, index=True)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)

    # 冗余 metadata 用于快速过滤
    source_type = Column(String(32), nullable=False, index=True)
    intent = Column(String(64), nullable=False, default="general", index=True)
    product_scope_json = Column(Text, nullable=False, default="[]")
    sku_scope_json = Column(Text, nullable=False, default="[]")
    platform_scope_json = Column(Text, nullable=False, default="[]")
    metadata_json = Column(Text, nullable=False, default="{}")

    # 冗余分类字段，用于检索加分
    category = Column(String(64), nullable=False, default="")
    category_l3 = Column(String(64), nullable=False, default="")
    search_keywords = Column(Text, nullable=False, default="")

    embedding_status = Column(String(16), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # RAG embedding + 事实审核字段
    embedding_json = Column(Text, nullable=True)
    source_confidence = Column(Float, nullable=True, default=0.5)
    fact_review_status = Column(String(32), nullable=True)
    fact_source_type = Column(String(32), nullable=True)
    updated_at = Column(DateTime, nullable=True)

    entry = relationship("KnowledgeEntry", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunk_source_intent", "source_type", "intent"),
    )

    def get_metadata(self):
        try:
            return json.loads(self.metadata_json or "{}")
        except Exception:
            return {}

    def set_metadata(self, value):
        self.metadata_json = json.dumps(value, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "chunk_text": self.chunk_text,
            "chunk_index": self.chunk_index,
            "source_type": self.source_type,
            "intent": self.intent,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeVersion(Base):
    """知识版本表"""
    __tablename__ = "knowledge_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content_snapshot = Column(Text, nullable=False)
    changed_by = Column(String(64), nullable=False, default="")
    change_reason = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entry = relationship("KnowledgeEntry", back_populates="versions")

    def to_dict(self):
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "version": self.version,
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeFeedback(Base):
    """知识反馈记录表"""
    __tablename__ = "knowledge_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=False, index=True)
    conversation_id = Column(String(64), nullable=False, default="")
    message_id = Column(String(64), nullable=False, default="")
    agent_reply = Column(Text, nullable=False, default="")
    suggested_reply = Column(Text, nullable=False, default="")
    used_knowledge_entry_ids = Column(Text, nullable=False, default="")
    was_used = Column(Boolean, nullable=False, default=False)
    csr_accepted = Column(Boolean, nullable=False, default=False)
    csr_edited = Column(Boolean, nullable=False, default=False)
    csr_rejected = Column(Boolean, nullable=False, default=False)
    edited_reply = Column(Text, nullable=False, default="")
    reject_reason = Column(Text, nullable=False, default="")
    supervisor_score = Column(Integer, nullable=True)
    customer_result = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entry = relationship("KnowledgeEntry", back_populates="feedbacks")

    def to_dict(self):
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "agent_reply": self.agent_reply,
            "suggested_reply": self.suggested_reply,
            "used_knowledge_entry_ids": self.get_used_entry_ids(),
            "was_used": self.was_used,
            "csr_accepted": self.csr_accepted,
            "csr_edited": self.csr_edited,
            "csr_rejected": self.csr_rejected,
            "edited_reply": self.edited_reply,
            "reject_reason": self.reject_reason,
            "supervisor_score": self.supervisor_score,
            "customer_result": self.customer_result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def get_used_entry_ids(self):
        try:
            return json.loads(self.used_knowledge_entry_ids or "[]")
        except Exception:
            return []

    def set_used_entry_ids(self, value):
        self.used_knowledge_entry_ids = json.dumps(value if isinstance(value, list) else [value], ensure_ascii=False)


class KnowledgeAuditLog(Base):
    """知识审计日志表"""
    __tablename__ = "knowledge_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, ForeignKey("knowledge_entries.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False)
    old_status = Column(String(16), nullable=False, default="")
    new_status = Column(String(16), nullable=False, default="")
    performed_by = Column(String(64), nullable=False, default="")
    details = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entry = relationship("KnowledgeEntry", back_populates="audit_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "entry_id": self.entry_id,
            "action": self.action,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "performed_by": self.performed_by,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
