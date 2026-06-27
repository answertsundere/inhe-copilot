"""
客服知识库数据库配置 - SQLite + SQLAlchemy
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import KNOWLEDGE_DB_PATH

engine = create_engine(
    f"sqlite:///{KNOWLEDGE_DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

Base = declarative_base()


def _migrate_add_columns():
    """SQLite 兼容的列添加迁移"""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)

    # knowledge_feedback 表迁移
    if "knowledge_feedback" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("knowledge_feedback")}
        new_columns = [
            ("suggested_reply", "TEXT", "''"),
            ("used_knowledge_entry_ids", "TEXT", "''"),
            ("csr_rejected", "BOOLEAN", "0"),
            ("edited_reply", "TEXT", "''"),
            ("reject_reason", "TEXT", "''"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE knowledge_feedback ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # knowledge_chunks 表迁移 - RAG embedding + 事实审核字段
    if "knowledge_chunks" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("knowledge_chunks")}
        new_columns = [
            ("embedding_json", "TEXT", "NULL"),
            ("source_confidence", "REAL", "0.5"),
            ("fact_review_status", "TEXT", "NULL"),
            ("fact_source_type", "TEXT", "NULL"),
            ("updated_at", "DATETIME", "NULL"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE knowledge_chunks ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # knowledge_entries 表迁移 - 事实审核字段 + 索引状态 + revision 关系
    if "knowledge_entries" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("knowledge_entries")}
        new_columns = [
            ("source_confidence", "REAL", "0.5"),
            ("fact_review_status", "TEXT", "NULL"),
            ("index_status", "TEXT", "'pending'"),
            ("parent_entry_id", "INTEGER", "NULL"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE knowledge_entries ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # kb_qa 表迁移 - 分类和 SOP 关联字段
    if "kb_qa" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("kb_qa")}
        new_columns = [
            ("scenario_category", "VARCHAR(64)", "''"),
            ("issue_type", "VARCHAR(64)", "''"),
            ("sop_id", "INTEGER", "NULL"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE kb_qa ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # kb_sop 表迁移 - agent_action 字段
    if "kb_sop" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("kb_sop")}
        new_columns = [
            ("agent_action", "VARCHAR(32)", "'auto_reply'"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE kb_sop ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # kb_media_asset 表迁移 - 链接保鲜 / 自动刷新 / 审核人
    if "kb_media_asset" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("kb_media_asset")}
        new_columns = [
            ("url_expires_at", "DATETIME", "NULL"),
            ("refresh_status", "VARCHAR(16)", "'ok'"),
            ("source_updated_at", "DATETIME", "NULL"),
            ("reviewed_by", "VARCHAR(64)", "''"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE kb_media_asset ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()
        # 新增索引
        idx_sql = [
            "CREATE INDEX IF NOT EXISTS idx_media_refresh_status ON kb_media_asset (refresh_status)",
            "CREATE INDEX IF NOT EXISTS idx_media_url_expires_at ON kb_media_asset (url_expires_at)",
        ]
        with engine.connect() as conn:
            for sql in idx_sql:
                conn.execute(text(sql))
            conn.commit()

    # kb_generic_service_rule 表迁移 - 通用服务规则运营字段
    if "kb_generic_service_rule" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("kb_generic_service_rule")}
        new_columns = [
            ("allowed_when_product_fact_missing", "BOOLEAN", "1"),
            ("required_guardrails_json", "TEXT", "'[]'"),
            ("priority", "INTEGER", "100"),
            ("version", "VARCHAR(32)", "'v1'"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE kb_generic_service_rule ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # knowledge_entries 表迁移 - 结构化业务键字段
    if "knowledge_entries" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("knowledge_entries")}
        new_columns = [
            ("business_key", "VARCHAR(128)", "NULL"),
            ("product_id", "VARCHAR(64)", "NULL"),
            ("sku_id", "VARCHAR(64)", "NULL"),
            ("fact_type", "VARCHAR(64)", "NULL"),
            ("fact_scope", "VARCHAR(32)", "''"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE knowledge_entries ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

        # 为新字段创建索引（SQLite ALTER TABLE 不自动创建索引）
        index_sql = [
            "CREATE INDEX IF NOT EXISTS ix_knowledge_entries_business_key ON knowledge_entries (business_key)",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_entries_product_id ON knowledge_entries (product_id)",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_entries_sku_id ON knowledge_entries (sku_id)",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_entries_fact_type ON knowledge_entries (fact_type)",
        ]
        with engine.connect() as conn:
            for sql in index_sql:
                conn.execute(text(sql))
            conn.commit()

    # eval replay tables - additive columns for QA review and repair routing.
    eval_table_columns = {
        "eval_failures": [
            ("suggested_fix_area", "VARCHAR(64)", "''"),
            ("suggested_owner", "VARCHAR(64)", "''"),
            ("explanation", "TEXT", "''"),
        ],
        "eval_reviews": [
            ("suggested_fix_area", "VARCHAR(64)", "''"),
        ],
        "eval_repair_tasks": [
            ("task_uid", "VARCHAR(64)", "''"),
            ("failure_type", "VARCHAR(64)", "''"),
            ("suggested_fix_area", "VARCHAR(64)", "''"),
            ("suggested_owner", "VARCHAR(64)", "''"),
            ("title", "VARCHAR(255)", "''"),
            ("description", "TEXT", "''"),
            ("sample_count", "INTEGER", "0"),
            ("related_case_uids_json", "TEXT", "'[]'"),
            ("related_turn_uids_json", "TEXT", "'[]'"),
            ("priority", "VARCHAR(16)", "'medium'"),
            ("created_by", "VARCHAR(64)", "''"),
            ("assigned_to", "VARCHAR(64)", "''"),
            ("resolution_note", "TEXT", "''"),
            ("last_verified_at", "DATETIME", "NULL"),
            ("verification_status", "VARCHAR(32)", "'not_verified'"),
            ("verification_run_uid", "VARCHAR(64)", "''"),
            ("verification_summary_json", "TEXT", "'{}'"),
            ("verified_by", "VARCHAR(64)", "''"),
        ],
        "eval_traces": [
            ("turn_understanding_json", "TEXT", "'{}'"),
        ],
        "knowledge_gap_publish_queue": [
            ("payload_fingerprint", "VARCHAR(64)", "''"),
            ("superseded_by", "VARCHAR(64)", "''"),
            ("superseded_reason", "TEXT", "''"),
            ("superseded_at", "DATETIME", "NULL"),
            ("superseded_by_reviewer", "VARCHAR(64)", "''"),
        ],
    }
    for table_name, new_columns in eval_table_columns.items():
        if table_name not in inspector.get_table_names():
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()

    # Training samples - evaluation set contract fields.
    if "kb_training_sample" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("kb_training_sample")}
        new_columns = [
            ("eval_contract_json", "TEXT", "'{}'"),
            ("eval_created_at", "DATETIME", "NULL"),
        ]
        with engine.connect() as conn:
            for col_name, col_type, default in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE kb_training_sample ADD COLUMN {col_name} {col_type} DEFAULT {default}"))
            conn.commit()


def init_db():
    """创建所有表（如果不存在）并执行迁移"""
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
