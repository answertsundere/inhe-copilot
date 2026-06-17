"""
一次性脚本：重新计算所有 kb_product 的完整度。
用途：完整度算法更新后，给已有商品重新打分，无需逐条编辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.db import SessionLocal
from app.models.kb_tables import KBProduct
from app.repositories.kb_product_repository import _compute_completeness


def main():
    db = SessionLocal()
    try:
        products = db.query(KBProduct).all()
        updated = 0
        for p in products:
            score, missing = _compute_completeness(p)
            p.completeness_score = round(score * 100, 1)
            p.set_missing_fields(missing)
            updated += 1
        db.commit()
        print(f"已更新 {updated} 条商品的完整度")
    except Exception as e:
        db.rollback()
        print(f"更新失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
