"""
商品知识库仓库 - CRUD / 列表过滤 / 完整度计算 / 状态流转 / 变更日志
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_, func, exists as sa_exists

from app.db import SessionLocal
from app.models.kb_tables import KBProduct, KBQA, KBChangeLog


# ─── 完整度字段定义 ───
# 等权检查每个关键字段是否已有效填写；避免 "specs" 整组因空对象被误判为完成。
_COMPLETENESS_FIELDS = [
    ("product_name", "商品名", None),
    ("brand", "品牌", None),
    ("category_l1", "一级类目", None),
    ("category_l2", "二级类目", None),
    ("category_l3", "三级类目", None),
    ("sku_list", "SKU列表", "get_sku_list"),
    ("specs.material", "材质", "get_specs"),
    ("specs.size", "尺寸", "get_specs"),
    ("specs.load_capacity", "承重/容量", "get_specs"),
    ("specs.age_range", "适用年龄", "get_specs"),
    ("specs.accessories", "配件清单", "get_specs"),
    ("specs.install_method", "安装方式", "get_specs"),
    ("specs.detachable", "是否可拆卸", "get_specs"),
    ("specs.drill_required", "是否打孔", "get_specs"),
    ("specs.pinch_safety", "安全/防夹说明", "get_specs"),
    ("specs.certification_report", "合格证/质检资料", "get_specs"),
    ("warranty.period", "质保期", "get_warranty"),
    ("logistics.attribute", "物流属性", "get_logistics"),
]

# 视为未填写的占位符（人工习惯填写的无意义值）
_USELESS_VALUES = {"-", "--", "无", "暂无", "详见商品详情页", "见详情页"}


def _is_useful(value) -> bool:
    """判断一个字段值是否算已有效填写。"""
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    text = str(value).strip()
    if not text:
        return False
    return text not in _USELESS_VALUES


def _get_field_value(product: KBProduct, key: str, getter_name: Optional[str]):
    """根据字段定义取值。key 支持点号路径（如 specs.material）。"""
    if getter_name is None:
        return getattr(product, key, None)
    container = getattr(product, getter_name)()
    # key 本身就是 JSON 字段本身（如 sku_list），直接返回容器
    if "." not in key:
        return container
    if not isinstance(container, dict):
        return None
    parts = key.split(".", 1)
    return container.get(parts[1])


def _compute_completeness(product: KBProduct) -> tuple:
    """计算商品完整度得分和缺失字段列表。返回 (score, missing_fields)"""
    total = len(_COMPLETENESS_FIELDS)
    if total == 0:
        return 1.0, []

    filled = 0
    missing = []
    for key, label, getter_name in _COMPLETENESS_FIELDS:
        value = _get_field_value(product, key, getter_name)
        if _is_useful(value):
            filled += 1
        else:
            missing.append(label)

    score = filled / total
    return round(score, 4), missing


class KBProductRepository:
    """商品知识库仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBProduct:
        db = SessionLocal()
        try:
            product = KBProduct(**kwargs)
            # 计算 completeness
            db.add(product)
            db.flush()  # 让 defaults 生效后再计算
            score, missing = _compute_completeness(product)
            product.completeness_score = round(score * 100, 1)
            product.set_missing_fields(missing)
            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="create",
                after_status=product.status, performed_by=product.created_by,
                snapshot=product.to_dict(detail=True),
                reason="新建商品知识",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(product_id: int) -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            return db.query(KBProduct).filter(KBProduct.id == product_id).first()
        finally:
            db.close()

    @staticmethod
    def get_by_iid(i_id: str) -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            return db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
        finally:
            db.close()

    # ─── 更新 ───

    @staticmethod
    def update(product_id: int, updates: dict, updated_by: str = "") -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
            if not product:
                return None

            allowed_fields = {
                "i_id", "product_name", "brand",
                "category_l1", "category_l2", "category_l3",
                "status", "import_batch_id",
            }
            json_setters = {
                "sku_list": "set_sku_list",
                "specs": "set_specs",
                "logistics": "set_logistics",
                "warranty": "set_warranty",
            }

            changed = []
            for k, v in updates.items():
                if k.startswith("_"):
                    continue
                if k in json_setters:
                    getattr(product, json_setters[k])(v)
                    changed.append(k)
                elif k in allowed_fields:
                    setattr(product, k, v)
                    changed.append(k)

            product.updated_by = updated_by or product.updated_by
            product.updated_at = datetime.utcnow()

            # 重算完整度
            score, missing = _compute_completeness(product)
            product.completeness_score = round(score * 100, 1)
            product.set_missing_fields(missing)

            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="update",
                before_status=product.status, after_status=product.status,
                performed_by=updated_by, changed_fields=changed,
                snapshot=product.to_dict(detail=True),
                reason="更新商品知识",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        category_l1: str = "",
        category_l2: str = "",
        category_l3: str = "",
        search: str = "",
        status: str = "",
        agent_usable: str = "",
        has_qa: str = "",
        missing_field: str = "",
        high_risk: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBProduct)
            if category_l1:
                q = q.filter(KBProduct.category_l1 == category_l1)
            if category_l2:
                q = q.filter(KBProduct.category_l2 == category_l2)
            if category_l3:
                q = q.filter(KBProduct.category_l3 == category_l3)
            if status:
                q = q.filter(KBProduct.status == status)
            if search:
                like = f"%{search}%"
                q = q.filter(
                    or_(
                        KBProduct.product_name.ilike(like),
                        KBProduct.brand.ilike(like),
                        KBProduct.i_id.ilike(like),
                    )
                )

            # Agent 可用性筛选（与 api_list_products 中的 can_agent_use 逻辑一致）
            if agent_usable:
                high_risk_qa = (
                    db.query(KBQA.id)
                    .filter(KBQA.product_id == KBProduct.id)
                    .filter(KBQA.risk_level.in_(["high", "critical"]))
                )
                if agent_usable == "yes":
                    q = q.filter(
                        KBProduct.status == "published",
                        KBProduct.completeness_score >= 60,
                        ~high_risk_qa.exists(),
                    )
                elif agent_usable == "no":
                    q = q.filter(
                        or_(
                            KBProduct.status != "published",
                            KBProduct.completeness_score < 60,
                            high_risk_qa.exists(),
                        )
                    )

            # 是否有关联 QA
            if has_qa:
                qa_any = db.query(KBQA.id).filter(KBQA.product_id == KBProduct.id)
                if has_qa == "yes":
                    q = q.filter(qa_any.exists())
                elif has_qa == "no":
                    q = q.filter(~qa_any.exists())

            # 完整度筛选
            if missing_field == "incomplete":
                q = q.filter(KBProduct.completeness_score < 60)

            # 高风险商品（关联高/极高风险 QA）
            if high_risk:
                high_risk_qa = (
                    db.query(KBQA.id)
                    .filter(KBQA.product_id == KBProduct.id)
                    .filter(KBQA.risk_level.in_(["high", "critical"]))
                )
                if high_risk == "yes":
                    q = q.filter(high_risk_qa.exists())
                elif high_risk == "no":
                    q = q.filter(~high_risk_qa.exists())

            total = q.count()
            items = (
                q.order_by(KBProduct.updated_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 状态流转 ───

    @staticmethod
    def submit_for_review(product_id: int, user: str = "") -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
            if not product:
                return None
            if product.status != "draft":
                raise ValueError(f"当前状态 {product.status} 不允许提交审核，仅 draft 可提交")

            old_status = product.status
            product.status = "pending_review"
            product.updated_by = user
            product.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="submit_review",
                before_status=old_status, after_status="pending_review",
                performed_by=user, reason="商品提交审核",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def approve(product_id: int, user: str = "") -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
            if not product:
                return None
            if product.status != "pending_review":
                raise ValueError(f"当前状态 {product.status} 不允许审核通过，仅 pending_review 可操作")

            old_status = product.status
            product.status = "published"
            product.version += 1
            product.updated_by = user
            product.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="approve",
                before_status=old_status, after_status="published",
                performed_by=user, reason="商品审核通过并发布",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def reject(product_id: int, user: str = "", reason: str = "") -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
            if not product:
                return None
            if product.status != "pending_review":
                raise ValueError(f"当前状态 {product.status} 不允许驳回")

            old_status = product.status
            product.status = "draft"
            product.updated_by = user
            product.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="reject",
                before_status=old_status, after_status="draft",
                performed_by=user, reason=f"商品审核驳回: {reason}",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def archive(product_id: int, user: str = "") -> Optional[KBProduct]:
        db = SessionLocal()
        try:
            product = db.query(KBProduct).filter(KBProduct.id == product_id).first()
            if not product:
                return None
            if product.status == "archived":
                return product

            old_status = product.status
            product.status = "archived"
            product.updated_by = user
            product.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(product)

            _log_change(
                db, target_type="kb_product", target_id=product.id,
                target_title=product.product_name, action="archive",
                before_status=old_status, after_status="archived",
                performed_by=user, reason="商品归档",
            )
            return product
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 统计 ───

    @staticmethod
    def get_category_stats() -> list:
        """获取品类维度的商品统计"""
        db = SessionLocal()
        try:
            rows = (
                db.query(
                    KBProduct.category_l1,
                    KBProduct.status,
                    func.count(KBProduct.id),
                    func.avg(KBProduct.completeness_score),
                )
                .group_by(KBProduct.category_l1, KBProduct.status)
                .all()
            )
            return [
                {
                    "category_l1": r[0],
                    "status": r[1],
                    "count": r[2],
                    "avg_completeness": round(float(r[3] or 0), 4),
                }
                for r in rows
            ]
        finally:
            db.close()


# ─── 内部变更日志辅助 ───

def _log_change(
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
