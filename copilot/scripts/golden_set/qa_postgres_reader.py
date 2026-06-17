"""
QA PostgreSQL Reader — 从客服质检系统 PostgreSQL 只读读取会话数据。

只读原则：只执行 SELECT 查询，不修改任何数据。

连接配置通过环境变量 QA_DATABASE_URL 读取。
默认: postgresql://postgres:postgres@127.0.0.1:15433/qa_db
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CUTOFF_DEFAULT = datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone(timedelta(hours=8)))

# ---------- 连接 ----------

def _get_database_url() -> str:
    url = os.environ.get("QA_DATABASE_URL", "")
    if url:
        return url
    return "postgresql://postgres:postgres@127.0.0.1:15433/qa_db"


def get_connection():
    import psycopg2
    url = _get_database_url()
    conn = psycopg2.connect(url, connect_timeout=10)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def test_connection() -> dict:
    result = {"connected": False, "tables": [], "error": ""}
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        result["tables"] = [r[0] for r in cur.fetchall()]
        result["connected"] = True
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------- 数据审计 ----------

def run_source_audit(cutoff: datetime = CUTOFF_DEFAULT) -> dict:
    """生成数据源审计报告，不修改任何数据。"""
    report = {
        "database_connected": False,
        "cutoff": cutoff.isoformat(),
        "tables": [],
        "total_messages": 0,
        "cutoff_messages": 0,
        "cutoff_customer_messages": 0,
        "cutoff_agent_messages": 0,
        "cutoff_chats": 0,
        "cutoff_business_sessions": 0,
        "data_quality_distribution": {},
        "scoreable_count": 0,
        "complete_count": 0,
        "history_truncated_count": 0,
        "earliest_sent_at": None,
        "latest_sent_at": None,
        "pre_cutoff_excluded_messages": 0,
        "error": "",
    }

    try:
        conn = get_connection()
        cur = conn.cursor()
        report["database_connected"] = True

        # Tables
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        report["tables"] = [r[0] for r in cur.fetchall()]

        # Total messages
        cur.execute("SELECT COUNT(*) FROM chat_messages")
        report["total_messages"] = cur.fetchone()[0]

        # Time range
        cur.execute("SELECT MIN(sent_at), MAX(sent_at) FROM chat_messages")
        r = cur.fetchone()
        report["earliest_sent_at"] = str(r[0]) if r[0] else None
        report["latest_sent_at"] = str(r[1]) if r[1] else None

        # Cutoff filtered counts
        cutoff_str = cutoff.isoformat()
        cur.execute("SELECT COUNT(*) FROM chat_messages WHERE sent_at >= %s", (cutoff_str,))
        report["cutoff_messages"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM chat_messages WHERE sent_at < %s", (cutoff_str,))
        report["pre_cutoff_excluded_messages"] = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE sent_at >= %s AND sender_type = 'customer'",
            (cutoff_str,),
        )
        report["cutoff_customer_messages"] = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE sent_at >= %s AND sender_type = 'agent'",
            (cutoff_str,),
        )
        report["cutoff_agent_messages"] = cur.fetchone()[0]

        # Chats with messages after cutoff
        cur.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM chats c
            JOIN chat_messages cm ON cm.chat_id = c.id
            WHERE cm.sent_at >= %s
        """, (cutoff_str,))
        report["cutoff_chats"] = cur.fetchone()[0]

        # Business sessions after cutoff
        cur.execute(
            "SELECT COUNT(*) FROM business_sessions WHERE first_message_time >= %s",
            (cutoff_str,),
        )
        report["cutoff_business_sessions"] = cur.fetchone()[0]

        # Data quality distribution for chats with cutoff messages
        cur.execute("""
            SELECT c.data_quality_status, c.scoreable, COUNT(DISTINCT c.id)
            FROM chats c
            JOIN chat_messages cm ON cm.chat_id = c.id
            WHERE cm.sent_at >= %s
            GROUP BY c.data_quality_status, c.scoreable
            ORDER BY COUNT(*) DESC
        """, (cutoff_str,))
        for row in cur.fetchall():
            key = f"{row[0]}_scoreable={row[1]}"
            report["data_quality_distribution"][key] = row[2]

        # Aggregate quality counts
        cur.execute("""
            SELECT
                SUM(CASE WHEN c.scoreable = true THEN 1 ELSE 0 END) as scoreable,
                SUM(CASE WHEN c.data_quality_status = 'complete' THEN 1 ELSE 0 END) as complete,
                SUM(CASE WHEN c.data_quality_status = 'history_truncated' THEN 1 ELSE 0 END) as truncated
            FROM chats c
            JOIN chat_messages cm ON cm.chat_id = c.id
            WHERE cm.sent_at >= %s
        """, (cutoff_str,))
        r = cur.fetchone()
        report["scoreable_count"] = r[0] or 0
        report["complete_count"] = r[1] or 0
        report["history_truncated_count"] = r[2] or 0

        conn.close()
    except Exception as e:
        report["error"] = str(e)
        logger.error("Source audit failed: %s", e)

    return report


# ---------- 会话读取 ----------

