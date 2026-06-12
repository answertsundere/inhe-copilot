"""
商品知识库仓库 - CRUD / 列表过滤 / 完整度计算 / 状态流转 / 变更日志
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_, func

from app.db import SessionLocal
from app.models.kb_tables import KBProduct, KBChangeLog


# ─── 完整度权重表 ───
_COMPLETENESS_WEIGHTS = {
    "product_name": 0.10,
    "brand": 0.05,
    "category_l1": 0.05,
    "category_l2": 0.05,
    "category_l3": 0.05,
    "sku_list": 0.15,
    "specs": 0.20,
    "logistics": 0.15,
    "warranty": 0.10,
    "image_url": 0.10,
}

# JSON 字段与 getter 的对应关系
_JSON_FIELD_GETTERS = {
    "sku_list": ("sku_list_json", "get_sku_list"),
    "specs": ("specs_json", "get_specs"),
    "logistics": ("logistics_json", "get_logistics"),
    "warranty": ("warranty_json", "get_warranty"),
}


def _compute_completeness(product: KBProduct) -> tuple:
    """计算商品完整度得分和缺失字段列表。返回 (score, missing_fields)"""
    score = 0.0
    missing = []

    for field, weight in _COMPLETENESS_WEIGHTS.items():
        if field in _JSON_FIELD_GETTERS:
            col_name, getter_name = _JSON_FIELD_GETTERS[field]
            getter = getattr(product, getter_name)
            value = getter()
            if value and value != [] and value != {}:
                score += weight
            else:
                missing.append(field)
        else:
            value = getattr(product, field, None)
            if value and str(value).strip():
                score += weight
            else:
                missing.append(field)

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
