"""
从 话术.xlsx 生成 copilot/knowledge/reply_templates.json
"""

import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "copilot", "knowledge", "reply_templates.json")
XLSX_PATH = os.path.join(SCRIPT_DIR, "话术.xlsx")


def _load_excel(path: str):
    try:
        import openpyxl
    except ImportError:
        print("[错误] 缺少 openpyxl，请安装: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    data = rows[1:]
    return headers, data


def _heuristic_columns(headers: list) -> dict:
    """启发式识别列含义"""
    mapping = {"title": None, "template": None, "tags": None, "image": None, "metadata": []}
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if mapping["title"] is None and any(k in h_lower for k in ["标题", "名称", "场景", "问题", "类型", "分类", "name", "title"]):
            mapping["title"] = i
        elif mapping["template"] is None and any(k in h_lower for k in ["话术", "回复", "模板", "回答", "内容", "template", "content", "reply"]):
            mapping["template"] = i
        elif mapping["tags"] is None and any(k in h_lower for k in ["标签", "分类", "tag", "category", "类型"]):
            mapping["tags"] = i
        elif mapping["image"] is None and any(k in h_lower for k in ["图片", "image", "图", "photo"]):
            mapping["image"] = i
        else:
            mapping["metadata"].append(i)
    # 兜底
    if mapping["title"] is None:
        mapping["title"] = 0
    if mapping["template"] is None:
        mapping["template"] = 1 if len(headers) > 1 else 0
    if mapping["tags"] is None and len(headers) > 2:
        mapping["tags"] = 2
    return mapping


def _infer_intent(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["发货", "物流", "快递", "签收", "运输", "派送"]):
        return "shipping"
    if any(k in t for k in ["退", "换", "售后", "保修", "维修", "补偿", "赔偿"]):
        return "refund"
    if any(k in t for k in ["材质", "尺寸", "规格", "颜色", "安装", "使用", "功能", "重量", "高度", "气味", "味道", "甲醛", "承重", "容量", "升降"]):
        return "product_consult"
    if any(k in t for k in ["投诉", "12315", "差评", "曝光", "媒体", "工商", "律师", "起诉", "法院", "举报", "威胁", "欺骗", "骗子", "虚假宣传"]):
        return "complaint"
    if any(k in t for k in ["破损", "质量", "瑕疵", "划痕", "开裂", "变形", "掉漆", "生锈", "坏", "差", "不合格", "次品"]):
        return "quality_issue"
    if any(k in t for k in ["价格", "优惠", "活动", "券", "满减", "折扣", "降价", "保价", "差价", "赠品", "红包", "秒杀", "促销"]):
        return "price_promotion"
    if any(k in t for k in ["发票", "收据", "凭证", "单据"]):
        return "invoice"
    if any(k in t for k in ["改地址", "地址", "改电话", "电话", "改信息", "信息", "备注"]):
        return "modify_info"
    if any(k in t for k in ["取消", "不要", "拦截", "拒收"]):
        return "cancel_order"
    return "general"


def _infer_risk_level(title: str, template: str) -> str:
    text = (title + " " + template).lower()
    high_kw = ["投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报", "威胁", "差评", "赔偿", "假", "骗", "虚假宣传", "欺诈"]
    medium_kw = ["退", "换", "售后", "质量", "破损", "少发", "漏发", "错发", "未收到", "丢件", "催", "慢", "延迟"]
    for kw in high_kw:
        if kw in text:
            return "high"
    for kw in medium_kw:
        if kw in text:
            return "medium"
    return "low"


def _extract_forbidden(template: str) -> list:
    """从话术中提取禁止表述（简单启发式）"""
    forbidden = []
    patterns = [
        r"一定[^，。]*发", r"保证[^，。]*到", r"肯定[^，。]*到", r"马上[^，。]*发",
        r"立刻[^，。]*发", r"绝对[^，。]*没有", r"百分百", r"100%", r"不可能[^，。]*坏",
        r"不可能[^，。]*塌", r"不可能[^，。]*倒", r"绝不会", r"肯定不会",
    ]
    for p in patterns:
        if re.search(p, template):
            m = re.search(p, template).group(0)
            if m not in forbidden:
                forbidden.append(m)
    return forbidden


def _split_tags(tag_text: str) -> list:
    if not tag_text:
        return []
    return [t.strip() for t in re.split(r"[,，/|;\\\s]+", str(tag_text)) if t.strip()]


def main():
    print("=" * 60)
    print("Build Reply Templates")
    print("=" * 60)

    if not os.path.exists(XLSX_PATH):
        print(f"[警告] 源文件不存在: {XLSX_PATH}")
        # 输出空文件
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"templates": [], "meta": {"source": "话术.xlsx", "count": 0, "error": "source missing"}}, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已写入空文件: {OUTPUT_PATH}")
        return

    headers, data = _load_excel(XLSX_PATH)
    print(f"  列名: {headers}")
    print(f"  数据行: {len(data)}")

    cols = _heuristic_columns(headers)
    print(f"  列映射: title={cols['title']}, template={cols['template']}, tags={cols['tags']}, image={cols['image']}")

    templates = []
    for row_idx, row in enumerate(data, start=2):
        title = str(row[cols["title"]]).strip() if cols["title"] is not None and cols["title"] < len(row) and row[cols["title"]] else ""
        template = str(row[cols["template"]]).strip() if cols["template"] is not None and cols["template"] < len(row) and row[cols["template"]] else ""
        if not title and not template:
            continue
        tags_raw = str(row[cols["tags"]]).strip() if cols["tags"] is not None and cols["tags"] < len(row) and row[cols["tags"]] else ""
        image = str(row[cols["image"]]).strip() if cols["image"] is not None and cols["image"] < len(row) and row[cols["image"]] else ""

        tags = _split_tags(tags_raw)
        intent = _infer_intent(title)
        risk_level = _infer_risk_level(title, template)
        forbidden = _extract_forbidden(template)

        meta = {}
        for mi in cols["metadata"]:
            if mi < len(row) and row[mi] is not None:
                meta[headers[mi]] = str(row[mi]).strip()

        templates.append({
            "id": f"tpl_{row_idx:04d}",
            "intent": intent,
            "scenario": title,
            "risk_level": risk_level,
            "channel": "通用",
            "platform": tags[0] if tags else "通用",
            "template": template,
            "required_actions": [],
            "forbidden_phrases": forbidden,
            "tags": tags,
            "source_file": "话术.xlsx",
            "source_sheet": "Sheet1",
            "row_number": row_idx,
            "metadata": meta,
            "image_url": image if image and image.startswith("http") else "",
        })

    result = {
        "templates": templates,
        "meta": {
            "source": "话术.xlsx",
            "count": len(templates),
            "generated_at": __import__('datetime').datetime.now().isoformat(),
        }
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] 生成 {len(templates)} 条话术模板 -> {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