def read_sessions(
    cutoff: datetime = CUTOFF_DEFAULT,
    limit: int = 0,
    quality_filter: list | None = None,
    scoreable_only: bool = True,
    offset: int = 0,
) -> list[dict]:
    """
    读取符合条件的会话及其消息。

    过滤规则:
    1. 会话中所有消息的 sent_at >= cutoff
    2. 至少有1条客户消息和1条客服消息
    3. 排除 history_truncated
    4. 可选: scoreable=true
    """
    conn = get_connection()
    cur = conn.cursor()
    cutoff_str = cutoff.isoformat()

    # Find chat IDs where ALL messages are after cutoff
    # and chat has both customer and agent messages
    quality_filter = quality_filter or ["complete", "low_interaction_scoreable"]

    query = """
        SELECT c.id, c.chat_id, c.data_quality_status, c.scoreable,
               c.customer_message_count, c.agent_message_count,
               c.data_completeness_score, c.scene_type, c.source_file,
               c.capture_time
        FROM chats c
        WHERE c.customer_message_count >= 1
          AND c.agent_message_count >= 1
          AND c.data_quality_status = ANY(%s)
          AND c.id IN (
              SELECT DISTINCT cm.chat_id
              FROM chat_messages cm
              WHERE cm.sent_at >= %s
          )
          AND c.id NOT IN (
              SELECT DISTINCT cm2.chat_id
              FROM chat_messages cm2
              WHERE cm2.sent_at < %s
          )
    """
    params = [quality_filter, cutoff_str, cutoff_str]

    if scoreable_only:
        query += " AND c.scoreable = true"

    query += " ORDER BY c.capture_time DESC"

    if limit > 0:
        query += f" LIMIT {limit} OFFSET {offset}"

    cur.execute(query, params)
    chat_rows = cur.fetchall()

    sessions = []
    for row in chat_rows:
        chat_pk = row[0]
        session = {
            "chat_pk": chat_pk,
            "chat_id": row[1],
            "data_quality_status": row[2],
            "scoreable": row[3],
            "customer_message_count": row[4],
            "agent_message_count": row[5],
            "data_completeness_score": row[6],
            "scene_type": row[7],
            "source_file": row[8],
            "capture_time": str(row[9]) if row[9] else None,
            "messages": [],
        }

        # Load messages
        cur.execute("""
            SELECT cm.id, cm.message_seq, cm.sender_type, cm.sender_name,
                   cm.content, cm.content_type, cm.message_type, cm.sent_at,
                   cm.product_url, cm.product_item_id
            FROM chat_messages cm
            WHERE cm.chat_id = %s
            ORDER BY cm.message_seq
        """, (chat_pk,))
        for msg in cur.fetchall():
            session["messages"].append({
                "id": msg[0],
                "seq": msg[1],
                "sender_type": msg[2],
                "sender_name": msg[3],
                "content": msg[4],
                "content_type": msg[5],
                "message_type": msg[6],
                "sent_at": str(msg[7]) if msg[7] else None,
                "product_url": msg[8],
                "product_item_id": msg[9],
            })

        # Verify no messages before cutoff
        has_pre_cutoff = False
        for m in session["messages"]:
            if m["sent_at"]:
                try:
                    from dateutil.parser import isoparse
                    msg_time = isoparse(m["sent_at"])
                    if msg_time < cutoff:
                        has_pre_cutoff = True
                        break
                except Exception:
                    pass

        if not has_pre_cutoff and session["messages"]:
            sessions.append(session)

    conn.close()
    return sessions


def read_business_sessions(
    cutoff: datetime = CUTOFF_DEFAULT,
    limit: int = 0,
    offset: int = 0,
) -> list[dict]:
    """读取跨批次合并的 business sessions。"""
    conn = get_connection()
    cur = conn.cursor()
    cutoff_str = cutoff.isoformat()

    query = """
        SELECT bs.id, bs.business_session_key, bs.buyer_name, bs.primary_agent,
               bs.order_id, bs.product_item_id, bs.product_url,
               bs.first_message_time, bs.last_message_time,
               bs.message_count, bs.customer_message_count, bs.agent_message_count,
               bs.data_quality_status, bs.scoreable, bs.data_completeness_score,
               bs.interaction_depth
        FROM business_sessions bs
        WHERE bs.first_message_time >= %s
          AND bs.customer_message_count >= 1
          AND bs.agent_message_count >= 1
          AND bs.data_quality_status NOT IN ('history_truncated', 'system_only', 'empty', 'duplicate')
        ORDER BY bs.first_message_time DESC
    """
    params = [cutoff_str]

    if limit > 0:
        query += f" LIMIT {limit} OFFSET {offset}"

    cur.execute(query, params)
    rows = cur.fetchall()

    sessions = []
    for row in rows:
        sessions.append({
            "id": row[0],
            "session_key": row[1],
            "buyer_name": row[2],
            "primary_agent": row[3],
            "order_id": row[4],
            "product_item_id": row[5],
            "product_url": row[6],
            "first_message_time": str(row[7]) if row[7] else None,
            "last_message_time": str(row[8]) if row[8] else None,
            "message_count": row[9],
            "customer_message_count": row[10],
            "agent_message_count": row[11],
            "data_quality_status": row[12],
            "scoreable": row[13],
            "data_completeness_score": row[14],
            "interaction_depth": row[15],
        })

    conn.close()
    return sessions


# ---------- 哈希与去重 ----------

def compute_session_hash(session: dict) -> str:
    """基于脱敏前内容计算稳定哈希。"""
    parts = []
    for m in session.get("messages", []):
        sender = m.get("sender_type", "")
        content = m.get("content", "") or ""
        sent_at = m.get("sent_at", "") or ""
        parts.append(f"{sender}|{sent_at}|{content}")

    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_record_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]
