"""Auto-classify QA entries: scenario_category + issue_type + sop_id linking."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import SessionLocal
from app.models.kb_tables import KBQA, KBSOP, KBProduct
from sqlalchemy import func

# source_type -> scenario_category mapping
SOURCE_TO_SCENARIO = {
    "faq": "售前咨询",
    "shipping_policy": "物流发货",
    "install_guide": "安装指导",
    "aftersales_policy": "售后问题",
    "complaint": "投诉风险",
    "invoice": "发票与价保",
    "sales_pitch": "推销推荐",
    "platform_rules": "平台规则",
    "safety_warranty": "安全质保",
    "special_scenario": "特殊场景",
    "language_guide": "客服规范",
}

# keyword -> issue_type mapping
KEYWORD_TO_ISSUE = [
    (r"材质|板材|实木|塑料|钢管|铁|钢|木", "材质"),
    (r"尺寸|大小|长|宽|高|厘米|cm|占地面积", "尺寸"),
    (r"承重|承压|负重|重量|公斤|kg|斤", "承重"),
    (r"年龄|岁|月龄|宝宝|小孩|儿童|婴儿", "适用年龄"),
    (r"安装|组装|螺丝|说明书|安装视频|不会装", "安装"),
    (r"发货|快递|物流|什么时候发|多久到|催发", "物流时效"),
    (r"破损|坏了|碎了|裂了|断了|损坏", "破损"),
    (r"缺件|少了|漏发|缺少|配件不够", "缺件"),
    (r"投诉|差评|不满意|态度差|态度不好", "投诉"),
    (r"12315|消费者协会|工商|举报", "12315"),
    (r"赔偿|赔钱|补偿|赔多少|赔偿金额", "赔偿"),
    (r"退款|退钱|退货|不想要了|申请退款", "退款"),
    (r"平台介入|平台客服|小二|淘宝介入", "平台介入"),
    (r"媒体|曝光|律师|起诉|法院|法律", "法务风险"),
    (r"受伤|夹伤|磕碰|流血|宝宝受伤|安全", "安全事故"),
    (r"倒塌|坍塌|倒了|砸到|塌了", "倒塌"),
    (r"发票|开票|税点|增值税", "发票"),
    (r"保价|价保|降价|差价", "价保"),
    (r"推荐|搭配|一起买|组合|关联", "推荐"),
    (r"好评|晒图|五星|好评返现", "好评"),
]


def classify_issue_type(question, answer, keywords_text):
    """Classify issue_type based on question + answer + keywords."""
    text = f"{question} {answer} {keywords_text}"
    for pattern, issue in KEYWORD_TO_ISSUE:
        if re.search(pattern, text):
            return issue
    return "通用咨询"


def main():
    db = SessionLocal()

    # Build SOP keyword index for linking
    sop_list = db.query(KBSOP).filter(KBSOP.status == "published").all()
    sop_keywords = {}  # sop_id -> [keywords]
    for sop in sop_list:
        sop_keywords[sop.id] = sop.get_keywords()

    updated = 0
    linked_sop = 0

    all_qa = db.query(KBQA).all()
    for qa in all_qa:
        changed = False

        # 1. Set scenario_category from source_type
        if not qa.scenario_category:
            qa.scenario_category = SOURCE_TO_SCENARIO.get(qa.source_type, "售前咨询")
            changed = True

        # 2. Set issue_type from question/answer/keywords
        if not qa.issue_type:
            kw_text = " ".join(qa.get_keywords())
            qa.issue_type = classify_issue_type(qa.question, qa.answer, kw_text)
            changed = True

        # 3. Link to SOP by keyword matching
        if not qa.sop_id and qa.risk_level in ("high", "critical", "medium"):
            qa_text = f"{qa.question} {qa.answer}"
            for sop_id, keywords in sop_keywords.items():
                for kw in keywords:
                    if kw and kw in qa_text:
                        qa.sop_id = sop_id
                        linked_sop += 1
                        changed = True
                        break
                if qa.sop_id:
                    break

        if changed:
            updated += 1

    db.commit()

    print(f"Updated: {updated}")
    print(f"SOP linked: {linked_sop}")

    # Stats
    print(f"\n=== scenario_category distribution ===")
    for r in db.query(KBQA.scenario_category, func.count(KBQA.id)).group_by(KBQA.scenario_category).all():
        print(f"  {r[0]}: {r[1]}")

    print(f"\n=== issue_type distribution ===")
    for r in db.query(KBQA.issue_type, func.count(KBQA.id)).order_by(func.count(KBQA.id).desc()).limit(15).all():
        print(f"  {r[0]}: {r[1]}")

    print(f"\n=== SOP linking ===")
    with_sop = db.query(func.count(KBQA.id)).filter(KBQA.sop_id.isnot(None)).scalar()
    print(f"  QA with SOP: {with_sop}")

    db.close()


if __name__ == "__main__":
    main()
