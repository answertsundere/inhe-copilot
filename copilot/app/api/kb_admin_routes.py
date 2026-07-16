"""
知识库管理后台 API 路由
权限角色：operator / supervisor / admin
"""

import hashlib
import json
from datetime import datetime

from flask import Blueprint, request, jsonify
from sqlalchemy import func, Integer
from app.api.admin_auth import current_role, current_user_name, has_any_role

kb_admin_bp = Blueprint("kb_admin", __name__, url_prefix="/api/kb")


# ============ 权限检查 ============

def _get_user_info():
    return current_role(), current_user_name()


def _require_supervisor(role):
    return has_any_role("supervisor", "admin")


# ============ Dashboard ============

@kb_admin_bp.route("/dashboard/stats", methods=["GET"])
def api_dashboard_stats():
    """聚合统计：各表计数 + QA 分布 + 审核待办 + 最近变更"""
    from app.db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        conn = db.connection()

        def _count(table_name):
            row = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
            return row[0] if row else 0

        total_products = _count("kb_product")
        total_qa = _count("kb_qa")
        total_sop = _count("kb_sop")
        total_cases = _count("kb_case")
        total_traces = _count("kb_agent_trace")
        total_feedback = _count("kb_feedback")

        # QA by status
        qa_by_status = {}
        rows = conn.execute(text("SELECT status, COUNT(*) FROM kb_qa GROUP BY status")).fetchall()
        for r in rows:
            qa_by_status[r[0]] = r[1]

        # QA by risk level
        qa_by_risk_level = {}
        rows = conn.execute(text("SELECT risk_level, COUNT(*) FROM kb_qa GROUP BY risk_level")).fetchall()
        for r in rows:
            qa_by_risk_level[r[0]] = r[1]

        # Review pending count
        row = conn.execute(
            text("SELECT COUNT(*) FROM kb_review_task WHERE status = 'pending'")
        ).fetchone()
        review_pending_count = row[0] if row else 0

        # Review stats by status
        review_stats = {}
        rows = conn.execute(
            text("SELECT status, COUNT(*) FROM kb_review_task GROUP BY status")
        ).fetchall()
        for r in rows:
            review_stats[r[0]] = r[1]

        # Recent changes
        recent_rows = conn.execute(
            text(
                "SELECT id, target_type, target_id, target_title, action, "
                "performed_by, created_at "
                "FROM kb_change_log ORDER BY created_at DESC LIMIT 10"
            )
        ).fetchall()
        recent_changes = [
            {
                "id": r[0],
                "target_type": r[1],
                "target_id": r[2],
                "target_title": r[3],
                "action": r[4],
                "performed_by": r[5],
                "created_at": str(r[6]) if r[6] else None,
            }
            for r in recent_rows
        ]

        return jsonify({
            "total_products": total_products,
            "total_qa": total_qa,
            "total_sop": total_sop,
            "total_cases": total_cases,
            "total_traces": total_traces,
            "total_feedback": total_feedback,
            "qa_by_status": qa_by_status,
            "qa_by_risk_level": qa_by_risk_level,
            "review_pending_count": review_pending_count,
            "review_stats": review_stats,
            "recent_changes": recent_changes,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ============ Products ============

# 商品主图优先级（只读，不写数据库）
_COVER_PRIORITY_ASSET_TYPES = (
    ("sku_image", "appearance_image"),
    ("detail_image", "appearance_image"),
    ("size_image", "size_image"),
    ("install_image", "install_image"),
    ("install_video", "install_video"),
)


def _select_product_cover_media(assets):
    """从素材列表中选择最佳封面图。

    优先级：
    1. 已审核可用外观/实物图（sku_image / detail_image）
    2. 已审核可用尺寸图（size_image）
    3. 已审核可用安装/场景图（install_image / install_video）
    4. 任意已审核且 usable_for_agent 的图片
    5. 任意状态可用的图片/视频（非 rejected）

    返回 (asset_url, cover_source) 或 (None, None)
    """
    if not assets:
        return None, None

    def _is_approved_usable(a):
        return a.status == "approved" and a.usable_for_agent and a.asset_url

    # 优先级 1-3：按类型匹配已审核可用
    for asset_type, source_label in _COVER_PRIORITY_ASSET_TYPES:
        for a in assets:
            if _is_approved_usable(a) and a.asset_type == asset_type:
                return a.asset_url, source_label

    # 优先级 4：任意已审核可用的图片（排除视频）
    for a in assets:
        if _is_approved_usable(a) and a.asset_type != "install_video":
            return a.asset_url, a.asset_type

    # 优先级 5：任意状态可用（非 rejected）
    for asset_type, source_label in _COVER_PRIORITY_ASSET_TYPES:
        for a in assets:
            if a.status != "rejected" and a.asset_url and a.asset_type == asset_type:
                return a.asset_url, source_label

    # 兜底：任意非 rejected 且有 URL
    for a in assets:
        if a.status != "rejected" and a.asset_url:
            return a.asset_url, a.asset_type

    return None, None


def _attach_product_cover_fields(products, db):
    """批量为商品附加封面图字段。只读，不写数据库。

    通过 product_id 与 i_id（非空时）批量匹配素材，避免 N+1。
    """
    if not products:
        return

    from app.models.kb_tables import KBMediaAsset
    from sqlalchemy import or_

    product_ids = [p["id"] for p in products]
    i_ids = [p.get("i_id") for p in products if p.get("i_id")]

    filters = []
    if product_ids:
        filters.append(KBMediaAsset.product_id.in_(product_ids))
    if i_ids:
        # 仅匹配非空 i_id，避免空字符串误匹配所有空 i_id 素材
        non_empty_i_ids = [i for i in i_ids if str(i).strip()]
        if non_empty_i_ids:
            filters.append(KBMediaAsset.i_id.in_(non_empty_i_ids))

    if not filters:
        for p in products:
            p["cover_image_url"] = None
            p["cover_image_source"] = None
            p["media_count"] = 0
        return

    assets = db.query(KBMediaAsset).filter(or_(*filters)).all()

    # 按商品分组；同一素材可能通过 product_id 或 i_id 匹配，需去重
    product_assets = {pid: {} for pid in product_ids}
    i_id_to_pid = {p.get("i_id"): p["id"] for p in products if p.get("i_id")}

    for a in assets:
        if a.product_id in product_assets:
            product_assets[a.product_id][a.id] = a
        if a.i_id and a.i_id in i_id_to_pid:
            product_assets[i_id_to_pid[a.i_id]][a.id] = a

    for p in products:
        pas = list(product_assets.get(p["id"], {}).values())
        cover_url, cover_source = _select_product_cover_media(pas)
        p["cover_image_url"] = cover_url
        p["cover_image_source"] = cover_source
        p["media_count"] = len(pas)


@kb_admin_bp.route("/products", methods=["GET"])
def api_list_products():
    """商品列表，支持过滤和分页"""
    from app.repositories.kb_product_repository import KBProductRepository
    try:
        category_l1 = request.args.get("category_l1", "")
        category_l2 = request.args.get("category_l2", "")
        category_l3 = request.args.get("category_l3", "")
        search = request.args.get("search", "")
        status = request.args.get("status", "")
        agent_usable = request.args.get("agent_usable", "")
        has_qa = request.args.get("has_qa", "")
        missing_field = request.args.get("missing_field", "")
        high_risk = request.args.get("high_risk", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        items, total = KBProductRepository.list_entries(
            category_l1=category_l1,
            category_l2=category_l2,
            category_l3=category_l3,
            search=search,
            status=status,
            agent_usable=agent_usable,
            has_qa=has_qa,
            missing_field=missing_field,
            high_risk=high_risk,
            limit=limit,
            offset=offset,
        )
        # Batch-fetch QA counts for all products on this page (2 queries instead of 2*N)
        from app.db import SessionLocal
        from app.models.kb_tables import KBQA
        _db = SessionLocal()
        try:
            product_ids = [p.id for p in items]
            qa_counts = {}
            high_risk_counts = {}
            if product_ids:
                rows = _db.query(
                    KBQA.product_id, func.count(KBQA.id),
                ).filter(KBQA.product_id.in_(product_ids)).group_by(KBQA.product_id).all()
                qa_counts = {r[0]: r[1] for r in rows}

                hr_rows = _db.query(
                    KBQA.product_id, func.count(KBQA.id),
                ).filter(
                    KBQA.product_id.in_(product_ids),
                    KBQA.risk_level.in_(["high", "critical"]),
                ).group_by(KBQA.product_id).all()
                high_risk_counts = {r[0]: r[1] for r in hr_rows}

            result = []
            for p in items:
                d = p.to_dict()
                qa_count = qa_counts.get(p.id, 0)
                high_risk_count = high_risk_counts.get(p.id, 0)
                d["qa_count"] = qa_count
                d["high_risk_qa_count"] = high_risk_count
                d["can_agent_use"] = (
                    p.status == "published"
                    and p.completeness_score >= 60
                    and high_risk_count == 0
                )
                result.append(d)

            # 批量附加封面图字段（只读）
            _attach_product_cover_fields(result, _db)
        finally:
            _db.close()
        return jsonify({
            "items": result,
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/products/categories", methods=["GET"])
def api_product_categories():
    """返回品类树，从 distinct category_l1/2/3 构建"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct
    from sqlalchemy import distinct
    db = SessionLocal()
    try:
        rows = db.query(
            KBProduct.category_l1,
            KBProduct.category_l2,
            KBProduct.category_l3,
        ).distinct().all()

        tree = {}
        for l1, l2, l3 in rows:
            if not l1:
                continue
            if l1 not in tree:
                tree[l1] = {}
            if not l2:
                continue
            if l2 not in tree[l1]:
                tree[l1][l2] = set()
            if l3:
                tree[l1][l2].add(l3)

        result = []
        for l1, l2_map in tree.items():
            l1_node = {"label": l1, "children": []}
            for l2, l3_set in l2_map.items():
                l2_node = {"label": l2, "children": [{"label": l3} for l3 in sorted(l3_set)]}
                l1_node["children"].append(l2_node)
            result.append(l1_node)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/summary", methods=["GET"])
def api_product_summary():
    """商品统计总览"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    db = SessionLocal()
    try:
        total = db.query(func.count(KBProduct.id)).scalar()
        published = db.query(func.count(KBProduct.id)).filter(KBProduct.status == "published").scalar()
        draft = db.query(func.count(KBProduct.id)).filter(KBProduct.status == "draft").scalar()
        avg_c = db.query(func.avg(KBProduct.completeness_score)).scalar()
        low_c = db.query(func.count(KBProduct.id)).filter(KBProduct.completeness_score < 60).scalar()
        review_pending = db.query(func.count(KBProduct.id)).filter(KBProduct.status == "pending_review").scalar()

        # 商品关联的高风险问答数
        high_risk_qa_products = db.query(func.count(func.distinct(KBQA.product_id))).filter(
            KBQA.risk_level.in_(["high", "critical"]),
            KBQA.product_id.isnot(None),
        ).scalar()

        # 无关联问答的商品数
        products_with_qa = db.query(func.count(func.distinct(KBQA.product_id))).filter(
            KBQA.product_id.isnot(None)
        ).scalar()
        no_qa_count = total - products_with_qa if total and products_with_qa else 0

        # Agent 可用商品数
        agent_usable = db.query(func.count(KBProduct.id)).filter(
            KBProduct.status == "published",
            KBProduct.completeness_score >= 60,
        ).scalar()
        # 排除有高风险QA的
        products_with_high_risk = db.query(func.count(func.distinct(KBQA.product_id))).filter(
            KBQA.risk_level.in_(["high", "critical"]),
            KBQA.product_id.isnot(None),
        ).scalar()
        agent_usable = max(0, agent_usable - min(agent_usable, products_with_high_risk))
        not_agent_usable = total - agent_usable

        # 健康评分：完整度40% + 已发布比例20% + 有关联问答比例20% + 无高风险配置20%
        completeness_score = round(float(avg_c or 0), 1)
        published_ratio = round(published / max(total, 1) * 100, 1)
        qa_ratio = round((total - no_qa_count) / max(total, 1) * 100, 1)
        high_risk_ratio = round((total - high_risk_qa_products) / max(total, 1) * 100, 1)
        health_score = round(completeness_score * 0.4 + published_ratio * 0.2 + qa_ratio * 0.2 + high_risk_ratio * 0.2, 1)

        return jsonify({
            "total": total,
            "published": published,
            "draft": draft,
            "avg_completeness": completeness_score,
            "incomplete_count": low_c,
            "review_pending": review_pending,
            "high_risk_product_count": high_risk_qa_products,
            "no_qa_count": no_qa_count,
            "agent_usable": agent_usable,
            "not_agent_usable": not_agent_usable,
            "health_score": health_score,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/category-tree", methods=["GET"])
def api_product_category_tree():
    """类目树，每个节点带商品数、待补全数、关联问答数、高风险数"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    db = SessionLocal()
    try:
        rows = db.query(
            KBProduct.category_l1, KBProduct.category_l2, KBProduct.category_l3,
            func.count(KBProduct.id),
            func.sum(func.cast(KBProduct.completeness_score < 60, db.bind.dialect.name == 'sqlite' and Integer or Integer)),
        ).group_by(KBProduct.category_l1, KBProduct.category_l2, KBProduct.category_l3).all()

        # QA counts per category
        qa_rows = db.query(
            KBQA.category_l1, KBQA.category_l2, KBQA.category_l3,
            func.count(KBQA.id),
            func.sum(func.cast(KBQA.risk_level.in_(["high", "critical"]), Integer)),
        ).group_by(KBQA.category_l1, KBQA.category_l2, KBQA.category_l3).all()

        # Build QA lookup
        qa_map = {}
        for ql1, ql2, ql3, qcnt, hcnt in qa_rows:
            qa_map[(ql1 or "", ql2 or "", ql3 or "")] = (qcnt, int(hcnt or 0))

        # Build tree
        tree = {}
        for l1, l2, l3, pcount, low_count in rows:
            if not l1:
                continue
            if l1 not in tree:
                tree[l1] = {"count": 0, "incomplete": 0, "qa": 0, "high_risk": 0, "children": {}}
            tree[l1]["count"] += pcount
            tree[l1]["incomplete"] += int(low_count or 0)
            k2 = l2 or ""
            if k2 not in tree[l1]["children"]:
                tree[l1]["children"][k2] = {"count": 0, "incomplete": 0, "qa": 0, "high_risk": 0, "children": {}}
            tree[l1]["children"][k2]["count"] += pcount
            tree[l1]["children"][k2]["incomplete"] += int(low_count or 0)
            # Merge QA stats
            for key in [(l1, l2 or "", l3 or ""), (l1, l2 or "", ""), (l1, "", "")]:
                if key in qa_map:
                    tree[l1]["qa"] += 0  # handled at leaf level
                    if key[1] == (l2 or "") and key[2] == (l3 or ""):
                        tree[l1]["children"][k2]["qa"] += qa_map[key][0]
                        tree[l1]["children"][k2]["high_risk"] += qa_map[key][1]

            k3 = l3 or ""
            if k3:
                if k3 not in tree[l1]["children"][k2]["children"]:
                    tree[l1]["children"][k2]["children"][k3] = {"count": 0, "incomplete": 0, "qa": 0, "high_risk": 0}
                tree[l1]["children"][k2]["children"][k3]["count"] += pcount
                tree[l1]["children"][k2]["children"][k3]["incomplete"] += int(low_count or 0)
                key3 = (l1, l2 or "", l3 or "")
                if key3 in qa_map:
                    tree[l1]["children"][k2]["children"][k3]["qa"] = qa_map[key3][0]
                    tree[l1]["children"][k2]["children"][k3]["high_risk"] = qa_map[key3][1]

        # Roll up QA counts
        for l1, n1 in tree.items():
            total_qa = 0
            total_hr = 0
            for l2, n2 in n1["children"].items():
                l2_qa = 0
                l2_hr = 0
                for l3, n3 in n2["children"].items():
                    l2_qa += n3.get("qa", 0)
                    l2_hr += n3.get("high_risk", 0)
                n2["qa"] = max(n2.get("qa", 0), l2_qa)
                n2["high_risk"] = max(n2.get("high_risk", 0), l2_hr)
                total_qa += n2["qa"]
                total_hr += n2["high_risk"]
            n1["qa"] = total_qa
            n1["high_risk"] = total_hr

        # Convert to list
        result = []
        for l1, n1 in sorted(tree.items()):
            l1_node = {"label": l1, "count": n1["count"], "incomplete": n1["incomplete"],
                       "qa": n1["qa"], "high_risk": n1["high_risk"], "children": []}
            for l2, n2 in sorted(n1["children"].items()):
                if not l2:
                    continue
                l2_node = {"label": l2, "count": n2["count"], "incomplete": n2["incomplete"],
                           "qa": n2["qa"], "high_risk": n2["high_risk"], "children": []}
                for l3, n3 in sorted(n2["children"].items()):
                    if not l3:
                        continue
                    l2_node["children"].append({"label": l3, "count": n3["count"],
                                                "incomplete": n3["incomplete"],
                                                "qa": n3.get("qa", 0),
                                                "high_risk": n3.get("high_risk", 0)})
                l1_node["children"].append(l2_node)
            result.append(l1_node)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>", methods=["GET"])
def api_get_product(product_id):
    """单个商品详情"""
    from app.repositories.kb_product_repository import KBProductRepository
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        product = KBProductRepository.get_by_id(product_id)
        if not product:
            return jsonify({"error": "Not found"}), 404
        data = product.to_dict(detail=True)
        _attach_product_cover_fields([data], db)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products", methods=["POST"])
def api_create_product():
    """创建商品"""
    from app.repositories.kb_product_repository import KBProductRepository
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        data["created_by"] = name

        # Extract JSON fields into setter-friendly form
        kwargs = _extract_product_kwargs(data)

        product = KBProductRepository.create(**kwargs)
        return jsonify(product.to_dict(detail=True)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/products/<int:product_id>", methods=["PUT"])
def api_update_product(product_id):
    """更新商品"""
    from app.repositories.kb_product_repository import KBProductRepository
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        product = KBProductRepository.update(product_id, data, updated_by=name)
        if not product:
            return jsonify({"error": "Not found"}), 404
        return jsonify(product.to_dict(detail=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/products/<int:product_id>/qa", methods=["GET"])
def api_product_qa(product_id):
    """获取商品关联的 QA 条目（含同类目通用问答）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    from sqlalchemy import or_, and_
    db = SessionLocal()
    try:
        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        conds = [KBQA.product_id == product_id]
        if product and (product.category_l1 or product.category_l2 or product.category_l3):
            cat_conds = [KBQA.product_id.is_(None)]
            if product.category_l1:
                cat_conds.append(KBQA.category_l1 == product.category_l1)
            if product.category_l2:
                cat_conds.append(KBQA.category_l2 == product.category_l2)
            if product.category_l3:
                cat_conds.append(KBQA.category_l3 == product.category_l3)
            conds.append(and_(*cat_conds))
        items = (
            db.query(KBQA)
            .filter(or_(*conds))
            .order_by(KBQA.updated_at.desc())
            .all()
        )
        return jsonify({"items": [q.to_dict() for q in items], "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/qa", methods=["POST"])
def api_create_product_qa(product_id):
    """在当前商品下新建 QA"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA, KBQuestionVariant
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()

        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        if not product:
            return jsonify({"error": "商品不存在"}), 404
        if not data.get("question") or not data.get("answer"):
            return jsonify({"error": "question 和 answer 必填"}), 400

        content_hash = hashlib.md5(
            (data.get("question", "") + data.get("answer", "")).encode("utf-8")
        ).hexdigest()

        kwargs = _extract_qa_kwargs(data)
        kwargs["content_hash"] = content_hash
        kwargs["product_id"] = product_id
        kwargs["created_by"] = name

        source_type = data.get("source_type", "faq")
        risk_level = data.get("risk_level", "low")
        if source_type == "high_risk" or risk_level in ("high", "critical"):
            kwargs["human_review"] = True
            kwargs["auto_reply"] = False

        qa = KBQA(**kwargs)
        db.add(qa)
        db.flush()

        for v in data.get("variants", []):
            variant = KBQuestionVariant(
                qa_id=qa.id,
                variant_text=v.get("variant_text", ""),
                source=v.get("source", "manual"),
                created_by=name,
            )
            db.add(variant)

        db.commit()
        db.refresh(qa)

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="create",
            after_status=qa.status, performed_by=name,
            snapshot=qa.to_dict(include_variants=True),
            reason=f"从商品 {product.product_name} 新建关联问答",
        )

        return jsonify(qa.to_dict(include_variants=True)), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/qa/link", methods=["POST"])
def api_link_product_qa(product_id):
    """把已有 QA 关联到当前商品"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        qa_id = data.get("qa_id")
        if not qa_id:
            return jsonify({"error": "qa_id 必填"}), 400

        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        if not product:
            return jsonify({"error": "商品不存在"}), 404

        qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
        if not qa:
            return jsonify({"error": "QA 不存在"}), 404

        before_status = qa.status
        qa.product_id = product_id
        _, name = _get_user_info()
        qa.updated_by = name
        qa.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(qa)

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="update",
            before_status=before_status, after_status=qa.status, performed_by=name,
            changed_fields=["product_id"],
            snapshot=qa.to_dict(include_variants=True),
            reason=f"关联到商品 {product.product_name}",
        )

        return jsonify(qa.to_dict(include_variants=True))
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/qa/<int:qa_id>", methods=["DELETE"])
def api_unlink_product_qa(product_id, qa_id):
    """取消 QA 与当前商品的关联"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    db = SessionLocal()
    try:
        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        if not product:
            return jsonify({"error": "商品不存在"}), 404

        qa = db.query(KBQA).filter(KBQA.id == qa_id, KBQA.product_id == product_id).first()
        if not qa:
            return jsonify({"error": "未找到关联的 QA"}), 404

        before_status = qa.status
        qa.product_id = None
        _, name = _get_user_info()
        qa.updated_by = name
        qa.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(qa)

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="update",
            before_status=before_status, after_status=qa.status, performed_by=name,
            changed_fields=["product_id"],
            snapshot=qa.to_dict(include_variants=True),
            reason=f"取消与商品 {product.product_name} 的关联",
        )

        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/media/link", methods=["POST"])
def api_link_product_media(product_id):
    """把已有素材关联到当前商品"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBMediaAsset
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        asset_id = data.get("asset_id")
        if not asset_id:
            return jsonify({"error": "asset_id 必填"}), 400

        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        if not product:
            return jsonify({"error": "商品不存在"}), 404

        asset = db.query(KBMediaAsset).filter(KBMediaAsset.id == asset_id).first()
        if not asset:
            return jsonify({"error": "素材不存在"}), 404

        _, name = _get_user_info()
        asset.product_id = product_id
        if product.i_id and not asset.i_id:
            asset.i_id = product.i_id
        if product.product_name and not asset.product_name:
            asset.product_name = product.product_name
        asset.updated_by = name
        asset.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(asset)

        return jsonify({"ok": True, "asset": asset.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/media/<int:asset_id>", methods=["DELETE"])
def api_unlink_product_media(product_id, asset_id):
    """取消素材与当前商品的关联"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBMediaAsset
    db = SessionLocal()
    try:
        product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
        if not product:
            return jsonify({"error": "商品不存在"}), 404

        asset = db.query(KBMediaAsset).filter(
            KBMediaAsset.id == asset_id, KBMediaAsset.product_id == product_id
        ).first()
        if not asset:
            return jsonify({"error": "未找到关联的素材"}), 404

        _, name = _get_user_info()
        asset.product_id = None
        asset.updated_by = name
        asset.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(asset)

        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/health", methods=["GET"])
def api_product_health(product_id):
    """商品数据健康检查"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBQA
    db = SessionLocal()
    try:
        product = db.query(KBProduct).get(product_id)
        if not product:
            return jsonify({"error": "Not found"}), 404

        issues = []
        specs = product.get_specs()
        # 检查缺失字段
        field_map = {
            "材质": "material", "尺寸": "size", "承重/容量": "load_capacity",
            "适用年龄": "age_range", "质保期": "period", "物流属性": "attribute",
        }
        for label, key in field_map.items():
            val = specs.get(key, "")
            if key == "period":
                val = product.get_warranty().get("period", "")
            if key == "attribute":
                val = product.get_logistics().get("attribute", "")
            if not val or val == "详见商品详情页":
                issues.append({"type": f"missing_{key}", "severity": "warning", "message": f"缺少{label}"})

        # 关联问答检查
        qa_list = db.query(KBQA).filter(KBQA.product_id == product_id).all()
        if not qa_list:
            issues.append({"type": "no_qa", "severity": "info", "message": "无关联问答"})

        high_risk_qa = [q for q in qa_list if q.risk_level in ("high", "critical")]
        if high_risk_qa:
            issues.append({"type": "high_risk_qa", "severity": "critical",
                           "message": f"关联 {len(high_risk_qa)} 条高/极高风险问答"})

        auto_high = [q for q in qa_list if q.risk_level in ("high", "critical") and q.auto_reply]
        if auto_high:
            issues.append({"type": "high_auto_reply", "severity": "critical",
                           "message": f"{len(auto_high)} 条高风险问答允许自动回复"})

        # Agent 可用性判断
        can_agent = (
            product.status == "published"
            and product.completeness_score >= 60
            and len(high_risk_qa) == 0
            and len(auto_high) == 0
        )

        return jsonify({
            "product_id": product_id,
            "completeness_score": product.completeness_score,
            "missing_fields": product.get_missing_fields(),
            "qa_count": len(qa_list),
            "high_risk_qa_count": len(high_risk_qa),
            "can_agent_use": can_agent,
            "agent_block_reason": "" if can_agent else _agent_block_reason(product, high_risk_qa, auto_high),
            "issues": issues,
            "total_issues": len(issues),
            "critical_count": sum(1 for i in issues if i["severity"] == "critical"),
            "warning_count": sum(1 for i in issues if i["severity"] == "warning"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _agent_block_reason(product, high_risk_qa, auto_high):
    reasons = []
    if product.status != "published":
        reasons.append("未发布")
    if product.completeness_score < 60:
        reasons.append(f"完整度不足({product.completeness_score}%)")
    if high_risk_qa:
        reasons.append("有关联高风险问答")
    if auto_high:
        reasons.append("高风险问答允许自动回复")
    return "、".join(reasons) if reasons else ""


@kb_admin_bp.route("/products/<int:product_id>/versions", methods=["GET"])
def api_product_versions(product_id):
    """商品版本历史（从 change_log 查询）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBChangeLog
    db = SessionLocal()
    try:
        items = (
            db.query(KBChangeLog)
            .filter(KBChangeLog.target_type == "kb_product", KBChangeLog.target_id == product_id)
            .order_by(KBChangeLog.created_at.desc())
            .limit(50)
            .all()
        )
        return jsonify({"items": [i.to_dict() for i in items], "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/batch-update", methods=["POST"])
def api_product_batch_update():
    """批量更新商品状态"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("ids", [])
        action = data.get("action", "")
        _, name = _get_user_info()

        if not ids or not action:
            return jsonify({"error": "ids and action required"}), 400

        updated = 0
        for pid in ids:
            product = db.query(KBProduct).get(pid)
            if not product:
                continue
            if action == "submit_review" and product.status == "draft":
                product.status = "pending_review"
            elif action == "publish" and product.status == "pending_review":
                product.status = "published"
            elif action == "archive":
                product.status = "archived"
            elif action == "set_agent_use":
                product.agent_usable_level = data.get("value", "L1")
            product.updated_by = name
            product.updated_at = datetime.utcnow()
            updated += 1

        db.commit()
        return jsonify({"updated": updated})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/submit-review", methods=["POST"])
def api_product_submit_review(product_id):
    """提交商品审核"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct
    db = SessionLocal()
    try:
        product = db.query(KBProduct).get(product_id)
        if not product:
            return jsonify({"error": "Not found"}), 404
        _, name = _get_user_info()
        product.status = "pending_review"
        product.updated_by = name
        product.updated_at = datetime.utcnow()
        db.commit()
        return jsonify(product.to_dict(detail=True))
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/publish", methods=["POST"])
def api_product_publish(product_id):
    """发布商品"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct
    db = SessionLocal()
    try:
        product = db.query(KBProduct).get(product_id)
        if not product:
            return jsonify({"error": "Not found"}), 404
        _, name = _get_user_info()
        if not _require_supervisor(_get_user_info()[0]):
            return jsonify({"error": "Forbidden"}), 403
        product.status = "published"
        product.version += 1
        product.updated_by = name
        product.updated_at = datetime.utcnow()
        db.commit()
        return jsonify(product.to_dict(detail=True))
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/products/<int:product_id>/activity-rules", methods=["GET"])
def api_product_activity_rules(product_id):
    """查询商品关联的活动规则（只读，不暴露内部价格字段）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    db = SessionLocal()
    try:
        product = db.query(KBProduct).get(product_id)
        if not product:
            return jsonify({"error": "Not found"}), 404

        q = db.query(KBProductActivityRule).filter(
            (KBProductActivityRule.product_id == product_id) |
            (KBProductActivityRule.i_id == product.i_id)
        ).order_by(KBProductActivityRule.updated_at.desc())

        return jsonify({
            "items": [r.customer_context() for r in q.all()],
            "total": q.count(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _extract_product_kwargs(data):
    """Extract and normalize product fields from request body."""
    kwargs = {}
    simple_fields = [
        "i_id", "product_name", "brand",
        "category_l1", "category_l2", "category_l3",
        "status", "import_batch_id", "created_by",
    ]
    for f in simple_fields:
        if f in data:
            kwargs[f] = data[f]
    json_fields = ["sku_list", "specs", "logistics", "warranty"]
    for f in json_fields:
        if f in data:
            kwargs[f] = data[f]
    return kwargs


# ============ QA ============

@kb_admin_bp.route("/qa/risk-control", methods=["GET"])
def api_qa_risk_control():
    """风控专项列表：高风险缺SOP、高风险允许自动回复等"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        all_qa = db.query(KBQA).filter(KBQA.status != "archived").all()
        issues = {
            "high_no_sop": [],
            "high_auto_reply": [],
        }

        for qa in all_qa:
            if qa.risk_level in ("high", "critical") and not qa.sop_id:
                issues["high_no_sop"].append(qa.to_dict())
            if qa.risk_level in ("high", "critical") and qa.auto_reply:
                issues["high_auto_reply"].append(qa.to_dict())

        return jsonify({
            "high_no_sop": {"count": len(issues["high_no_sop"]), "items": issues["high_no_sop"][:50]},
            "high_auto_reply": {"count": len(issues["high_auto_reply"]), "items": issues["high_auto_reply"][:50]},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/navigation/product-tree", methods=["GET"])
def api_qa_product_tree():
    """按商品类目的问答导航树"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBProduct
    db = SessionLocal()
    try:
        # Build product lookup
        products = {p.id: p for p in db.query(KBProduct).all()}

        # Group QA by category path
        all_qa = db.query(KBQA).all()
        tree = {}  # l1 -> l2 -> l3 -> {count, pending, no_agent, high_risk, issue_types}

        for qa in all_qa:
            l1 = qa.category_l1 or "未分类"
            l2 = qa.category_l2 or "未分类"
            l3 = qa.category_l3 or "未分类"
            issue = qa.issue_type or "通用"

            if l1 not in tree:
                tree[l1] = {"count": 0, "pending": 0, "no_agent": 0, "high_risk": 0, "children": {}}
            tree[l1]["count"] += 1
            if qa.status == "pending_review": tree[l1]["pending"] += 1
            if qa.risk_level in ("high", "critical"): tree[l1]["high_risk"] += 1
            if not _qa_agent_ok(qa): tree[l1]["no_agent"] += 1

            if l2 not in tree[l1]["children"]:
                tree[l1]["children"][l2] = {"count": 0, "pending": 0, "no_agent": 0, "high_risk": 0, "children": {}}
            tree[l1]["children"][l2]["count"] += 1
            if qa.status == "pending_review": tree[l1]["children"][l2]["pending"] += 1
            if qa.risk_level in ("high", "critical"): tree[l1]["children"][l2]["high_risk"] += 1
            if not _qa_agent_ok(qa): tree[l1]["children"][l2]["no_agent"] += 1

            if l3 not in tree[l1]["children"][l2]["children"]:
                tree[l1]["children"][l2]["children"][l3] = {"count": 0, "pending": 0, "no_agent": 0, "high_risk": 0, "issue_types": {}}
            tree[l1]["children"][l2]["children"][l3]["count"] += 1
            if qa.status == "pending_review": tree[l1]["children"][l2]["children"][l3]["pending"] += 1
            if qa.risk_level in ("high", "critical"): tree[l1]["children"][l2]["children"][l3]["high_risk"] += 1
            if not _qa_agent_ok(qa): tree[l1]["children"][l2]["children"][l3]["no_agent"] += 1

            issues = tree[l1]["children"][l2]["children"][l3].setdefault("issue_types", {})
            issues[issue] = issues.get(issue, 0) + 1

        # Convert to list
        result = []
        for l1, n1 in sorted(tree.items()):
            node1 = {"label": l1, "count": n1["count"], "pending": n1["pending"], "no_agent": n1["no_agent"], "high_risk": n1["high_risk"], "children": []}
            for l2, n2 in sorted(n1["children"].items()):
                node2 = {"label": l2, "count": n2["count"], "pending": n2["pending"], "no_agent": n2["no_agent"], "high_risk": n2["high_risk"], "children": []}
                for l3, n3 in sorted(n2["children"].items()):
                    issues = n3.get("issue_types", {})
                    issue_list = [{"label": k, "count": v} for k, v in sorted(issues.items(), key=lambda x: -x[1])]
                    node2["children"].append({"label": l3, "count": n3["count"], "pending": n3["pending"], "no_agent": n3["no_agent"], "high_risk": n3["high_risk"], "issue_types": issue_list})
                node1["children"].append(node2)
            result.append(node1)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/navigation/scenario-tree", methods=["GET"])
def api_qa_scenario_tree():
    """按客服场景的问答导航树"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        all_qa = db.query(KBQA).all()
        tree = {}

        for qa in all_qa:
            scenario = qa.scenario_category or "未分类"
            issue = qa.issue_type or "通用"

            if scenario not in tree:
                tree[scenario] = {"count": 0, "medium_high": 0, "need_review": 0, "with_sop": 0, "no_sop": 0, "children": {}}
            tree[scenario]["count"] += 1
            if qa.risk_level in ("medium", "high", "critical"): tree[scenario]["medium_high"] += 1
            if qa.human_review: tree[scenario]["need_review"] += 1
            if qa.sop_id: tree[scenario]["with_sop"] += 1
            elif qa.risk_level in ("high", "critical"): tree[scenario]["no_sop"] += 1

            if issue not in tree[scenario]["children"]:
                tree[scenario]["children"][issue] = {"count": 0, "medium_high": 0, "need_review": 0, "with_sop": 0, "no_sop": 0}
            tree[scenario]["children"][issue]["count"] += 1
            if qa.risk_level in ("medium", "high", "critical"): tree[scenario]["children"][issue]["medium_high"] += 1
            if qa.human_review: tree[scenario]["children"][issue]["need_review"] += 1
            if qa.sop_id: tree[scenario]["children"][issue]["with_sop"] += 1
            elif qa.risk_level in ("high", "critical"): tree[scenario]["children"][issue]["no_sop"] += 1

        result = []
        for scenario, n in sorted(tree.items(), key=lambda x: -x[1]["count"]):
            children = [{"label": k, **v} for k, v in sorted(n["children"].items(), key=lambda x: -x[1]["count"])]
            result.append({"label": scenario, "count": n["count"], "medium_high": n["medium_high"],
                          "need_review": n["need_review"], "with_sop": n["with_sop"], "no_sop": n["no_sop"],
                          "children": children})

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/navigation/risk-tree", methods=["GET"])
def api_qa_risk_tree():
    """按风险等级的问答导航树"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        all_qa = db.query(KBQA).all()
        tree = {
            "低风险": {"count": 0, "auto_yes": 0, "draft": 0, "no_product": 0, "children": {}},
            "中风险": {"count": 0, "need_review": 0, "no_review": 0, "pending_confirm": 0, "children": {}},
            "高风险": {"count": 0, "no_auto": 0, "no_sop": 0, "compensation": 0, "complaint": 0, "children": {}},
            "极高风险": {"count": 0, "safety": 0, "legal": 0, "quality": 0, "children": {}},
        }

        for qa in all_qa:
            risk = qa.risk_level
            issue = qa.issue_type or "通用"

            if risk == "low":
                tree["低风险"]["count"] += 1
                if qa.auto_reply: tree["低风险"]["auto_yes"] += 1
                if qa.status == "draft": tree["低风险"]["draft"] += 1
                if not qa.product_id: tree["低风险"]["no_product"] += 1
            elif risk == "medium":
                tree["中风险"]["count"] += 1
                if qa.human_review: tree["中风险"]["need_review"] += 1
                else: tree["中风险"]["no_review"] += 1
                if qa.status == "pending_review": tree["中风险"]["pending_confirm"] += 1
            elif risk == "high":
                tree["高风险"]["count"] += 1
                if not qa.auto_reply: tree["高风险"]["no_auto"] += 1
                if not qa.sop_id: tree["高风险"]["no_sop"] += 1
                if "赔" in qa.question or "赔" in qa.answer: tree["高风险"]["compensation"] += 1
                if "投诉" in qa.question or "差评" in qa.question: tree["高风险"]["complaint"] += 1
            elif risk == "critical":
                tree["极高风险"]["count"] += 1
                if "受伤" in qa.question or "安全" in qa.question: tree["极高风险"]["safety"] += 1
                if "法律" in qa.question or "律师" in qa.question or "起诉" in qa.question: tree["极高风险"]["legal"] += 1
                if "质量" in qa.question or "缺陷" in qa.question: tree["极高风险"]["quality"] += 1

            # Add issue_type children under risk level
            risk_label = {"low": "低风险", "medium": "中风险", "high": "高风险", "critical": "极高风险"}.get(risk, "低风险")
            children = tree[risk_label].setdefault("children", {})
            if issue not in children:
                children[issue] = {"count": 0}
            children[issue]["count"] += 1

        # Convert children to lists
        for risk_level in tree.values():
            risk_level["children"] = [{"label": k, **v} for k, v in sorted(risk_level.get("children", {}).items(), key=lambda x: -x[1]["count"])]

        return jsonify(tree)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/sop", methods=["GET"])
def api_qa_sop(qa_id):
    """问答关联的 SOP"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBSOP
    db = SessionLocal()
    try:
        qa = db.query(KBQA).get(qa_id)
        if not qa or not qa.sop_id:
            return jsonify({"sop": None})
        sop = db.query(KBSOP).get(qa.sop_id)
        return jsonify({"sop": sop.to_dict() if sop else None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/link-sop", methods=["POST"])
def api_qa_link_sop(qa_id):
    """为 QA 关联 SOP"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        qa = db.query(KBQA).get(qa_id)
        if not qa:
            return jsonify({"error": "Not found"}), 404
        qa.sop_id = data.get("sop_id")
        db.commit()
        return jsonify({"ok": True, "sop_id": qa.sop_id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/navigation/risk-tree", methods=["GET"])
def api_sop_risk_tree():
    """SOP 风险场景导航树"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP, KBQA, KBCase
    db = SessionLocal()
    try:
        all_sop = db.query(KBSOP).all()
        qa_by_sop = {}
        for r in db.query(KBQA.sop_id, func.count(KBQA.id)).filter(KBQA.sop_id.isnot(None)).group_by(KBQA.sop_id).all():
            qa_by_sop[r[0]] = r[1]

        tree = {}
        for sop in all_sop:
            scenario = sop.scenario or "未分类"
            # Categorize by scenario content
            if "投诉" in scenario or "差评" in scenario or "12315" in scenario or "平台" in scenario:
                cat = "投诉/差评"
            elif "赔偿" in scenario or "退款" in scenario or "补偿" in scenario:
                cat = "赔偿/退款"
            elif "受伤" in scenario or "夹伤" in scenario or "倒塌" in scenario or "坍塌" in scenario:
                cat = "安全事故"
            elif "质量" in scenario or "破损" in scenario or "缺件" in scenario:
                cat = "质量问题"
            else:
                cat = "平台规则"

            if cat not in tree:
                tree[cat] = {"count": 0, "qa_count": 0, "children": []}

            qa_count = qa_by_sop.get(sop.id, 0)
            tree[cat]["count"] += 1
            tree[cat]["qa_count"] += qa_count
            tree[cat]["children"].append({
                "label": scenario,
                "sop_id": sop.id,
                "scenario_code": sop.scenario_code,
                "risk_level": sop.risk_level,
                "qa_count": qa_count,
            })

        result = []
        for cat, n in sorted(tree.items()):
            result.append({"label": cat, "count": n["count"], "qa_count": n["qa_count"], "children": n["children"]})

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _qa_agent_ok(qa):
    """Check if QA is usable by agent."""
    if qa.status != "published": return False
    if not qa.auto_reply: return False
    if qa.risk_level in ("high", "critical"): return False
    return True


@kb_admin_bp.route("/qa/summary", methods=["GET"])
def api_qa_summary():
    """问答统计总览"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBQuestionVariant
    from sqlalchemy import or_, and_
    db = SessionLocal()
    try:
        total = db.query(func.count(KBQA.id)).scalar()
        published = db.query(func.count(KBQA.id)).filter(KBQA.status == "published").scalar()
        draft = db.query(func.count(KBQA.id)).filter(KBQA.status == "draft").scalar()
        pending = db.query(func.count(KBQA.id)).filter(KBQA.status == "pending_review").scalar()
        auto_yes = db.query(func.count(KBQA.id)).filter(KBQA.auto_reply == True).scalar()
        auto_no = db.query(func.count(KBQA.id)).filter(KBQA.auto_reply == False).scalar()
        human_yes = db.query(func.count(KBQA.id)).filter(KBQA.human_review == True).scalar()
        low = db.query(func.count(KBQA.id)).filter(KBQA.risk_level == "low").scalar()
        medium = db.query(func.count(KBQA.id)).filter(KBQA.risk_level == "medium").scalar()
        high = db.query(func.count(KBQA.id)).filter(KBQA.risk_level == "high").scalar()
        critical = db.query(func.count(KBQA.id)).filter(KBQA.risk_level == "critical").scalar()
        no_product = db.query(func.count(KBQA.id)).filter(KBQA.product_id.is_(None)).scalar()
        variants = db.query(func.count(KBQuestionVariant.id)).scalar()

        # Agent usable: published + low/medium risk + auto_reply=True
        agent_ok = db.query(func.count(KBQA.id)).filter(
            KBQA.status == "published",
            KBQA.auto_reply == True,
            KBQA.risk_level.in_(["low", "medium"]),
        ).scalar()

        return jsonify({
            "total": total,
            "published": published,
            "draft": draft,
            "pending_review": pending,
            "auto_reply_yes": auto_yes,
            "auto_reply_no": auto_no,
            "human_review_yes": human_yes,
            "risk_low": low,
            "risk_medium": medium,
            "risk_high": high,
            "risk_critical": critical,
            "no_product": no_product,
            "variants": variants,
            "agent_usable": agent_ok,
            "not_agent_usable": total - agent_ok,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/health", methods=["GET"])
def api_qa_health(qa_id):
    """单条问答健康检查"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBProduct, KBQuestionVariant
    db = SessionLocal()
    try:
        qa = db.query(KBQA).get(qa_id)
        if not qa:
            return jsonify({"error": "Not found"}), 404

        issues = []
        answer = qa.answer or ""

        # 1. 缺关联商品
        if not qa.product_id:
            issues.append({"type": "no_product", "severity": "warning", "message": "未关联商品"})

        # 2. 缺关键词
        if not qa.get_keywords():
            issues.append({"type": "no_keywords", "severity": "warning", "message": "缺少分类关键词"})

        # 3. 无口语化问法
        variant_count = db.query(func.count(KBQuestionVariant.id)).filter(KBQuestionVariant.qa_id == qa_id).scalar()
        if variant_count == 0:
            issues.append({"type": "no_variants", "severity": "info", "message": "无口语化问法变体"})

        # 4. 答案过短
        if len(answer) < 20:
            issues.append({"type": "answer_short", "severity": "warning", "message": f"答案过短({len(answer)}字)"})

        # 6. 高风险允许自动回复
        if qa.risk_level in ("high", "critical") and qa.auto_reply:
            issues.append({"type": "high_auto_reply", "severity": "critical", "message": "高风险但允许自动回复"})

        # 7. 模糊承诺
        vague_words = ["一定", "保证", "肯定", "绝对", "百分之百"]
        for w in vague_words:
            if w in answer:
                issues.append({"type": "vague_promise", "severity": "warning", "message": f"答案含模糊承诺「{w}」"})
                break

        # 8. 赔偿承诺
        comp_words = ["赔偿", "退款", "补偿", "赔钱"]
        for w in comp_words:
            if w in answer:
                issues.append({"type": "compensation", "severity": "warning", "message": f"答案含赔偿相关「{w}」"})
                break

        # 9. 未发布
        if qa.status != "published":
            issues.append({"type": "not_published", "severity": "info", "message": f"状态: {qa.status}"})

        # 10. Agent 可用性
        can_agent = (
            qa.status == "published"
            and qa.auto_reply == True
            and qa.risk_level in ("low", "medium")
        )
        block_reasons = []
        if qa.status != "published": block_reasons.append("未发布")
        if not qa.auto_reply: block_reasons.append("未开启自动回复")
        if qa.risk_level in ("high", "critical"): block_reasons.append("高风险禁止自动回复")

        return jsonify({
            "qa_id": qa_id,
            "variant_count": variant_count,
            "issues": issues,
            "total_issues": len(issues),
            "can_agent_use": can_agent,
            "agent_block_reason": "、".join(block_reasons) if block_reasons else "",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/product", methods=["GET"])
def api_qa_product(qa_id):
    """问答关联商品详情"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBProduct
    db = SessionLocal()
    try:
        qa = db.query(KBQA).get(qa_id)
        if not qa or not qa.product_id:
            return jsonify({"product": None})
        product = db.query(KBProduct).get(qa.product_id)
        if not product:
            return jsonify({"product": None})
        return jsonify({"product": product.to_dict(detail=True)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/variants", methods=["GET"])
def api_qa_variants(qa_id):
    """问答口语化问法列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQuestionVariant
    db = SessionLocal()
    try:
        items = db.query(KBQuestionVariant).filter(KBQuestionVariant.qa_id == qa_id).all()
        return jsonify({"items": [v.to_dict() for v in items], "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/variants", methods=["POST"])
def api_qa_add_variant(qa_id):
    """新增口语化问法"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQuestionVariant
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        v = KBQuestionVariant(
            qa_id=qa_id,
            variant_text=data.get("variant_text", ""),
            source=data.get("source", "manual"),
            created_by=name,
        )
        db.add(v)
        db.commit()
        return jsonify(v.to_dict()), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/variants/<int:vid>", methods=["DELETE"])
def api_qa_delete_variant(qa_id, vid):
    """删除口语化问法"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQuestionVariant
    db = SessionLocal()
    try:
        v = db.query(KBQuestionVariant).get(vid)
        if not v or v.qa_id != qa_id:
            return jsonify({"error": "Not found"}), 404
        db.delete(v)
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/versions", methods=["GET"])
def api_qa_versions(qa_id):
    """问答版本记录"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBChangeLog
    db = SessionLocal()
    try:
        items = db.query(KBChangeLog).filter(
            KBChangeLog.target_type == "kb_qa", KBChangeLog.target_id == qa_id
        ).order_by(KBChangeLog.created_at.desc()).limit(50).all()
        return jsonify({"items": [i.to_dict() for i in items], "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/batch-update", methods=["POST"])
def api_qa_batch_update():
    """批量更新问答"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        data = request.get_json(force=True) or {}
        ids = data.get("ids", [])
        action = data.get("action", "")
        _, name = _get_user_info()

        if not ids or not action:
            return jsonify({"error": "ids and action required"}), 400

        updated = 0
        for qid in ids:
            qa = db.query(KBQA).get(qid)
            if not qa:
                continue
            if action == "submit_review" and qa.status in ("draft", "rejected"):
                qa.status = "pending_review"
            elif action == "publish" and qa.status == "pending_review":
                qa.status = "published"
            elif action == "archive":
                qa.status = "archived"
            elif action == "set_risk":
                qa.risk_level = data.get("value", "low")
            elif action == "set_auto_reply":
                qa.auto_reply = data.get("value", True)
            elif action == "set_human_review":
                qa.human_review = data.get("value", True)
            qa.updated_by = name
            qa.updated_at = datetime.utcnow()
            updated += 1

        db.commit()
        return jsonify({"updated": updated})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa", methods=["GET"])
def api_list_qa():
    """QA 列表，支持多维度过滤"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    from sqlalchemy import or_
    db = SessionLocal()
    try:
        q = db.query(KBQA)

        intent = request.args.get("intent", "")
        risk_level = request.args.get("risk_level", "")
        status = request.args.get("status", "")
        product_id = request.args.get("product_id", "")
        source_type = request.args.get("source_type", "")
        search = request.args.get("search", "")
        auto_reply = request.args.get("auto_reply", "")
        human_review = request.args.get("human_review", "")
        category_l1 = request.args.get("category_l1", "")
        category_l2 = request.args.get("category_l2", "")
        category_l3 = request.args.get("category_l3", "")
        scenario_category = request.args.get("scenario_category", "")
        issue_type = request.args.get("issue_type", "")
        sop_status = request.args.get("sop_status", "")
        content_contains = request.args.get("content_contains", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if intent:
            q = q.filter(KBQA.intent == intent)
        if risk_level:
            # 支持单值或逗号分隔多值，如 high,critical
            levels = [lvl.strip() for lvl in risk_level.split(",") if lvl.strip()]
            if len(levels) > 1:
                q = q.filter(KBQA.risk_level.in_(levels))
            else:
                q = q.filter(KBQA.risk_level == levels[0])
        if status:
            q = q.filter(KBQA.status == status)
        if product_id:
            q = q.filter(KBQA.product_id == int(product_id))
        if source_type:
            q = q.filter(KBQA.source_type == source_type)
        if auto_reply != "":
            q = q.filter(KBQA.auto_reply == (auto_reply.lower() in ("true", "1")))
        if human_review != "":
            q = q.filter(KBQA.human_review == (human_review.lower() in ("true", "1")))
        if category_l1:
            q = q.filter(KBQA.category_l1 == category_l1)
        if category_l2:
            q = q.filter(KBQA.category_l2 == category_l2)
        if category_l3:
            q = q.filter(KBQA.category_l3 == category_l3)
        if scenario_category:
            q = q.filter(KBQA.scenario_category == scenario_category)
        if issue_type:
            q = q.filter(KBQA.issue_type == issue_type)
        if sop_status == "has_sop":
            q = q.filter(KBQA.sop_id.isnot(None))
        elif sop_status == "no_sop":
            q = q.filter(KBQA.sop_id.is_(None))
        if content_contains:
            # 逗号分隔关键词，命中问题或答案任一即保留
            keywords = [kw.strip() for kw in content_contains.split(",") if kw.strip()]
            if keywords:
                content_conds = []
                for kw in keywords:
                    like = f"%{kw}%"
                    content_conds.append(or_(KBQA.question.ilike(like), KBQA.answer.ilike(like)))
                q = q.filter(or_(*content_conds))
        if search:
            like = f"%{search}%"
            q = q.filter(or_(
                KBQA.question.ilike(like),
                KBQA.answer.ilike(like),
            ))

        total = q.count()
        items = (
            q.order_by(KBQA.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [i.to_dict() for i in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>", methods=["GET"])
def api_get_qa(qa_id):
    """单个 QA 详情（含变体）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        item = db.query(KBQA).filter(KBQA.id == qa_id).first()
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item.to_dict(include_variants=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa", methods=["POST"])
def api_create_qa():
    """创建 QA，高风险自动关闭自动回复"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBQuestionVariant, KBChangeLog
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        db = SessionLocal()
        try:
            # Compute content_hash
            content_hash = hashlib.md5(
                (data.get("question", "") + data.get("answer", "")).encode("utf-8")
            ).hexdigest()

            kwargs = _extract_qa_kwargs(data)
            kwargs["content_hash"] = content_hash
            kwargs["created_by"] = name

            # High risk: keep it out of automatic replies.
            source_type = data.get("source_type", "faq")
            risk_level = data.get("risk_level", "low")
            if source_type == "high_risk" or risk_level in ("high", "critical"):
                kwargs["human_review"] = True
                kwargs["auto_reply"] = False

            qa = KBQA(**kwargs)
            db.add(qa)
            db.flush()

            # Handle variants
            variants = data.get("variants", [])
            for v in variants:
                variant = KBQuestionVariant(
                    qa_id=qa.id,
                    variant_text=v.get("variant_text", ""),
                    source=v.get("source", "manual"),
                    created_by=name,
                )
                db.add(variant)

            db.commit()
            db.refresh(qa)

            # Log change
            _log_change_inline(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question[:200], action="create",
                after_status=qa.status, performed_by=name,
                snapshot=qa.to_dict(include_variants=True),
                reason="新建QA",
            )

            return jsonify(qa.to_dict(include_variants=True)), 201
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/qa/<int:qa_id>", methods=["PUT"])
def api_update_qa(qa_id):
    """更新 QA，检测 review-needed 变更并自动创建审核任务"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA, KBReviewTask, KBChangeLog
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return jsonify({"error": "Not found"}), 404

            before_snapshot = qa.to_dict(include_variants=True)

            # Track changed fields
            review_needed_fields = {
                "question", "answer", "risk_level", "auto_reply",
                "human_review", "intent", "source_type",
            }
            changed = []

            simple_fields = [
                "question", "answer", "intent", "sub_intent",
                "category_l1", "category_l2", "category_l3",
                "scenario_category", "issue_type", "sop_id",
                "risk_level", "auto_reply", "human_review",
                "source_type", "status",
            ]
            for f in simple_fields:
                if f in data:
                    setattr(qa, f, data[f])
                    changed.append(f)

            if "product_id" in data:
                qa.product_id = data["product_id"]
                changed.append("product_id")
            if "sku_codes" in data:
                qa.set_sku_codes(data["sku_codes"])
                changed.append("sku_codes")
            if "keywords" in data:
                qa.set_keywords(data["keywords"])
                changed.append("keywords")

            qa.updated_by = name
            qa.updated_at = datetime.utcnow()

            # Risk hard rules - block dangerous auto_reply settings
            risk_errors = []
            new_risk = data.get("risk_level", qa.risk_level)
            new_auto = data.get("auto_reply", qa.auto_reply)
            new_sop = data.get("sop_id", qa.sop_id) if "sop_id" in data else qa.sop_id

            if new_risk in ("high", "critical") and new_auto:
                risk_errors.append({"field": "auto_reply", "reason": "高/极高风险问答禁止自动回复"})

            if risk_errors:
                db.rollback()
                return jsonify({"success": False, "message": "保存失败：存在风险违规", "errors": risk_errors}), 400

            # Update content_hash
            qa.content_hash = hashlib.md5(
                (qa.question + qa.answer).encode("utf-8")
            ).hexdigest()

            db.commit()
            db.refresh(qa)

            # Auto-create review task for review-needed changes
            if changed and set(changed) & review_needed_fields:
                after_snapshot = qa.to_dict(include_variants=True)
                review_task = KBReviewTask(
                    target_type="kb_qa",
                    target_id=qa.id,
                    change_type="update",
                    change_summary=f"字段变更: {', '.join(changed)}",
                    status="pending",
                    priority="high" if qa.risk_level in ("high", "critical") else "normal",
                    risk_level=qa.risk_level,
                    requested_by=name,
                )
                review_task.set_before_snapshot(before_snapshot)
                review_task.set_after_snapshot(after_snapshot)
                review_task.set_changed_fields(changed)
                db.add(review_task)
                db.commit()

            # Log change
            _log_change_inline(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question[:200], action="update",
                before_status=before_snapshot.get("status", ""),
                after_status=qa.status, performed_by=name,
                changed_fields=changed,
                snapshot=qa.to_dict(include_variants=True),
                reason="更新QA",
            )

            return jsonify(qa.to_dict(include_variants=True))
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/qa/<int:qa_id>", methods=["DELETE"])
def api_archive_qa(qa_id):
    """归档 QA（软删除），需 supervisor 权限"""
    role, name = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要 supervisor 或 admin 权限"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
        if not qa:
            return jsonify({"error": "Not found"}), 404

        old_status = qa.status
        qa.status = "archived"
        qa.updated_by = name
        qa.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="archive",
            before_status=old_status, after_status="archived",
            performed_by=name, reason="归档QA",
        )

        return jsonify({"id": qa.id, "status": "archived"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/variants", methods=["POST"])
def api_add_variant(qa_id):
    """添加口语化变体"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQuestionVariant
    try:
        data = request.get_json(force=True) or {}
        _, name = _get_user_info()
        db = SessionLocal()
        try:
            variant = KBQuestionVariant(
                qa_id=qa_id,
                variant_text=data.get("variant_text", ""),
                source=data.get("source", "manual"),
                created_by=name,
            )
            db.add(variant)
            db.commit()
            db.refresh(variant)
            return jsonify(variant.to_dict()), 201
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@kb_admin_bp.route("/qa/<int:qa_id>/variants/<int:variant_id>", methods=["DELETE"])
def api_remove_variant(qa_id, variant_id):
    """删除口语化变体"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQuestionVariant
    db = SessionLocal()
    try:
        variant = (
            db.query(KBQuestionVariant)
            .filter(
                KBQuestionVariant.id == variant_id,
                KBQuestionVariant.qa_id == qa_id,
            )
            .first()
        )
        if not variant:
            return jsonify({"error": "Not found"}), 404
        db.delete(variant)
        db.commit()
        return jsonify({"id": variant_id, "deleted": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/submit-review", methods=["POST"])
def api_qa_submit_review(qa_id):
    """提交 QA 审核"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    _, name = _get_user_info()
    db = SessionLocal()
    try:
        qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
        if not qa:
            return jsonify({"error": "Not found"}), 404

        old_status = qa.status
        qa.status = "pending_review"
        qa.updated_by = name
        qa.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="submit_review",
            before_status=old_status, after_status="pending_review",
            performed_by=name, reason="QA提交审核",
        )

        return jsonify(qa.to_dict(include_variants=True))
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/<int:qa_id>/publish", methods=["POST"])
def api_qa_publish(qa_id):
    """发布 QA（需 supervisor + 风险校验）"""
    role, name = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要 supervisor 或 admin 权限"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    db = SessionLocal()
    try:
        qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
        if not qa:
            return jsonify({"error": "Not found"}), 404

        # Risk hard rules - block publish
        errors = []
        if qa.risk_level in ("high", "critical") and qa.auto_reply:
            errors.append({"field": "auto_reply", "reason": "高/极高风险问答禁止自动回复"})
        if qa.risk_level in ("high", "critical") and not qa.sop_id:
            errors.append({"field": "sop_id", "reason": "高/极高风险问答必须关联 SOP"})
        if errors:
            return jsonify({"success": False, "message": "发布失败：存在风险违规", "errors": errors}), 400

        old_status = qa.status
        qa.status = "published"
        qa.reviewed_by = name
        qa.published_at = datetime.utcnow()
        qa.version += 1
        qa.updated_by = name
        qa.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_qa", target_id=qa.id,
            target_title=qa.question[:200], action="publish",
            before_status=old_status, after_status="published",
            performed_by=name, reason="QA发布",
        )

        return jsonify(qa.to_dict(include_variants=True))
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/intents", methods=["GET"])
def api_qa_intents():
    """返回所有 distinct intent 值，用于过滤下拉"""
    from app.db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT DISTINCT intent FROM kb_qa ORDER BY intent")).fetchall()
        return jsonify({"intents": [r[0] for r in rows if r[0]]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/qa/batch-submit", methods=["POST"])
def api_qa_batch_submit():
    """批量提交审核"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBQA
    data = request.get_json(force=True) or {}
    ids = data.get("ids", [])
    _, name = _get_user_info()

    if not ids:
        return jsonify({"error": "ids 不能为空"}), 400

    results = []
    db = SessionLocal()
    try:
        for qa_id in ids:
            try:
                qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
                if not qa:
                    results.append({"id": qa_id, "status": "error", "reason": "Not found"})
                    continue
                old_status = qa.status
                qa.status = "pending_review"
                qa.updated_by = name
                qa.updated_at = datetime.utcnow()
                db.flush()

                _log_change_inline(
                    db, target_type="kb_qa", target_id=qa.id,
                    target_title=qa.question[:200], action="submit_review",
                    before_status=old_status, after_status="pending_review",
                    performed_by=name, reason="批量提交审核",
                )
                results.append({"id": qa_id, "status": "submitted"})
            except Exception as e:
                results.append({"id": qa_id, "status": "error", "reason": str(e)})
        db.commit()
        return jsonify({"results": results})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _extract_qa_kwargs(data):
    """Extract and normalize QA fields from request body."""
    kwargs = {}
    simple_fields = [
        "question", "answer", "intent", "sub_intent",
        "category_l1", "category_l2", "category_l3",
        "scenario_category", "issue_type", "sop_id",
        "risk_level", "auto_reply", "human_review",
        "source_type", "status", "product_id",
    ]
    for f in simple_fields:
        if f in data:
            kwargs[f] = data[f]
    if "sku_codes" in data:
        kwargs["sku_codes_json"] = json.dumps(data["sku_codes"], ensure_ascii=False)
    if "keywords" in data:
        kwargs["keywords_json"] = json.dumps(data["keywords"], ensure_ascii=False)
    return kwargs


# ============ Reviews ============

@kb_admin_bp.route("/reviews", methods=["GET"])
def api_list_reviews():
    """审核任务列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBReviewTask
    db = SessionLocal()
    try:
        q = db.query(KBReviewTask)

        status = request.args.get("status", "")
        target_type = request.args.get("target_type", "")
        priority = request.args.get("priority", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if status:
            q = q.filter(KBReviewTask.status == status)
        if target_type:
            q = q.filter(KBReviewTask.target_type == target_type)
        if priority:
            q = q.filter(KBReviewTask.priority == priority)

        total = q.count()
        items = (
            q.order_by(KBReviewTask.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [i.to_dict() for i in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/reviews/<int:review_id>", methods=["GET"])
def api_get_review(review_id):
    """审核任务详情（含 before/after snapshot）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBReviewTask
    db = SessionLocal()
    try:
        item = db.query(KBReviewTask).filter(KBReviewTask.id == review_id).first()
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/reviews/<int:review_id>/approve", methods=["POST"])
def api_approve_review(review_id):
    """批准审核，将 after_snapshot 写回目标实体"""
    role, name = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要 supervisor 或 admin 权限"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBReviewTask, KBQA, KBSOP
    db = SessionLocal()
    try:
        task = db.query(KBReviewTask).filter(KBReviewTask.id == review_id).first()
        if not task:
            return jsonify({"error": "Not found"}), 404

        after = task.get_after_snapshot()

        # Apply after_snapshot to target entity
        if task.target_type == "kb_qa":
            entity = db.query(KBQA).filter(KBQA.id == task.target_id).first()
            if entity:
                _apply_snapshot_to_entity(entity, after, db)
        elif task.target_type == "kb_sop":
            entity = db.query(KBSOP).filter(KBSOP.id == task.target_id).first()
            if entity:
                _apply_snapshot_to_sop(entity, after, db)

        task.status = "approved"
        task.reviewer = name
        task.reviewed_at = datetime.utcnow()
        db.commit()

        return jsonify(task.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/reviews/<int:review_id>/reject", methods=["POST"])
def api_reject_review(review_id):
    """驳回审核"""
    role, name = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要 supervisor 或 admin 权限"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBReviewTask
    data = request.get_json(force=True) or {}
    db = SessionLocal()
    try:
        task = db.query(KBReviewTask).filter(KBReviewTask.id == review_id).first()
        if not task:
            return jsonify({"error": "Not found"}), 404

        task.status = "rejected"
        task.reviewer = name
        task.reviewed_at = datetime.utcnow()
        task.review_opinion = data.get("opinion", "")
        db.commit()

        return jsonify(task.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/reviews/stats", methods=["GET"])
def api_review_stats():
    """按状态统计审核任务"""
    from app.db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT status, COUNT(*) FROM kb_review_task GROUP BY status")
        ).fetchall()
        stats = {r[0]: r[1] for r in rows}
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _apply_snapshot_to_entity(entity, snapshot, db):
    """将 snapshot 中的字段写回 QA 实体"""
    simple_fields = [
        "question", "answer", "intent", "sub_intent",
        "category_l1", "category_l2", "category_l3",
        "risk_level", "auto_reply", "human_review",
        "source_type", "status",
    ]
    for f in simple_fields:
        if f in snapshot:
            setattr(entity, f, snapshot[f])
    if "product_id" in snapshot:
        entity.product_id = snapshot["product_id"]
    if "sku_codes" in snapshot:
        entity.set_sku_codes(snapshot["sku_codes"])
    if "keywords" in snapshot:
        entity.set_keywords(snapshot["keywords"])
    entity.updated_at = datetime.utcnow()
    entity.content_hash = hashlib.md5(
        (entity.question + entity.answer).encode("utf-8")
    ).hexdigest()


def _apply_snapshot_to_sop(entity, snapshot, db):
    """将 snapshot 中的字段写回 SOP 实体"""
    simple_fields = [
        "scenario", "scenario_code", "risk_level",
        "escalation_condition", "escalation_target",
        "response_template", "category_l1", "status",
    ]
    for f in simple_fields:
        if f in snapshot:
            setattr(entity, f, snapshot[f])
    if "keywords" in snapshot:
        entity.set_keywords(snapshot["keywords"])
    if "steps" in snapshot:
        entity.set_steps(snapshot["steps"])
    if "forbidden_actions" in snapshot:
        entity.set_forbidden_actions(snapshot["forbidden_actions"])
    entity.updated_at = datetime.utcnow()


# ============ SOP ============

@kb_admin_bp.route("/sop", methods=["GET"])
def api_list_sop():
    """SOP 列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    db = SessionLocal()
    try:
        q = db.query(KBSOP)

        risk_level = request.args.get("risk_level", "")
        status = request.args.get("status", "")
        category = request.args.get("category", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if risk_level:
            q = q.filter(KBSOP.risk_level == risk_level)
        if status:
            q = q.filter(KBSOP.status == status)
        else:
            q = q.filter(KBSOP.status != "archived")
        if category:
            q = q.filter(KBSOP.category_l1 == category)

        total = q.count()
        items = (
            q.order_by(KBSOP.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [s.to_dict() for s in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/<int:sop_id>", methods=["GET"])
def api_get_sop(sop_id):
    """单个 SOP 详情"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    db = SessionLocal()
    try:
        item = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop", methods=["POST"])
def api_create_sop():
    """创建 SOP"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    _, name = _get_user_info()
    data = request.get_json(force=True) or {}
    db = SessionLocal()
    try:
        kwargs = _extract_sop_kwargs(data)
        kwargs["created_by"] = name
        sop = KBSOP(**kwargs)
        db.add(sop)
        db.commit()
        db.refresh(sop)

        _log_change_inline(
            db, target_type="kb_sop", target_id=sop.id,
            target_title=sop.scenario[:200], action="create",
            after_status=sop.status, performed_by=name,
            snapshot=sop.to_dict(), reason="新建SOP",
        )

        return jsonify(sop.to_dict()), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/<int:sop_id>", methods=["PUT"])
def api_update_sop(sop_id):
    """更新 SOP，自动创建审核任务"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP, KBReviewTask
    _, name = _get_user_info()
    data = request.get_json(force=True) or {}
    db = SessionLocal()
    try:
        sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        if not sop:
            return jsonify({"error": "Not found"}), 404

        before_snapshot = sop.to_dict()

        changed = _apply_sop_updates(sop, data)
        sop.updated_by = name
        sop.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(sop)

        after_snapshot = sop.to_dict()

        # Create review task
        if changed:
            review_task = KBReviewTask(
                target_type="kb_sop",
                target_id=sop.id,
                change_type="update",
                change_summary=f"字段变更: {', '.join(changed)}",
                status="pending",
                priority="high" if sop.risk_level in ("high", "critical") else "normal",
                risk_level=sop.risk_level,
                requested_by=name,
            )
            review_task.set_before_snapshot(before_snapshot)
            review_task.set_after_snapshot(after_snapshot)
            review_task.set_changed_fields(changed)
            db.add(review_task)
            db.commit()

        _log_change_inline(
            db, target_type="kb_sop", target_id=sop.id,
            target_title=sop.scenario[:200], action="update",
            before_status=before_snapshot.get("status", ""),
            after_status=sop.status, performed_by=name,
            changed_fields=changed,
            snapshot=sop.to_dict(), reason="更新SOP",
        )

        return jsonify(sop.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/<int:sop_id>/submit-review", methods=["POST"])
def api_sop_submit_review(sop_id):
    """提交 SOP 审核"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    _, name = _get_user_info()
    db = SessionLocal()
    try:
        sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        if not sop:
            return jsonify({"error": "Not found"}), 404

        old_status = sop.status
        sop.status = "pending_review"
        sop.updated_by = name
        sop.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_sop", target_id=sop.id,
            target_title=sop.scenario[:200], action="submit_review",
            before_status=old_status, after_status="pending_review",
            performed_by=name, reason="SOP提交审核",
        )

        return jsonify(sop.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/<int:sop_id>/publish", methods=["POST"])
def api_sop_publish(sop_id):
    """发布 SOP（需 supervisor）"""
    role, name = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要 supervisor 或 admin 权限"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    db = SessionLocal()
    try:
        sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        if not sop:
            return jsonify({"error": "Not found"}), 404

        old_status = sop.status
        sop.status = "published"
        sop.reviewed_by = name
        sop.version += 1
        sop.updated_by = name
        sop.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_sop", target_id=sop.id,
            target_title=sop.scenario[:200], action="publish",
            before_status=old_status, after_status="published",
            performed_by=name, reason="SOP发布",
        )

        return jsonify(sop.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/sop/<int:sop_id>", methods=["DELETE"])
def api_delete_sop(sop_id):
    """归档 SOP（前端作为删除使用，保留历史记录）"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBSOP
    _, name = _get_user_info()
    db = SessionLocal()
    try:
        sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        if not sop:
            return jsonify({"error": "Not found"}), 404

        old_status = sop.status
        sop.status = "archived"
        sop.updated_by = name
        sop.updated_at = datetime.utcnow()
        db.commit()

        _log_change_inline(
            db, target_type="kb_sop", target_id=sop.id,
            target_title=sop.scenario[:200], action="archive",
            before_status=old_status, after_status="archived",
            performed_by=name, reason="SOP删除/归档",
        )

        return jsonify(sop.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _extract_sop_kwargs(data):
    """Extract SOP fields from request body."""
    kwargs = {}
    simple_fields = [
        "scenario", "scenario_code", "risk_level",
        "escalation_condition", "escalation_target",
        "response_template", "category_l1", "status", "owner",
    ]
    for f in simple_fields:
        if f in data:
            kwargs[f] = data[f]
    if "keywords" in data:
        kwargs["keywords_json"] = json.dumps(data["keywords"], ensure_ascii=False)
    if "steps" in data:
        kwargs["steps_json"] = json.dumps(data["steps"], ensure_ascii=False)
    if "forbidden_actions" in data:
        kwargs["forbidden_actions_json"] = json.dumps(data["forbidden_actions"], ensure_ascii=False)
    return kwargs


def _apply_sop_updates(sop, data):
    """Apply updates to SOP entity, return list of changed fields."""
    changed = []
    simple_fields = [
        "scenario", "scenario_code", "risk_level",
        "escalation_condition", "escalation_target",
        "response_template", "category_l1", "status",
    ]
    for f in simple_fields:
        if f in data:
            setattr(sop, f, data[f])
            changed.append(f)
    if "keywords" in data:
        sop.set_keywords(data["keywords"])
        changed.append("keywords")
    if "steps" in data:
        sop.set_steps(data["steps"])
        changed.append("steps")
    if "forbidden_actions" in data:
        sop.set_forbidden_actions(data["forbidden_actions"])
        changed.append("forbidden_actions")
    return changed


# ============ Cases ============

@kb_admin_bp.route("/cases", methods=["GET"])
def api_list_cases():
    """案例列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBCase
    db = SessionLocal()
    try:
        q = db.query(KBCase)

        scenario = request.args.get("scenario", "")
        category_l1 = request.args.get("category_l1", "")
        risk_level = request.args.get("risk_level", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if scenario:
            q = q.filter(KBCase.scenario.ilike(f"%{scenario}%"))
        if category_l1:
            q = q.filter(KBCase.category_l1 == category_l1)
        if risk_level:
            q = q.filter(KBCase.risk_level == risk_level)

        total = q.count()
        items = (
            q.order_by(KBCase.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [c.to_dict() for c in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/cases/<int:case_id>", methods=["GET"])
def api_get_case(case_id):
    """单个案例详情"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBCase
    db = SessionLocal()
    try:
        item = db.query(KBCase).filter(KBCase.id == case_id).first()
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/cases", methods=["POST"])
def api_create_case():
    """创建案例"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBCase
    _, name = _get_user_info()
    data = request.get_json(force=True) or {}
    db = SessionLocal()
    try:
        kwargs = _extract_case_kwargs(data)
        kwargs["created_by"] = name
        case = KBCase(**kwargs)
        db.add(case)
        db.commit()
        db.refresh(case)
        return jsonify(case.to_dict()), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/cases/<int:case_id>", methods=["PUT"])
def api_update_case(case_id):
    """更新案例"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBCase
    _, name = _get_user_info()
    data = request.get_json(force=True) or {}
    db = SessionLocal()
    try:
        case = db.query(KBCase).filter(KBCase.id == case_id).first()
        if not case:
            return jsonify({"error": "Not found"}), 404

        _apply_case_updates(case, data)
        case.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(case)
        return jsonify(case.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _extract_case_kwargs(data):
    """Extract case fields from request body."""
    kwargs = {}
    simple_fields = [
        "case_code", "scenario", "customer_dialogue",
        "correct_reply", "wrong_reply",
        "reply_quality_score", "empathy_score",
        "accuracy_score", "wrong_reply_score",
        "wrong_reason", "supervisor_comment",
        "final_result", "category_l1", "risk_level",
        "qa_id", "status",
    ]
    for f in simple_fields:
        if f in data:
            kwargs[f] = data[f]
    if "tags" in data:
        kwargs["tags_json"] = json.dumps(data["tags"], ensure_ascii=False)
    return kwargs


def _apply_case_updates(case, data):
    """Apply updates to case entity."""
    simple_fields = [
        "case_code", "scenario", "customer_dialogue",
        "correct_reply", "wrong_reply",
        "reply_quality_score", "empathy_score",
        "accuracy_score", "wrong_reply_score",
        "wrong_reason", "supervisor_comment",
        "final_result", "category_l1", "risk_level",
        "qa_id", "status",
    ]
    for f in simple_fields:
        if f in data:
            setattr(case, f, data[f])
    if "tags" in data:
        case.set_tags(data["tags"])


# ============ Traces ============

@kb_admin_bp.route("/traces", methods=["GET"])
def api_list_traces():
    """Agent 轨迹列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBAgentTrace
    db = SessionLocal()
    try:
        q = db.query(KBAgentTrace)

        conversation_id = request.args.get("conversation_id", "")
        intent = request.args.get("intent", "")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if conversation_id:
            q = q.filter(KBAgentTrace.conversation_id == conversation_id)
        if intent:
            q = q.filter(KBAgentTrace.detected_intent == intent)
        if date_from:
            q = q.filter(KBAgentTrace.created_at >= date_from)
        if date_to:
            q = q.filter(KBAgentTrace.created_at <= date_to)

        total = q.count()
        items = (
            q.order_by(KBAgentTrace.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [t.to_dict() for t in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/traces/<int:trace_id>", methods=["GET"])
def api_get_trace(trace_id):
    """单个轨迹详情"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBAgentTrace
    db = SessionLocal()
    try:
        item = db.query(KBAgentTrace).filter(KBAgentTrace.id == trace_id).first()
        if not item:
            return jsonify({"error": "Not found"}), 404
        return jsonify(item.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/traces/stats", methods=["GET"])
def api_trace_stats():
    """轨迹聚合统计"""
    from app.db import SessionLocal
    from sqlalchemy import text, func
    from app.models.kb_tables import KBAgentTrace
    db = SessionLocal()
    try:
        # Intent distribution
        intent_rows = db.query(
            KBAgentTrace.detected_intent,
            func.count(KBAgentTrace.id),
        ).group_by(KBAgentTrace.detected_intent).all()
        intent_distribution = {r[0]: r[1] for r in intent_rows if r[0]}

        # Average confidence
        avg_conf = db.query(func.avg(KBAgentTrace.confidence)).scalar() or 0.0

        # Guard pass rate
        total_traces = db.query(func.count(KBAgentTrace.id)).scalar() or 1
        guard_pass = db.query(func.count(KBAgentTrace.id)).filter(
            KBAgentTrace.guard_passed == True  # noqa: E712
        ).scalar() or 0

        return jsonify({
            "intent_distribution": intent_distribution,
            "avg_confidence": round(float(avg_conf), 4),
            "guard_pass_rate": round(guard_pass / total_traces, 4),
            "total_traces": total_traces,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ============ Feedback ============

@kb_admin_bp.route("/feedback", methods=["GET"])
def api_list_feedback():
    """反馈列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBFeedback
    db = SessionLocal()
    try:
        q = db.query(KBFeedback)

        csr_action = request.args.get("csr_action", "")
        qa_id = request.args.get("qa_id", "")
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if csr_action:
            q = q.filter(KBFeedback.csr_action == csr_action)
        if qa_id:
            q = q.filter(KBFeedback.qa_id == int(qa_id))
        if date_from:
            q = q.filter(KBFeedback.created_at >= date_from)
        if date_to:
            q = q.filter(KBFeedback.created_at <= date_to)

        total = q.count()
        items = (
            q.order_by(KBFeedback.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [f.to_dict() for f in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/feedback/stats", methods=["GET"])
def api_feedback_stats():
    """反馈聚合统计"""
    from app.db import SessionLocal
    from sqlalchemy import func
    from app.models.kb_tables import KBFeedback
    db = SessionLocal()
    try:
        # Action distribution
        action_rows = db.query(
            KBFeedback.csr_action,
            func.count(KBFeedback.id),
        ).group_by(KBFeedback.csr_action).all()
        action_distribution = {r[0]: r[1] for r in action_rows if r[0]}

        # Avg supervisor score
        avg_sup = db.query(func.avg(KBFeedback.supervisor_score)).scalar()

        # Avg reward score
        avg_reward = db.query(func.avg(KBFeedback.reward_score)).scalar()

        return jsonify({
            "action_distribution": action_distribution,
            "avg_supervisor_score": round(float(avg_sup), 2) if avg_sup else None,
            "avg_reward_score": round(float(avg_reward), 4) if avg_reward else None,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ============ Health ============

@kb_admin_bp.route("/health/report", methods=["GET"])
def api_health_report():
    """综合健康检查"""
    from app.db import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        issues = []
        issue_id = 0

        # 1. Products with completeness_score < 60
        rows = db.execute(
            text("SELECT id, product_name, completeness_score FROM kb_product WHERE completeness_score < 60")
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "low_completeness",
                "severity": "warning",
                "message": f"商品 '{r[1]}' 完整度仅 {r[2]}%",
                "target_type": "kb_product",
                "target_id": r[0],
                "suggestion": "补充缺失字段以提高商品完整度",
            })

        # 2. QA without product_id
        rows = db.execute(
            text("SELECT id, question FROM kb_qa WHERE product_id IS NULL AND status != 'archived'")
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "qa_no_product",
                "severity": "info",
                "message": f"QA #{r[0]} 未关联商品",
                "target_type": "kb_qa",
                "target_id": r[0],
                "suggestion": "关联到对应商品以提高检索精度",
            })

        # 3. QA with empty keywords
        rows = db.execute(
            text("SELECT id, question FROM kb_qa WHERE (keywords_json = '[]' OR keywords_json = '' OR keywords_json IS NULL) AND status != 'archived'")
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "qa_empty_keywords",
                "severity": "warning",
                "message": f"QA #{r[0]} 缺少关键词",
                "target_type": "kb_qa",
                "target_id": r[0],
                "suggestion": "添加关键词以提高检索命中率",
            })

        # 4. QA with no variants
        rows = db.execute(
            text(
                "SELECT q.id, q.question FROM kb_qa q "
                "LEFT JOIN kb_question_variant v ON v.qa_id = q.id "
                "WHERE v.id IS NULL AND q.status != 'archived' "
                "GROUP BY q.id"
            )
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "qa_no_variants",
                "severity": "info",
                "message": f"QA #{r[0]} 没有口语化变体",
                "target_type": "kb_qa",
                "target_id": r[0],
                "suggestion": "添加口语化变体以提高意图匹配率",
            })

        # 6. QA: high/critical risk but auto_reply=True
        rows = db.execute(
            text("SELECT id, question, risk_level FROM kb_qa WHERE risk_level IN ('high', 'critical') AND auto_reply = 1 AND status != 'archived'")
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "high_risk_auto_reply",
                "severity": "critical",
                "message": f"QA #{r[0]} 为 {r[2]} 风险但开启了自动回复",
                "target_type": "kb_qa",
                "target_id": r[0],
                "suggestion": "高风险QA应关闭自动回复并关联SOP",
            })

        # 7. QA: answer shorter than 20 chars
        rows = db.execute(
            text("SELECT id, question, LENGTH(answer) as alen FROM kb_qa WHERE LENGTH(answer) < 20 AND status != 'archived'")
        ).fetchall()
        for r in rows:
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "short_answer",
                "severity": "warning",
                "message": f"QA #{r[0]} 回答过短（{r[2]}字符）",
                "target_type": "kb_qa",
                "target_id": r[0],
                "suggestion": "补充更完整的回答内容",
            })

        # 8. QA: answer contains vague promises
        vague_patterns = ["一定", "保证", "肯定", "绝对"]
        for pattern in vague_patterns:
            rows = db.execute(
                text(f"SELECT id, question FROM kb_qa WHERE answer LIKE '%{pattern}%' AND status != 'archived'")
            ).fetchall()
            for r in rows:
                issue_id += 1
                issues.append({
                    "id": issue_id,
                    "type": "vague_promise",
                    "severity": "critical",
                    "message": f"QA #{r[0]} 回答包含模糊承诺词 '{pattern}'",
                    "target_type": "kb_qa",
                    "target_id": r[0],
                    "suggestion": f"移除或替换 '{pattern}'，避免过度承诺",
                })

        # 9. QA: answer contains compensation promises
        comp_patterns = ["赔偿", "退款", "补偿"]
        for pattern in comp_patterns:
            rows = db.execute(
                text(f"SELECT id, question FROM kb_qa WHERE answer LIKE '%{pattern}%' AND status != 'archived'")
            ).fetchall()
            for r in rows:
                issue_id += 1
                issues.append({
                    "id": issue_id,
                    "type": "compensation_promise",
                    "severity": "critical",
                    "message": f"QA #{r[0]} 回答包含赔偿/退款承诺词 '{pattern}'",
                    "target_type": "kb_qa",
                    "target_id": r[0],
                    "suggestion": f"确认 '{pattern}' 相关内容是否符合公司政策，建议走SOP流程",
                })

        # 10. Duplicate QA (same content_hash)
        rows = db.execute(
            text(
                "SELECT content_hash, COUNT(*) as cnt FROM kb_qa "
                "WHERE content_hash != '' AND status != 'archived' "
                "GROUP BY content_hash HAVING cnt > 1"
            )
        ).fetchall()
        for r in rows:
            dup_rows = db.execute(
                text("SELECT id, question FROM kb_qa WHERE content_hash = :hash AND status != 'archived'"),
                {"hash": r[0]},
            ).fetchall()
            issue_id += 1
            issues.append({
                "id": issue_id,
                "type": "duplicate_qa",
                "severity": "warning",
                "message": f"发现 {r[1]} 条重复QA（content_hash={r[0][:8]}...）: {', '.join(str(d[0]) for d in dup_rows)}",
                "target_type": "kb_qa",
                "target_id": dup_rows[0][0] if dup_rows else 0,
                "suggestion": "合并或归档重复的QA条目",
            })

        # Compute score: base 100, penalize by severity with diminishing impact
        total_qa_count = db.execute(text("SELECT COUNT(*) FROM kb_qa")).scalar() or 1
        total_product_count = db.execute(text("SELECT COUNT(*) FROM kb_product")).scalar() or 1
        critical_count = sum(1 for i in issues if i["severity"] == "critical")
        warning_count = sum(1 for i in issues if i["severity"] == "warning")
        info_count = sum(1 for i in issues if i["severity"] == "info")
        # Score: start from 100, deduct proportionally (capped so it never goes below 0)
        qa_penalty = min(30, int(warning_count / max(1, total_qa_count / 10) * 10))
        prod_penalty = min(20, int(sum(1 for i in issues if i["type"] == "low_completeness") / max(1, total_product_count) * 20))
        critical_penalty = min(30, critical_count * 10)
        info_penalty = min(10, info_count)
        score = max(0, 100 - qa_penalty - prod_penalty - critical_penalty - info_penalty)

        return jsonify({
            "score": score,
            "total_issues": len(issues),
            "issues": issues,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@kb_admin_bp.route("/health/issues", methods=["GET"])
def api_health_issues():
    """健康检查问题列表（可按 severity/type 过滤）"""
    # Re-run the report but return only issues
    try:
        from flask import current_app
        with current_app.test_request_context("/api/kb/health/report"):
            report_resp = api_health_report()
        report_data = report_resp.get_json()
        issues = report_data.get("issues", [])

        severity = request.args.get("severity", "")
        issue_type = request.args.get("issue_type", "")

        if severity:
            issues = [i for i in issues if i["severity"] == severity]
        if issue_type:
            issues = [i for i in issues if i["type"] == issue_type]

        return jsonify({"issues": issues, "total": len(issues)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============ Changelog ============

@kb_admin_bp.route("/changelog", methods=["GET"])
def api_changelog():
    """变更日志列表"""
    from app.db import SessionLocal
    from app.models.kb_tables import KBChangeLog
    db = SessionLocal()
    try:
        q = db.query(KBChangeLog)

        target_type = request.args.get("target_type", "")
        performed_by = request.args.get("performed_by", "")
        date_from = request.args.get("date_from", "")
        limit = request.args.get("limit", 20, type=int)
        offset = request.args.get("offset", 0, type=int)

        if target_type:
            q = q.filter(KBChangeLog.target_type == target_type)
        if performed_by:
            q = q.filter(KBChangeLog.performed_by == performed_by)
        if date_from:
            q = q.filter(KBChangeLog.created_at >= date_from)

        total = q.count()
        items = (
            q.order_by(KBChangeLog.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return jsonify({
            "items": [l.to_dict() for l in items],
            "total": total,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ============ AI Assist ============

@kb_admin_bp.route("/ai/optimize-tone", methods=["POST"])
def api_ai_optimize_tone():
    """AI 优化话术语气"""
    data = request.get_json(force=True) or {}
    answer = data.get("answer", "")
    tone = data.get("tone", "professional")

    if not answer:
        return jsonify({"error": "answer 不能为空"}), 400

    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()

        if not client.api_key:
            return jsonify({
                "optimized": answer,
                "note": "LLM 未配置，返回原文",
            })

        tone_map = {
            "professional": "专业、简洁、准确",
            "warm": "温暖、亲切、共情",
            "concise": "简短、直接、明了",
        }
        tone_desc = tone_map.get(tone, tone_map["professional"])

        system_prompt = "你是一个客服话术优化专家。只返回优化后的话术文本，不要解释。"
        user_message = (
            f"请将以下客服回复优化为{tone_desc}的语气，保持原意不变：\n\n{answer}"
        )

        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            max_tokens=500,
        )
        optimized = response.choices[0].message.content.strip()
        return jsonify({"optimized": optimized})
    except Exception as e:
        return jsonify({"optimized": answer, "error": str(e)})


@kb_admin_bp.route("/ai/generate-variants", methods=["POST"])
def api_ai_generate_variants():
    """AI 生成口语化问法变体"""
    data = request.get_json(force=True) or {}
    question = data.get("question", "")
    count = data.get("count", 10)

    if not question:
        return jsonify({"error": "question 不能为空"}), 400

    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()

        if not client.api_key:
            return jsonify({
                "variants": [question],
                "note": "LLM 未配置，返回原文",
            })

        system_prompt = f"你是一个客服对话数据增强专家。生成 {count} 种不同的口语化问法变体。以 JSON 数组格式返回，不要其他内容。"
        user_message = f"请为以下标准问法生成 {count} 种口语化变体：\n\n{question}"

        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()

        # Parse JSON array from response
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            variants = json.loads(match.group())
        else:
            variants = [line.strip().strip('"').strip("'") for line in raw.split("\n") if line.strip()]

        return jsonify({"variants": variants})
    except Exception as e:
        return jsonify({"variants": [question], "error": str(e)})


@kb_admin_bp.route("/ai/check-violations", methods=["POST"])
def api_ai_check_violations():
    """AI 检查回答违规"""
    data = request.get_json(force=True) or {}
    answer = data.get("answer", "")

    if not answer:
        return jsonify({"error": "answer 不能为空"}), 400

    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()

        if not client.api_key:
            return jsonify({
                "violations": [],
                "note": "LLM 未配置，无法检查",
            })

        system_prompt = (
            "你是客服合规审核专家。检查回答中是否存在以下违规：\n"
            "1. 过度承诺（如'一定''保证''肯定''绝对'）\n"
            "2. 未经授权的赔偿/退款承诺\n"
            "3. 不专业的语气\n"
            "4. 泄露内部流程或系统信息\n"
            "5. 误导性信息\n"
            "以 JSON 数组格式返回，每项包含 type 和 description 字段。无违规返回空数组。"
        )
        user_message = f"请检查以下客服回复是否存在违规：\n\n{answer}"

        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()

        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            violations = json.loads(match.group())
        else:
            violations = []

        return jsonify({"violations": violations})
    except Exception as e:
        return jsonify({"violations": [], "error": str(e)})


@kb_admin_bp.route("/ai/suggest-keywords", methods=["POST"])
def api_ai_suggest_keywords():
    """AI 推荐关键词"""
    data = request.get_json(force=True) or {}
    question = data.get("question", "")
    answer = data.get("answer", "")

    if not question:
        return jsonify({"error": "question 不能为空"}), 400

    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()

        if not client.api_key:
            return jsonify({
                "keywords": [],
                "note": "LLM 未配置，无法推荐",
            })

        system_prompt = (
            "你是客服知识库管理专家。根据问答内容推荐用于检索的关键词。"
            "以 JSON 数组格式返回关键词列表（字符串数组），不要其他内容。"
            "关键词应包含：商品相关词、场景词、问题类型词、客户可能的搜索词。"
        )
        user_message = f"问题：{question}\n\n回答：{answer}\n\n请推荐检索关键词。"

        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        raw = response.choices[0].message.content.strip()

        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            keywords = json.loads(match.group())
        else:
            keywords = []

        return jsonify({"keywords": keywords})
    except Exception as e:
        return jsonify({"keywords": [], "error": str(e)})


@kb_admin_bp.route("/ai/generate-versions", methods=["POST"])
def api_ai_generate_versions():
    """AI 生成不同风格的回答版本"""
    data = request.get_json(force=True) or {}
    question = data.get("question", "")
    answer = data.get("answer", "")
    style = data.get("style", "short")

    if not question or not answer:
        return jsonify({"error": "question 和 answer 不能为空"}), 400

    try:
        from app.llm.client import get_llm_client
        client = get_llm_client()

        if not client.api_key:
            return jsonify({
                "generated": answer,
                "note": "LLM 未配置，返回原回答",
            })

        style_map = {
            "short": "简短版（3句话以内，直击要点）",
            "warm": "温暖版（增加共情和关怀表达）",
            "presale": "售前版（引导购买，突出卖点）",
            "aftersale": "售后版（解决问题为主，安抚情绪）",
        }
        style_desc = style_map.get(style, style_map["short"])

        system_prompt = "你是客服话术专家。只返回优化后的回复文本，不要解释。"
        user_message = (
            f"请将以下客服回复改写为{style_desc}：\n\n"
            f"客户问题：{question}\n\n"
            f"原始回复：{answer}"
        )

        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.5,
            max_tokens=500,
        )
        generated = response.choices[0].message.content.strip()
        return jsonify({"generated": generated})
    except Exception as e:
        return jsonify({"generated": answer, "error": str(e)})


# ============ AI Update Center ============

def _ai_update_tasks_path():
    import os
    from app.config import BASE_DIR
    return os.path.join(BASE_DIR, "data", "ai_update_tasks.json")


def _load_ai_update_tasks():
    path = _ai_update_tasks_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []


def _save_ai_update_tasks(tasks):
    import os
    path = _ai_update_tasks_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)


def _status_summary(tasks):
    labels = ["待整理给 AI", "待人工确认", "AI 已可用", "测试失败"]
    return {label: sum(1 for item in tasks if item.get("status") == label) for label in labels}


@kb_admin_bp.route("/ai-update/tasks", methods=["GET"])
def api_ai_update_tasks():
    """AI 更新中心任务列表。"""
    from app.db import SessionLocal
    from sqlalchemy import text

    tasks = _load_ai_update_tasks()
    db = SessionLocal()
    derived = {}
    try:
        conn = db.connection()
        derived = {
            "pending_review": conn.execute(
                text("SELECT COUNT(*) FROM kb_review_task WHERE status = 'pending'")
            ).scalar() or 0,
            "feedback_total": conn.execute(text("SELECT COUNT(*) FROM kb_feedback")).scalar() or 0,
            "case_total": conn.execute(text("SELECT COUNT(*) FROM kb_case")).scalar() or 0,
            "test_total": conn.execute(text("SELECT COUNT(*) FROM kb_agent_trace")).scalar() or 0,
            "product_draft": conn.execute(
                text("SELECT COUNT(*) FROM kb_product WHERE status IN ('draft', 'pending_review')")
            ).scalar() or 0,
        }
    except Exception:
        derived = {}
    finally:
        db.close()

    return jsonify({
        "items": tasks,
        "summary": _status_summary(tasks),
        "derived": derived,
    })


@kb_admin_bp.route("/ai-update/tasks/<task_id>", methods=["PUT"])
def api_update_ai_update_task(task_id):
    """更新 AI 更新中心任务。"""
    data = request.get_json(force=True) or {}
    _, user_name = _get_user_info()
    allowed_status = {"待整理给 AI", "待人工确认", "AI 已可用", "测试失败"}

    tasks = _load_ai_update_tasks()
    for item in tasks:
        if item.get("id") != task_id:
            continue
        before_status = item.get("status", "")
        for field in ("owner", "status", "reason", "testQuestion"):
            if field in data:
                if field == "status" and data[field] not in allowed_status:
                    return jsonify({"error": "status 不合法"}), 400
                item[field] = data[field]
        item["lastChanged"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save_ai_update_tasks(tasks)
        try:
            from app.db import SessionLocal
            db = SessionLocal()
            _log_change_inline(
                db,
                target_type="ai_update_task",
                target_id=0,
                target_title=item.get("title", task_id),
                action="update",
                performed_by=user_name,
                reason=item.get("reason", ""),
                before_status=before_status,
                after_status=item.get("status", ""),
                changed_fields=list(data.keys()),
                snapshot=item,
            )
            db.close()
        except Exception:
            pass
        return jsonify({"item": item, "summary": _status_summary(tasks)})

    return jsonify({"error": "任务不存在"}), 404


def _safe_json_loads(value, fallback=None):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback if fallback is not None else []


def _summarize_bad_case_learning(case):
    status = case.get("status", "open")
    has_fix = bool(case.get("fix_note") or case.get("regression_test_id"))
    if status == "verified":
        return "已复测通过"
    if status == "fixed" or has_fix:
        return "已修复待复测"
    if status in ("triaged", "fixing"):
        return "处理中"
    return "未学习"


@kb_admin_bp.route("/ai-center/overview", methods=["GET"])
def api_ai_center_overview():
    """AI 中心核心看板：失败原因、学习状态、RAG 索引状态。"""
    from app.db import SessionLocal
    from sqlalchemy import text
    from app.services.bad_case_service import BadCaseStore

    bad_store = BadCaseStore()
    bad_cases = bad_store.load_all(limit=100000)
    open_cases = [c for c in bad_cases if c.get("status", "open") not in ("verified", "wont_fix")]
    failed_cases = []
    for c in open_cases[:20]:
        used_evidence = _safe_json_loads(c.get("used_evidence_json"), [])
        failed_cases.append({
            "id": c.get("id", ""),
            "status": c.get("status", "open"),
            "failure_type": c.get("failure_type", "unknown"),
            "scenario": c.get("scenario", ""),
            "customer_message": c.get("customer_message", ""),
            "ai_suggested_reply": c.get("ai_suggested_reply", ""),
            "root_cause": c.get("root_cause", "") or c.get("reject_reason", "") or c.get("auto_create_reason", ""),
            "fix_note": c.get("fix_note", ""),
            "learning_status": _summarize_bad_case_learning(c),
            "used_evidence": used_evidence,
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
        })

    failure_types = {}
    learning_summary = {"未学习": 0, "处理中": 0, "已修复待复测": 0, "已复测通过": 0}
    for c in bad_cases:
        failure_type = c.get("failure_type", "unknown")
        failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
        learning = _summarize_bad_case_learning(c)
        learning_summary[learning] = learning_summary.get(learning, 0) + 1

    db = SessionLocal()
    try:
        conn = db.connection()
        rag_rows = conn.execute(text("""
            SELECT
              e.id,
              e.title,
              e.status,
              e.index_status,
              e.updated_at,
              e.published_at,
              COUNT(c.id) AS chunk_count,
              SUM(CASE WHEN c.embedding_status = 'done' THEN 1 ELSE 0 END) AS embedded_count
            FROM knowledge_entries e
            LEFT JOIN knowledge_chunks c ON c.entry_id = e.id
            GROUP BY e.id
            ORDER BY e.updated_at DESC
            LIMIT 500
        """)).fetchall()

        rag_summary = {
            "published_total": 0,
            "ready": 0,
            "not_ready": 0,
            "failed": 0,
            "zero_chunk": 0,
            "draft_or_review": 0,
        }
        rag_issues = []
        recent_updates = []
        for row in rag_rows:
            entry = {
                "entry_id": row[0],
                "title": row[1],
                "status": row[2],
                "index_status": row[3],
                "updated_at": str(row[4]) if row[4] else "",
                "published_at": str(row[5]) if row[5] else "",
                "chunk_count": int(row[6] or 0),
                "embedded_count": int(row[7] or 0),
            }
            if entry["status"] == "published":
                rag_summary["published_total"] += 1
                if entry["index_status"] == "ready" and entry["chunk_count"] > 0:
                    rag_summary["ready"] += 1
                else:
                    rag_summary["not_ready"] += 1
                    if entry["index_status"] == "failed":
                        rag_summary["failed"] += 1
                    if entry["chunk_count"] == 0:
                        rag_summary["zero_chunk"] += 1
                    rag_issues.append({
                        **entry,
                        "issue": "已发布但 AI 检索还没同步好",
                    })
            else:
                rag_summary["draft_or_review"] += 1
            recent_updates.append(entry)

        feedback_rows = conn.execute(text("""
            SELECT customer_message, action, suggested_reply, final_reply, source, created_at
            FROM knowledge_feedback
            ORDER BY created_at DESC
            LIMIT 20
        """)).fetchall() if "knowledge_feedback" else []
    except Exception:
        rag_summary = {}
        rag_issues = []
        recent_updates = []
        feedback_rows = []
    finally:
        db.close()

    feedback_items = [
        {
            "customer_message": r[0],
            "action": r[1],
            "suggested_reply": r[2],
            "final_reply": r[3],
            "source": r[4],
            "created_at": str(r[5]) if r[5] else "",
        }
        for r in feedback_rows
    ]

    return jsonify({
        "summary": {
            "bad_case_total": len(bad_cases),
            "open_bad_case": len(open_cases),
            "rag_not_ready": rag_summary.get("not_ready", 0),
            "rag_failed": rag_summary.get("failed", 0),
            "rag_zero_chunk": rag_summary.get("zero_chunk", 0),
        },
        "failure_types": failure_types,
        "learning_summary": learning_summary,
        "failed_cases": failed_cases,
        "rag_summary": rag_summary,
        "rag_issues": rag_issues[:30],
        "recent_knowledge_updates": recent_updates[:30],
        "recent_feedback": feedback_items,
    })


@kb_admin_bp.route("/ai-center/bad-cases/<case_id>", methods=["GET"])
def api_ai_center_bad_case_detail(case_id):
    """Return one Bad Case for AI center detail view."""
    from app.services.bad_case_service import BadCaseStore

    case = BadCaseStore().get_by_id(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    return jsonify(case)


@kb_admin_bp.route("/ai-center/bad-cases/<case_id>", methods=["DELETE"])
def api_ai_center_bad_case_delete(case_id):
    """Delete a mistaken or obsolete Bad Case from AI center."""
    role, _ = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要主管或管理员权限"}), 403

    from app.services.bad_case_service import BadCaseStore

    deleted = BadCaseStore().delete(case_id)
    if not deleted:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "id": case_id})


@kb_admin_bp.route("/ai-center/rebuild-rag", methods=["POST"])
def api_ai_center_rebuild_rag():
    """重建已发布知识的检索索引。"""
    role, _ = _get_user_info()
    if not _require_supervisor(role):
        return jsonify({"error": "需要主管或管理员权限"}), 403
    try:
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
        result = KnowledgeIndexPipeline.rebuild_all()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============ Helpers ============

def _log_change_inline(
    db,
    target_type: str,
    target_id: int,
    target_title: str,
    action: str,
    performed_by: str,
    reason: str = "",
    before_status: str = "",
    after_status: str = "",
    changed_fields: list = None,
    snapshot: dict = None,
):
    """在当前 session 中写入 KBChangeLog（不 close db）"""
    from app.models.kb_tables import KBChangeLog
    entry = KBChangeLog(
        target_type=target_type,
        target_id=target_id,
        target_title=target_title,
        action=action,
        before_status=before_status,
        after_status=after_status,
        performed_by=performed_by or "",
        change_reason=reason,
    )
    if snapshot:
        entry.set_snapshot(snapshot)
    if changed_fields:
        entry.set_changed_fields(changed_fields)
    db.add(entry)
    db.commit()
