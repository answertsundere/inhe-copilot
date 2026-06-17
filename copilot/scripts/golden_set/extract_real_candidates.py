"""
Extract Real Candidates — 从真实聊天数据生成 Golden Set 候选。

执行流程:
1. 读取会话 (PostgreSQL 或 Excel)
2. 时间过滤 (sent_at >= cutoff)
3. 数据质量过滤
4. 消息类型过滤
5. 会话完整性检查
6. 脱敏
7. 精确去重
8. 语义聚类
9. 场景预分类
10. 难度预分类
11. 生成预标注候选
12. 输出人工审核队列

用法:
  python scripts/golden_set/extract_real_candidates.py --source postgres --report-only
  python scripts/golden_set/extract_real_candidates.py --source postgres --cutoff "2026-05-26T00:00:00+08:00"
  python scripts/golden_set/extract_real_candidates.py --source excel --excel-dir "D:/path/to/聊天记录"
  python scripts/golden_set/extract_real_candidates.py --source postgres --limit 500 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CUTOFF_DEFAULT = "2026-05-26T00:00:00+08:00"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "real_golden_candidates",
)
EXTRACTION_VERSION = "v1"

logger = logging.getLogger(__name__)


# ---------- 场景预分类 ----------

SCENARIO_RULES = [
    ("complaint_high_risk", [
        "投诉", "12315", "举报", "消费者协会", "工商", "差评", "曝光",
        "律师", "法院", "起诉", "诈骗", "欺诈", "假货", "退款不退",
    ]),
    ("aftersales_return", [
        "退货", "退款", "换货", "破损", "少件", "漏发", "发错",
        "质量问题", "坏了", "有瑕疵", "不满意", "不要了", "退回",
    ]),
    ("logistics", [
        "发货", "快递", "物流", "到货", "签收", "运费", "包邮",
        "配送", "邮寄", "单号", "揽收", "在途", "延误", "丢件",
    ]),
    ("product_question", [
        "材质", "尺寸", "承重", "防水", "可洗", "安全", "实木",
        "适合", "多大", "几岁", "重量", "厚", "规格", "颜色",
        "尺寸", "型号", "区别", "对比", "哪个好",
    ]),
    ("installation", [
        "安装", "组装", "说明书", "怎么装", "螺丝", "固定", "拆卸",
    ]),
    ("pre_sale_product", [
        "多少钱", "价格", "优惠", "折扣", "促销", "活动", "有货",
        "库存", "上架", "什么时候有", "买", "下单", "链接",
    ]),
]


def classify_scenario(messages: list[dict]) -> str:
    """根据消息内容预分类场景。"""
    customer_texts = []
    for m in messages:
        if m.get("sender_type") == "customer":
            content = (m.get("content") or "").strip()
            if content and len(content) > 2:
                customer_texts.append(content)

    all_text = " ".join(customer_texts).lower()

    if not all_text:
        return "unclear"

    # Score each scenario
    scores = {}
    for scenario, keywords in SCENARIO_RULES:
        score = sum(1 for kw in keywords if kw in all_text)
        scores[scenario] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        # Check if it looks like chitchat
        if any(kw in all_text for kw in ["你好", "在吗", "谢谢", "好的", "嗯", "哦"]):
            return "chitchat_ambiguous"
        return "unclear"

    return best


# ---------- 难度预分类 ----------

def classify_difficulty(session: dict) -> str:
    """评估会话难度。"""
    messages = session.get("messages", [])
    customer_msgs = [m for m in messages if m.get("sender_type") == "customer"]
    content = " ".join(m.get("content", "") for m in customer_msgs)

    hard_signals = 0
    medium_signals = 0

    # Multi-turn with pronouns
    if len(customer_msgs) >= 3:
        if any(w in content for w in ["这个", "那个", "它", "上面", "刚才"]):
            hard_signals += 1

    # Order number provided
    if re_search_order(content):
        medium_signals += 1

    # Incomplete product title
    if any(w in content for w in ["这个", "那个", "一号", "六号", "十一号"]):
        hard_signals += 1

    # Emotion escalation
    if any(w in content for w in ["太差", "气愤", "投诉", "差评", "骗"]):
        hard_signals += 1

    # Multi-intent
    scenario = classify_scenario(messages)
    if any(w in content for w in ["而且", "还有", "另外", "同时"]):
        hard_signals += 1

    # Typo/colloquial
    if any(w in content for w in ["咋", "啥", "咋个", "咋还", "咋不"]):
        medium_signals += 1

    if hard_signals >= 2:
        return "hard"
    if hard_signals >= 1 or medium_signals >= 2:
        return "medium"
    return "easy"


def re_search_order(text: str) -> bool:
    import re
    return bool(re.search(r"\d{10,}", text))


# ---------- 消息质量过滤 ----------

def is_valid_session(session: dict) -> tuple[bool, str]:
    """检查会话是否适合作为 Golden Set 候选。"""
    messages = session.get("messages", [])
    if not messages:
        return False, "no_messages"

    customer_msgs = [m for m in messages if m.get("sender_type") == "customer"]
    agent_msgs = [m for m in messages if m.get("sender_type") == "agent"]

    if not customer_msgs:
        return False, "customer_only"
    if not agent_msgs:
        return False, "agent_only"

    # Check for real customer questions (not just images/links/emojis)
    has_real_question = False
    for m in customer_msgs:
        content = (m.get("content") or "").strip()
        msg_type = m.get("message_type") or m.get("content_type") or ""
        if msg_type in ("image", "product_link"):
            continue
        if len(content) >= 2 and not _is_pure_emoji(content):
            has_real_question = True
            break

    if not has_real_question:
        return False, "no_real_question"

    # Check for system-only or welcome-only
    agent_contents = [(m.get("content") or "").strip() for m in agent_msgs]
    if all(_is_automated_greeting(c) for c in agent_contents if c):
        return False, "automated_greeting_only"

    # Check data quality
    quality = session.get("data_quality_status", "")
    if quality in ("history_truncated", "system_only", "empty", "duplicate"):
        return False, f"quality_{quality}"

    return True, "ok"


def _is_pure_emoji(text: str) -> bool:
    import re
    # Check if text contains any non-emoji, non-whitespace characters
    # CJK characters (U+4E00-U+9FFF) are NOT emoji
    has_real_text = False
    for c in text:
        cp = ord(c)
        # CJK Unified Ideographs
        if 0x4E00 <= cp <= 0x9FFF:
            has_real_text = True
            break
        # CJK Extension A
        if 0x3400 <= cp <= 0x4DBF:
            has_real_text = True
            break
        # ASCII letters and digits
        if c.isalpha() or c.isdigit():
            has_real_text = True
            break
    return not has_real_text


def _is_automated_greeting(text: str) -> bool:
    greetings = [
        "亲，欢迎光临", "您好，欢迎", "感谢您的咨询",
        "自动回复", "智能客服", "机器人回复",
    ]
    text_lower = text.lower()
    return any(g in text_lower for g in greetings)


# ---------- 主流程 ----------

def extract_candidates(
    source: str = "postgres",
    cutoff: str = CUTOFF_DEFAULT,
    output_dir: str = OUTPUT_DIR,
    limit: int = 0,
    dry_run: bool = False,
    report_only: bool = False,
    excel_dir: str = "",
    resume: bool = False,
) -> dict:
    from dateutil.parser import isoparse
    cutoff_dt = isoparse(cutoff)

    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Run audit
    stats = {
        "source": source,
        "cutoff": cutoff,
        "extraction_version": EXTRACTION_VERSION,
        "sessions_read": 0,
        "sessions_after_time_filter": 0,
        "sessions_after_quality_filter": 0,
        "sessions_after_dedup": 0,
        "candidates_generated": 0,
        "excluded_no_messages": 0,
        "excluded_customer_only": 0,
        "excluded_agent_only": 0,
        "excluded_no_real_question": 0,
        "excluded_automated_greeting": 0,
        "excluded_quality": 0,
        "scenario_distribution": {},
        "difficulty_distribution": {},
    }

    if report_only:
        if source == "postgres":
            from scripts.golden_set.qa_postgres_reader import run_source_audit
            audit = run_source_audit(cutoff_dt)
            # Save audit
            audit_path = os.path.join(output_dir, "source_audit.json")
            with open(audit_path, "w", encoding="utf-8") as f:
                json.dump(audit, f, ensure_ascii=False, indent=2)
            print(f"Source audit saved to {audit_path}")
            return audit

    # Step 2: Read sessions
    print(f"Reading sessions from {source}...")
    if source == "postgres":
        from scripts.golden_set.qa_postgres_reader import read_sessions, compute_session_hash
        sessions = read_sessions(cutoff=cutoff_dt, limit=limit)
    elif source == "excel":
        sessions = _read_excel_sessions(excel_dir, cutoff_dt, limit)
    else:
        raise ValueError(f"Unknown source: {source}")

    stats["sessions_read"] = len(sessions)
    print(f"Read {len(sessions)} sessions")

    if report_only:
        print(f"Report-only mode, not generating candidates.")
        return stats

    # Step 3: Quality filter
    valid_sessions = []
    exclude_reasons = Counter()
    for s in sessions:
        ok, reason = is_valid_session(s)
        if ok:
            valid_sessions.append(s)
        else:
            exclude_reasons[reason] += 1
            if "customer_only" in reason:
                stats["excluded_customer_only"] += 1
            elif "agent_only" in reason:
                stats["excluded_agent_only"] += 1
            elif "no_real_question" in reason:
                stats["excluded_no_real_question"] += 1
            elif "greeting" in reason:
                stats["excluded_automated_greeting"] += 1
            elif "quality" in reason:
                stats["excluded_quality"] += 1
            else:
                stats["excluded_no_messages"] += 1

    stats["sessions_after_quality_filter"] = len(valid_sessions)
    print(f"After quality filter: {len(valid_sessions)} (excluded: {dict(exclude_reasons)})")

    if dry_run:
        print("Dry-run mode, not generating candidates.")
        stats["dry_run"] = True
        return stats

    # Step 4: Sanitize
    from scripts.golden_set.real_data_sanitizer import sanitize_session, check_sensitive_data
    sanitized = []
    for s in valid_sessions:
        ss = sanitize_session(s)
        sanitized.append(ss)

    # Step 5: Dedup by content hash
    seen_hashes = set()
    deduped = []
    for s in sanitized:
        from scripts.golden_set.qa_postgres_reader import compute_session_hash
        h = compute_session_hash(s)
        if h not in seen_hashes:
            seen_hashes.add(h)
            deduped.append(s)
    stats["sessions_after_dedup"] = len(deduped)
    print(f"After dedup: {len(deduped)}")

    # Step 6: Semantic clustering (simple: by scenario)
    scenario_groups = Counter()
    difficulty_groups = Counter()
    candidates = []

    for i, s in enumerate(deduped):
        messages = s.get("messages", [])
        scenario = classify_scenario(messages)
        difficulty = classify_difficulty(s)

        scenario_groups[scenario] += 1
        difficulty_groups[difficulty] += 1

        # Extract customer message (last real question)
        customer_msg = _extract_customer_message(messages)

        # Extract product context
        product_ctx = _extract_product_context(s)

        candidate = {
            "case_id": f"REAL-CAND-{i+1:04d}",
            "source": {
                "system": "customer_service_qa",
                "type": source,
                "record_hash": compute_session_hash(s),
                "business_session_hash": "",
                "source_date_min": _get_min_time(s),
                "source_date_max": _get_max_time(s),
                "source_files": [],
                "cutoff_applied": cutoff,
            },
            "scenario": scenario,
            "difficulty": difficulty,
            "conversation_history": _build_conversation_history(messages),
            "customer_message": customer_msg,
            "product_context": product_ctx,
            "expected": {
                "allowed_intents": [],
                "required_tools": [],
                "forbidden_tools": [],
                "required_knowledge_entry_ids": [],
                "required_claims": [],
                "forbidden_claims": [],
                "risk_level": "",
                "need_human_review": False,
                "reply_requirements": [],
                "max_duration_ms": 0,
            },
            "evidence_review": {
                "status": "unverified",
                "knowledge_entries": [],
                "product_facts": [],
                "sop_entries": [],
                "jst_verification": None,
                "conflicts": [],
            },
            "annotation": {
                "status": "candidate",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            },
        }

        # Check sensitive data
        findings = check_sensitive_data(candidate)
        if findings:
            candidate["sanitization_findings"] = findings

        candidates.append(candidate)

    stats["candidates_generated"] = len(candidates)
    stats["scenario_distribution"] = dict(scenario_groups)
    stats["difficulty_distribution"] = dict(difficulty_groups)

    # Step 7: Save candidates
    candidates_path = os.path.join(output_dir, "candidates.jsonl")
    with open(candidates_path, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    stats_path = os.path.join(output_dir, "extraction_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\n=== Extraction Complete ===")
    print(f"Candidates: {len(candidates)}")
    print(f"Scenario distribution: {dict(scenario_groups)}")
    print(f"Difficulty distribution: {dict(difficulty_groups)}")
    print(f"Saved to: {candidates_path}")
    print(f"Stats: {stats_path}")

    return stats


def _extract_customer_message(messages: list[dict]) -> str:
    """Extract the last meaningful customer message."""
    for m in reversed(messages):
        if m.get("sender_type") != "customer":
            continue
        content = (m.get("content") or "").strip()
        msg_type = m.get("message_type") or m.get("content_type") or ""
        if msg_type in ("image",):
            continue
        if len(content) >= 2:
            return content
    return ""


def _extract_product_context(session: dict) -> dict:
    """Extract product context from session."""
    ctx = {
        "platform_product_id_masked": "",
        "platform_title": "",
        "internal_i_id": "",
        "sku_id": "",
        "canonical_product_name": "",
    }

    product_id = session.get("product_item_id", "")
    if product_id:
        ctx["platform_product_id_masked"] = f"<PRODUCT_ID_{hashlib.md5(str(product_id).encode()).hexdigest()[:6]}>"

    product_url = session.get("product_url", "")
    if product_url:
        import re
        m = re.search(r"id=(\d+)", product_url)
        if m:
            ctx["platform_product_id_masked"] = f"<PRODUCT_ID_{hashlib.md5(m.group(1).encode()).hexdigest()[:6]}>"

    return ctx


def _build_conversation_history(messages: list[dict]) -> list[dict]:
    """Build conversation history for the candidate."""
    history = []
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        msg_type = m.get("message_type") or m.get("content_type") or ""
        if msg_type == "image":
            content = "[图片]"
        elif msg_type == "product_link":
            content = "[商品链接]"
        history.append({
            "role": m.get("sender_type", "unknown"),
            "text": content,
            "time": m.get("sent_at", ""),
        })
    return history


def _get_min_time(session: dict) -> str:
    times = [
        m.get("sent_at", "") for m in session.get("messages", [])
        if m.get("sent_at")
    ]
    return min(times) if times else ""


def _get_max_time(session: dict) -> str:
    times = [
        m.get("sent_at", "") for m in session.get("messages", [])
        if m.get("sent_at")
    ]
    return max(times) if times else ""


def _read_excel_sessions(excel_dir: str, cutoff_dt: datetime, limit: int) -> list[dict]:
    """Fallback: read sessions from Excel files."""
    import openpyxl

    sessions = []
    if not os.path.isdir(excel_dir):
        print(f"Excel directory not found: {excel_dir}")
        return sessions

    # Find standard files (not 清洗版)
    files = sorted([
        f for f in os.listdir(excel_dir)
        if f.endswith(".xlsx") and "清洗" not in f
    ])

    from dateutil.parser import isoparse

    for fname in files:
        fpath = os.path.join(excel_dir, fname)
        print(f"  Reading {fname}...")

        try:
            wb = openpyxl.load_workbook(fpath, read_only=True, data_only=True)
        except Exception as e:
            print(f"    Failed to open: {e}")
            continue

        # Try standard sheet
        sheet_name = None
        for sn in wb.sheetnames:
            if "聊天记录" in sn and "清洗" not in sn:
                sheet_name = sn
                break
        if not sheet_name:
            sheet_name = wb.sheetnames[0]

        ws = wb[sheet_name]
        rows = list(ws.iter_rows(min_row=2, values_only=True))

        # Parse rows into messages
        current_session_msgs = []
        for row in rows:
            if not row or len(row) < 4:
                continue
            # Standard format: 抓取时间, 说话时间, 说话人类型, 说话人, 消息类型, 消息内容
            sent_at_raw = row[1] if len(row) > 1 else row[0]
            content = str(row[7] if len(row) > 7 else row[3] if len(row) > 3 else "")

            # Time filtering
            if not sent_at_raw:
                continue
            try:
                if isinstance(sent_at_raw, datetime):
                    sent_at = sent_at_raw
                else:
                    sent_at_str = str(sent_at_raw).strip()
                    sent_at = isoparse(sent_at_str)
            except Exception:
                continue

            if sent_at < cutoff_dt:
                continue

            sender_type = str(row[2] if len(row) > 2 else "").strip().lower()
            sender_name = str(row[3] if len(row) > 3 else "").strip()
            msg_type = str(row[4] if len(row) > 4 else "text").strip()

            current_session_msgs.append({
                "sender_type": sender_type,
                "sender_name": sender_name,
                "content": content,
                "message_type": msg_type,
                "sent_at": str(sent_at),
            })

        if current_session_msgs:
            sessions.append({
                "messages": current_session_msgs,
                "data_quality_status": "excel_import",
                "scoreable": True,
                "source_file": fname,
            })

        wb.close()

        if limit > 0 and len(sessions) >= limit:
            break

    return sessions


# ---------- CLI ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract real golden set candidates")
    parser.add_argument("--source", choices=["postgres", "excel"], default="postgres")
    parser.add_argument("--cutoff", default=CUTOFF_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--excel-dir", default="")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = extract_candidates(
        source=args.source,
        cutoff=args.cutoff,
        output_dir=args.output,
        limit=args.limit,
        dry_run=args.dry_run,
        report_only=args.report_only,
        excel_dir=args.excel_dir,
        resume=args.resume,
    )

    if isinstance(result, dict):
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
