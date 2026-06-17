"""将现有商品数据导入知识库作为初始数据"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal
from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.services.knowledge_index_service import KnowledgeIndexService

def seed_from_product_cards():
    db = SessionLocal()
    try:
        with open("../product_knowledge/product_cards.json", "r", encoding="utf-8") as f:
            products = json.load(f)

        count = 0
        for p in products[:50]:  # 先导入前50条作为示例
            name = p.get("product_name", "")
            if not name:
                continue
            sku_list = p.get("sku_summary", {}).get("sku_list", [])
            sku_names = ", ".join([s.get("sku_name", "") for s in sku_list[:3]])

            content_parts = [f"商品名称：{name}"]
            if p.get("category"):
                content_parts.append(f"分类：{p['category']}")
            if p.get("brand"):
                content_parts.append(f"品牌：{p['brand']}")
            if sku_names:
                content_parts.append(f"SKU：{sku_names}")
            if p.get("main_image"):
                content_parts.append(f"图片：{p['main_image']}")

            entry = KnowledgeEntryRepository.create(
                source_type="product_facts",
                title=name,
                content="\n".join(content_parts),
                intent="product_question",
                product_scope=[name],
                auto_reply_allowed=True,
                human_review_required=False,
                created_by="system_seed",
            )
            # 直接发布
            KnowledgeEntryRepository.submit_for_review(entry.id, user="system_seed")
            KnowledgeIndexService.on_publish(entry.id, user="system_seed")
            count += 1

        print(f"成功导入 {count} 条商品知识到知识库")
    except Exception as e:
        print(f"导入失败: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_from_product_cards()
