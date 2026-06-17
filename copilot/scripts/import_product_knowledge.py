#!/usr/bin/env python
"""
商品知识导入工具 v3 - 从 product_cards.json 导入商品身份和事实到 knowledge_entries。

用法:
    python scripts/import_product_knowledge.py --dry-run --limit 5
    python scripts/import_product_knowledge.py --limit 5
    python scripts/import_product_knowledge.py --product-id YH117K01
    python scripts/import_product_knowledge.py --product-ids YH01K01,YH01K02,YH02K05 --type identity --dry-run
    python scripts/import_product_knowledge.py --type identity
    python scripts/import_product_knowledge.py --type facts

安全边界:
    允许: dry-run / 创建 draft / 更新未提交的 draft / 为已发布条目创建 revision draft
    禁止: 自动提交审核 / 自动发布 / 直接设置 ready / 创建生产 chunks / 修改人工知识

所有新条目默认 status=draft, index_status=pending。
发布必须通过管理后台执行 KnowledgeLifecycleService.approve()。
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BK_PREFIX = "BK"
IMPORT_TOOL_ID = "import_tool"

HIGH_RISK_FACT_TYPES = {"material", "waterproof", "age_range", "weight_capacity", "food_safe", "safety"}
UNCERTAIN_FACT_TYPES = {"weight", "color"}

SOURCE_TYPE_IDENTITY = "product_identity"
SOURCE_TYPE_FACTS = "product_facts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _content_hash(title: str, content: str) -> str:
    text = f"{title.strip()}|{content.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _make_business_key(product_id: str, sku_id: str, fact_type: str, scope: str) -> str:
    return f"{_BK_PREFIX}:{product_id}:{sku_id}:{fact_type}:{scope}"


def _parse_business_key(bk: str) -> dict:
    parts = bk.split(":")
    if len(parts) < 5 or parts[0] != _BK_PREFIX:
        return {}
    return {
        "product_id": parts[1],
        "sku_id": parts[2],
        "fact_type": parts[3],
        "scope": ":".join(parts[4:]),
    }


def _gen_batch_id() -> str:
    """生成本次导入的批次号。"""
    return f"product_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

def _extract_facts(csf: dict) -> list[dict]:
    facts = []
    if not csf:
        return facts

    mapping = {
        "material": ("材质", 0.8),
        "size": ("尺寸", 0.7),
        "weight": ("重量", 0.5),
        "weight_capacity": ("承重", 0.8),
        "age_range": ("适龄范围", 0.9),
        "waterproof": ("防水", 0.8),
        "installation": ("安装方式", 0.6),
        "package_contents": ("包装清单", 0.6),
        "color": ("颜色", 0.4),
        "usage": ("使用方式", 0.6),
        "maintenance": ("保养要求", 0.6),
        "warranty": ("质保", 0.6),
    }

    for key, (label, confidence) in mapping.items():
        val = csf.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = [str(v).strip() for v in val if v and str(v).strip()]
            if not val:
                continue
            val_str = "、".join(val)
        else:
            val_str = str(val).strip()
        if not val_str or val_str.lower() in ("none", "null", "无", "未知", "待确认"):
            continue
        facts.append({
            "fact_type": key,
            "label": label,
            "content": val_str,
            "confidence": confidence,
            "high_risk": key in HIGH_RISK_FACT_TYPES,
            "uncertain": key in UNCERTAIN_FACT_TYPES,
        })

    return facts


def _extract_sku_info(card: dict) -> tuple[str, list[dict]]:
    sku_summary = card.get("sku_summary", {}) or {}
    sku_list = sku_summary.get("sku_list", []) or []
    skus = []
    for s in sku_list:
        skus.append({
            "sku_id": _safe_str(s.get("sku_id")),
            "sku_name": _safe_str(s.get("sku_name")),
            "price": s.get("price"),
            "stock": s.get("stock"),
        })
    return _safe_str(sku_summary.get("sku_count", len(skus))), skus


# ---------------------------------------------------------------------------
# Card analysis
# ---------------------------------------------------------------------------

def analyze_card(card: dict) -> dict:
    i_id = _safe_str(card.get("i_id"))
    product_name = _safe_str(card.get("product_name"))
    category = _safe_str(card.get("category"))
    completeness = card.get("completeness_score", 0) or 0
    agent_level = _safe_str(card.get("agent_usable_level"))
    review_status = _safe_str(card.get("review_status"))
    csf = card.get("customer_service_facts", {}) or {}
    facts = _extract_facts(csf)
    sku_count, skus = _extract_sku_info(card)
    missing = card.get("missing_fields", []) or []
    warnings = card.get("data_quality_warnings", []) or []

    has_identity = bool(product_name and i_id)
    confirmed_facts = [f for f in facts if f["content"]]
    high_risk_facts = [f for f in confirmed_facts if f["high_risk"]]
    uncertain_facts = [f for f in confirmed_facts if f["uncertain"]]

    return {
        "i_id": i_id,
        "product_name": product_name,
        "category": category,
        "completeness": completeness,
        "agent_level": agent_level,
        "review_status": review_status,
        "sku_count": sku_count,
        "skus": skus,
        "facts": confirmed_facts,
        "high_risk_facts": high_risk_facts,
        "uncertain_facts": uncertain_facts,
        "missing_fields": missing,
        "warnings": warnings,
        "has_identity": has_identity,
        "has_facts": bool(confirmed_facts),
    }


# ---------------------------------------------------------------------------
# Entry data builders
# ---------------------------------------------------------------------------

def build_identity_entry(card: dict, analysis: dict) -> dict:
    i_id = analysis["i_id"]
    product_name = analysis["product_name"]
    category = analysis["category"]
    skus = analysis["skus"]

    title = f"商品身份：{product_name}"
    parts = [f"商品名称：{product_name}"]
    if i_id:
        parts.append(f"商品编号：{i_id}")
    if category:
        parts.append(f"类目：{category}")
    if skus:
        sku_lines = []
        for s in skus[:10]:
            line = f"  - {s['sku_name'] or s['sku_id']}"
            if s.get("price"):
                line += f" (价格: {s['price']})"
            sku_lines.append(line)
        parts.append(f"SKU ({len(skus)}款):\n" + "\n".join(sku_lines))
    content = "\n".join(parts)

    return {
        "source_type": SOURCE_TYPE_IDENTITY,
        "title": title,
        "content": content,
        "intent": "product_question",
        "category": "商品信息",
        "product_scope_json": json.dumps([product_name], ensure_ascii=False),
        "sku_scope_json": json.dumps([], ensure_ascii=False),
        "risk_level": "low",
        "auto_reply_allowed": True,
        "human_review_required": False,
        "source_confidence": 0.9,
        "content_hash": _content_hash(title, content),
        "business_key": _make_business_key(i_id, "", "identity", "product"),
        "product_id": i_id,
        "sku_id": "",
        "fact_type": "identity",
        "fact_scope": "product",
    }


def build_fact_entry(card: dict, analysis: dict, fact: dict) -> dict:
    product_name = analysis["product_name"]
    i_id = analysis["i_id"]

    title = f"{product_name} - {fact['label']}"
    parts = [
        f"商品：{product_name} (编号: {i_id})",
        f"参数类型：{fact['label']}",
        f"参数值：{fact['content']}",
    ]
    content = "\n".join(parts)

    is_high_risk = fact["high_risk"]
    is_uncertain = fact["uncertain"]

    if is_high_risk or is_uncertain:
        auto_reply = False
        human_review = True
        risk_level = "high" if is_high_risk else "medium"
    else:
        auto_reply = True
        human_review = False
        risk_level = "low"

    return {
        "source_type": SOURCE_TYPE_FACTS,
        "title": title,
        "content": content,
        "intent": "product_question",
        "category": "商品参数",
        "product_scope_json": json.dumps([product_name], ensure_ascii=False),
        "sku_scope_json": json.dumps([], ensure_ascii=False),
        "risk_level": risk_level,
        "auto_reply_allowed": auto_reply,
        "human_review_required": human_review,
        "source_confidence": fact["confidence"],
        "content_hash": _content_hash(title, content),
        "business_key": _make_business_key(i_id, "", fact["fact_type"], "product"),
        "product_id": i_id,
        "sku_id": "",
        "fact_type": fact["fact_type"],
        "fact_scope": "product",
    }


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def _find_by_business_key(db, business_key: str):
    """通过业务键查找当前工作版本。

    优先级:
    1. 已有的 draft/pending_review revision (未完成的修订)
    2. 当前 published 条目
    3. 其他非 archived 条目
    """
    from app.models.knowledge_base import KnowledgeEntry

    # 优先查找未完成的 revision (draft/pending_review，有 parent_entry_id)
    revision = (
        db.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.business_key == business_key,
            KnowledgeEntry.status.in_(["draft", "pending_review"]),
            KnowledgeEntry.parent_entry_id.isnot(None),
        )
        .order_by(KnowledgeEntry.version.desc())
        .first()
    )
    if revision:
        return revision

    # 查找当前 published 条目
    published = (
        db.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.business_key == business_key,
            KnowledgeEntry.status == "published",
        )
        .order_by(KnowledgeEntry.version.desc())
        .first()
    )
    if published:
        return published

    # 其他非 archived
    return (
        db.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.business_key == business_key,
            KnowledgeEntry.status != "archived",
        )
        .order_by(KnowledgeEntry.version.desc())
        .first()
    )


def _is_managed_by_tool(entry) -> bool:
    """检查条目是否由本导入工具管理（非人工创建）。"""
    return entry.created_by == IMPORT_TOOL_ID


def _plan_entry(db, entry_data: dict, dry_run: bool, batch_id: str = "") -> dict:
    """Plan or execute an entry creation/update.

    安全规则:
    - 只能创建 draft
    - 只能更新本工具创建且状态为 draft/rejected 的条目
    - pending_review 和 published 不可直接修改
    - published 只能通过 create_revision 创建新 draft
    - 人工创建的条目不可覆盖
    """
    from app.models.knowledge_base import KnowledgeEntry

    business_key = entry_data.get("business_key", "")
    content_hash = entry_data.get("content_hash", "")
    source_type = entry_data.get("source_type", "")
    fact_type = entry_data.get("fact_type", "")
    product_id = entry_data.get("product_id", "")
    sku_id = entry_data.get("sku_id", "")
    fact_scope = entry_data.get("fact_scope", "")

    existing = _find_by_business_key(db, business_key)

    if existing:
        # 内容未变化 -> 跳过
        if existing.content_hash == content_hash:
            return {
                "action": "would_skip_unchanged" if dry_run else "skipped",
                "entry_id": existing.id,
                "business_key": business_key,
                "reason": "content unchanged",
                "existing_status": existing.status,
            }

        # published 条目: 创建 revision draft
        if existing.status == "published":
            if dry_run:
                return {
                    "action": "would_create_revision",
                    "entry_id": existing.id,
                    "business_key": business_key,
                    "reason": "content changed on published entry",
                    "existing_status": existing.status,
                }

            from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
            result = KnowledgeLifecycleService.create_revision(existing.id, user=IMPORT_TOOL_ID)
            if result.get("error"):
                return {"action": "error", "business_key": business_key,
                        "reason": f"create_revision failed: {result['error']}"}

            revision_id = result.get("revision_entry_id")

            # 更新 revision 内容和业务键
            from app.db import SessionLocal
            rev_db = SessionLocal()
            try:
                rev = rev_db.query(KnowledgeEntry).get(revision_id)
                if rev:
                    rev.title = entry_data["title"].strip()
                    rev.content = entry_data["content"].strip()
                    rev.content_hash = content_hash
                    rev.source_confidence = entry_data.get("source_confidence", 0.5)
                    rev.risk_level = entry_data.get("risk_level", "low")
                    rev.auto_reply_allowed = entry_data.get("auto_reply_allowed", True)
                    rev.human_review_required = entry_data.get("human_review_required", False)
                    rev.business_key = business_key
                    rev.product_id = product_id
                    rev.sku_id = sku_id
                    rev.fact_type = fact_type
                    rev.fact_scope = fact_scope
                    rev.import_batch_id = batch_id
                    rev.updated_by = IMPORT_TOOL_ID
                    rev.updated_at = datetime.utcnow()
                    rev_db.commit()
            except Exception:
                rev_db.rollback()
                raise
            finally:
                rev_db.close()

            return {
                "action": "revision_created",
                "entry_id": revision_id,
                "business_key": business_key,
                "reason": "content changed, revision draft created",
                "parent_id": existing.id,
            }

        # pending_review: 不可修改
        if existing.status == "pending_review":
            return {
                "action": "conflict",
                "entry_id": existing.id,
                "business_key": business_key,
                "reason": "entry is pending_review, cannot modify",
            }

        # draft/rejected: 只允许本工具管理的条目更新
        if existing.status in ("draft", "rejected"):
            if not _is_managed_by_tool(existing):
                return {
                    "action": "conflict",
                    "entry_id": existing.id,
                    "business_key": business_key,
                    "reason": "entry was created manually, import tool cannot modify",
                }

            if dry_run:
                return {
                    "action": "would_update_draft",
                    "entry_id": existing.id,
                    "business_key": business_key,
                    "reason": "content changed, would update draft",
                    "existing_status": existing.status,
                }

            # 更新 draft 内容
            existing.title = entry_data["title"].strip()
            existing.content = entry_data["content"].strip()
            existing.content_hash = content_hash
            existing.source_confidence = entry_data.get("source_confidence", 0.5)
            existing.risk_level = entry_data.get("risk_level", "low")
            existing.auto_reply_allowed = entry_data.get("auto_reply_allowed", True)
            existing.human_review_required = entry_data.get("human_review_required", False)
            existing.business_key = business_key
            existing.product_id = product_id
            existing.sku_id = sku_id
            existing.fact_type = fact_type
            existing.fact_scope = fact_scope
            existing.import_batch_id = batch_id
            existing.updated_by = IMPORT_TOOL_ID
            existing.updated_at = datetime.utcnow()
            db.flush()

            return {
                "action": "updated_draft",
                "entry_id": existing.id,
                "business_key": business_key,
                "reason": "content changed, draft updated",
            }

    # 新条目
    if dry_run:
        return {
            "action": "would_create",
            "business_key": business_key,
            "reason": "new entry",
        }

    entry = KnowledgeEntry(
        source_type=source_type,
        title=entry_data["title"].strip(),
        content=entry_data["content"].strip(),
        intent=entry_data.get("intent", "general"),
        category=entry_data.get("category", ""),
        risk_level=entry_data.get("risk_level", "low"),
        auto_reply_allowed=entry_data.get("auto_reply_allowed", True),
        human_review_required=entry_data.get("human_review_required", False),
        source_confidence=entry_data.get("source_confidence", 0.5),
        status="draft",
        version=1,
        created_by=IMPORT_TOOL_ID,
        updated_by=IMPORT_TOOL_ID,
        import_batch_id=batch_id,
        content_hash=content_hash,
        business_key=business_key,
        product_id=product_id,
        sku_id=sku_id,
        fact_type=fact_type,
        fact_scope=fact_scope,
    )
    entry.set_product_scope(json.loads(entry_data.get("product_scope_json", "[]")))
    entry.set_sku_scope(json.loads(entry_data.get("sku_scope_json", "[]")))

    db.add(entry)
    db.flush()

    return {
        "action": "created",
        "entry_id": entry.id,
        "business_key": business_key,
        "reason": "new entry",
    }


# ---------------------------------------------------------------------------
# Main import
# ---------------------------------------------------------------------------

def run_import(args):
    """Execute the import pipeline. Returns stats dict."""
    from app.main import create_app
    app = create_app()
    import app.main as m
    repo = m._product_knowledge_repo

    if not repo or not repo._cards:
        print("ERROR: No product knowledge cards loaded.")
        return {"error": "no cards"}

    cards = repo._cards
    print(f"Loaded {len(cards)} product cards.")

    # 合并 --product-id 和 --product-ids，去重去空格
    requested_ids = set()
    if args.product_id:
        requested_ids.add(args.product_id.strip())
    if args.product_ids:
        for pid in args.product_ids.split(","):
            pid = pid.strip()
            if pid:
                requested_ids.add(pid)

    if requested_ids:
        requested_ids.discard("")
        print(f"Requested product IDs: {sorted(requested_ids)}")
        all_i_ids = {_safe_str(c.get("i_id")) for c in cards}
        matched = requested_ids & all_i_ids
        missing = requested_ids - all_i_ids
        if matched:
            print(f"Matched product IDs: {sorted(matched)}")
        if missing:
            print(f"Missing product IDs: {sorted(missing)}")
        if not matched:
            print(f"ERROR: None of the requested product IDs were found in product cards.")
            return {"error": "no matching product IDs", "missing": sorted(missing)}
        cards = [c for c in cards if _safe_str(c.get("i_id")) in matched]
        print(f"Filtered to {len(cards)} card(s).")

    analyses = []
    for card in cards:
        a = analyze_card(card)
        if a["has_identity"]:
            analyses.append((card, a))

    print(f"Analyzable cards: {len(analyses)}")
    analyses.sort(key=lambda x: x[1]["completeness"], reverse=True)

    if args.limit:
        analyses = analyses[:args.limit]
        print(f"Limited to top {args.limit} cards.")

    import_plan = []
    for card, analysis in analyses:
        if args.type in ("identity", "all"):
            import_plan.append(("product_identity", build_identity_entry(card, analysis), analysis))
        if args.type in ("facts", "all") and analysis["has_facts"]:
            for fact in analysis["facts"]:
                import_plan.append(("product_facts", build_fact_entry(card, analysis, fact), analysis))

    print(f"Import plan: {len(import_plan)} entries")
    type_counts = {}
    for t, _, _ in import_plan:
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    if args.dry_run:
        return _dry_run_report(import_plan)

    return _execute_import(import_plan)


def _dry_run_report(import_plan: list) -> dict:
    from app.db import SessionLocal
    from app.models.knowledge_base import KnowledgeEntry

    batch_id = _gen_batch_id()
    db = SessionLocal()
    try:
        stats = {
            "batch_id": batch_id,
            "would_create": 0,
            "would_update_draft": 0,
            "would_skip_unchanged": 0,
            "would_create_revision": 0,
            "would_require_human_review": 0,
            "conflicts": 0,
            "product_count": 0,
            "entry_count": len(import_plan),
        }
        details = []
        products_seen = set()

        for t, data, analysis in import_plan:
            plan = _plan_entry(db, data, dry_run=True, batch_id=batch_id)
            action = plan["action"]

            if action == "would_create":
                stats["would_create"] += 1
            elif action == "would_update_draft":
                stats["would_update_draft"] += 1
            elif action == "would_skip_unchanged":
                stats["would_skip_unchanged"] += 1
            elif action == "would_create_revision":
                stats["would_create_revision"] += 1
            elif action == "conflict":
                stats["conflicts"] += 1

            if data.get("human_review_required"):
                stats["would_require_human_review"] += 1

            products_seen.add(analysis["i_id"])

            details.append({
                "batch_id": batch_id,
                "product_id": analysis["i_id"],
                "sku_id": data.get("sku_id", ""),
                "fact_type": data.get("fact_type", t),
                "fact_scope": data.get("fact_scope", "product"),
                "business_key": data.get("business_key", ""),
                "action": action,
                "risk_level": data.get("risk_level", "low"),
                "source_confidence": data.get("source_confidence", 0.5),
                "auto_reply_allowed": data.get("auto_reply_allowed", True),
                "human_review_required": data.get("human_review_required", False),
                "target_status": "draft",
                "target_index_status": "pending",
                "existing_entry_id": plan.get("entry_id"),
                "parent_entry_id": plan.get("parent_id"),
                "reason": plan.get("reason", ""),
                "source": "official_product_data",
            })

        stats["product_count"] = len(products_seen)

        print()
        print("=" * 70)
        print("DRY RUN - no changes made to database")
        print("=" * 70)
        print(f"\nBatch ID: {batch_id}")
        print(f"\nSummary:")
        print(f"  Products: {stats['product_count']}")
        print(f"  Total entries: {stats['entry_count']}")
        print(f"  Would create (new): {stats['would_create']}")
        print(f"  Would update draft: {stats['would_update_draft']}")
        print(f"  Would skip (unchanged): {stats['would_skip_unchanged']}")
        print(f"  Would create revision: {stats['would_create_revision']}")
        print(f"  Conflicts: {stats['conflicts']}")
        print(f"  Requires human review: {stats['would_require_human_review']}")

        print(f"\nSample entries (first 15):")
        for i, d in enumerate(details[:15]):
            print(f"\n  [{i+1}] product={d['product_id']} fact={d['fact_type']} scope={d['fact_scope']}")
            print(f"      business_key: {d['business_key']}")
            print(f"      batch_id: {d['batch_id']}")
            print(f"      action: {d['action']}")
            print(f"      risk: {d['risk_level']} confidence: {d['source_confidence']}")
            print(f"      auto_reply: {d['auto_reply_allowed']} human_review: {d['human_review_required']}")
            print(f"      target: {d['target_status']} / {d['target_index_status']}")
            print(f"      source: {d['source']}")
            if d.get("existing_entry_id"):
                print(f"      existing_entry_id: {d['existing_entry_id']}")
            if d.get("parent_entry_id"):
                print(f"      parent_entry_id: {d['parent_entry_id']}")
            if d.get("reason"):
                print(f"      reason: {d['reason']}")

        prod_count = db.query(KnowledgeEntry).count()
        prod_ready = db.query(KnowledgeEntry).filter_by(
            status="published", index_status="ready"
        ).count()
        print(f"\nProduction DB (unchanged):")
        print(f"  entries: {prod_count}")
        print(f"  published+ready: {prod_ready}")

        return stats
    finally:
        db.close()


def _execute_import(import_plan: list) -> dict:
    from app.db import SessionLocal
    from app.models.knowledge_base import KnowledgeEntry

    batch_id = _gen_batch_id()
    print(f"Batch ID: {batch_id}")

    products = {}
    for t, data, analysis in import_plan:
        pid = analysis["i_id"]
        if pid not in products:
            products[pid] = []
        products[pid].append((t, data, analysis))

    stats = {
        "batch_id": batch_id,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "revisions_created": 0,
        "conflicts": 0,
        "failed_products": 0,
        "rolled_back": 0,
        "errors": [],
    }

    for pid, entries in products.items():
        db = SessionLocal()
        try:
            for t, data, analysis in entries:
                plan = _plan_entry(db, data, dry_run=False, batch_id=batch_id)
                action = plan["action"]

                if action == "skipped":
                    stats["skipped"] += 1
                elif action == "created":
                    stats["created"] += 1
                elif action == "updated_draft":
                    stats["updated"] += 1
                elif action == "revision_created":
                    stats["revisions_created"] += 1
                elif action == "conflict":
                    stats["conflicts"] += 1
                elif action == "error":
                    stats["errors"].append(f"{pid}: {plan.get('reason', 'unknown')}")

            db.commit()
        except Exception as e:
            db.rollback()
            stats["failed_products"] += 1
            stats["rolled_back"] += len(entries)
            stats["errors"].append(f"{pid}: {e}")
        finally:
            db.close()

    print(f"\nImport complete:")
    print(f"  Created: {stats['created']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Skipped (unchanged): {stats['skipped']}")
    print(f"  Revisions created: {stats['revisions_created']}")
    print(f"  Conflicts: {stats['conflicts']}")
    print(f"  Failed products: {stats['failed_products']}")
    print(f"  Rolled back entries: {stats['rolled_back']}")
    if stats["errors"]:
        print(f"  Errors ({len(stats['errors'])}):")
        for e in stats["errors"][:10]:
            print(f"    - {e}")

    db = SessionLocal()
    try:
        total = db.query(KnowledgeEntry).count()
        ready = db.query(KnowledgeEntry).filter_by(
            status="published", index_status="ready"
        ).count()
        print(f"\nProduction DB after import:")
        print(f"  entries: {total}")
        print(f"  published+ready: {ready}")
    finally:
        db.close()

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="商品知识导入工具 v3")
    parser.add_argument("--dry-run", action="store_true",
                        help="只分析不写入数据库")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制导入商品数量")
    parser.add_argument("--product-id", type=str, default="",
                        help="只导入指定商品（单个编号）")
    parser.add_argument("--product-ids", type=str, default="",
                        help="导入多个商品编号，逗号分隔，如 YH01K01,YH01K02,YH02K05")
    parser.add_argument("--type", choices=["identity", "facts", "all"], default="all",
                        help="导入类型: identity=身份, facts=事实, all=全部")
    args = parser.parse_args()

    if not args.dry_run:
        print("Mode: create draft only (no auto-publish, no auto-review)")

    result = run_import(args)

    if isinstance(result, dict):
        if result.get("error") or result.get("failed_products", 0) > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
