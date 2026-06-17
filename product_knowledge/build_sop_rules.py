"""
从 基础培训.txt 和 基础规则.docx 生成结构化知识库：
- copilot/knowledge/sop_scenarios.yaml
- copilot/rules/platform_rules.yaml
- copilot/rules/escalation_rules.yaml
- copilot/rules/qa_checklist.yaml
"""

import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

OUT_SOP = os.path.join(PROJECT_ROOT, "copilot", "knowledge", "sop_scenarios.yaml")
OUT_PLATFORM = os.path.join(PROJECT_ROOT, "copilot", "rules", "platform_rules.yaml")
OUT_ESCALATION = os.path.join(PROJECT_ROOT, "copilot", "rules", "escalation_rules.yaml")
OUT_QA = os.path.join(PROJECT_ROOT, "copilot", "rules", "qa_checklist.yaml")

SRC_TRAINING = os.path.join(SCRIPT_DIR, "基础培训.txt")
SRC_RULES_DOCX = os.path.join(SCRIPT_DIR, "基础规则.docx")


def _load_training_txt(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _load_docx(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        from docx import Document
        doc = Document(path)
        return [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    except Exception as e:
        print(f"[警告] 读取 docx 失败: {e}")
        return []


def _split_sections(text: str) -> list:
    """按 markdown 标题拆分段落"""
    lines = text.split("\n")
    sections = []
    current = {"title": "", "lines": [], "level": 0}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            if current["lines"]:
                sections.append(current)
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            current = {"title": title, "lines": [], "level": level}
        else:
            current["lines"].append(stripped)
    if current["lines"]:
        sections.append(current)
    return sections


def _classify_scenario(title: str, content: str) -> str:
    text = (title + " " + " ".join(content)).lower()
    if any(k in text for k in ["发货", "物流", "快递", "运输", "签收", "派送", "揽收", "配送"]):
        return "shipping"
    if any(k in text for k in ["退", "换", "售后", "保修", "维修", "补偿", "赔偿", "退款", "退货", "拒收"]):
        return "refund"
    if any(k in text for k in ["材质", "尺寸", "规格", "颜色", "安装", "使用", "功能", "重量", "气味", "承重", "容量"]):
        return "product_consult"
    if any(k in text for k in ["投诉", "12315", "差评", "曝光", "媒体", "工商", "律师", "起诉", "法院", "举报", "威胁"]):
        return "complaint"
    if any(k in text for k in ["破损", "质量", "瑕疵", "划痕", "开裂", "变形", "掉漆", "生锈", "坏", "次品", "不合格"]):
        return "quality_issue"
    if any(k in text for k in ["价格", "优惠", "活动", "券", "满减", "折扣", "降价", "保价", "差价", "赠品", "红包", "秒杀", "促销"]):
        return "price_promotion"
    if any(k in text for k in ["售前", "咨询", "推荐", "介绍", "选购", "购买", "下单", "付款", "支付"]):
        return "pre_sales"
    if any(k in text for k in ["质检", "检查", "审核", "合规", "违规", "红线", "底线", "规范", "标准", "要求", "守则", "制度", "条例", "准则", "规章", "规定", "规范", "规范", "规范"]):
        return "qa"
    return "general"


def _extract_steps(lines: list) -> list:
    """提取步骤（数字开头或·/-开头）"""
    steps = []
    for line in lines:
        if re.match(r"^\d+[\.、)）\s]", line) or re.match(r"^[·\-\*]\s", line):
            steps.append(re.sub(r"^\d+[\.、)）\s]\s*", "", line).strip())
    if not steps and len(lines) > 0:
        # 无明确步骤时，取前3个非空句作为步骤
        for line in lines:
            if len(line) > 10 and line not in steps:
                steps.append(line)
            if len(steps) >= 5:
                break
    return steps[:8]


def _extract_forbidden(lines: list) -> list:
    """提取禁止行为"""
    forbidden = []
    for line in lines:
        if any(k in line for k in ["禁止", "严禁", "不得", "不能", "不可以", "不许", "勿", "不要", "绝不", "千万不要"]):
            # 提取整句或片段
            s = re.split(r"[。；;!！]", line)
            for part in s:
                if any(k in part for k in ["禁止", "严禁", "不得", "不能", "不可以", "不许", "勿", "不要", "绝不", "千万不要"]):
                    p = part.strip()
                    if len(p) > 3 and p not in forbidden:
                        forbidden.append(p)
    return forbidden[:10]


def _extract_escalation_triggers(lines: list) -> list:
    """提取升级触发条件"""
    triggers = []
    for line in lines:
        if any(k in line for k in ["升级", "主管", "经理", "领导", "上报", "转交", "转接", "移交", "投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报", "威胁", "差评", "赔偿", "假", "骗", "欺诈", "虚假宣传"]):
            s = re.split(r"[。；;!！]", line)
            for part in s:
                if any(k in part for k in ["升级", "主管", "经理", "领导", "上报", "转交", "转接", "移交"]):
                    p = part.strip()
                    if len(p) > 3 and p not in triggers:
                        triggers.append(p)
    return triggers[:8]


def _infer_risk_level(title: str, content: str) -> str:
    text = (title + " " + content).lower()
    high_kw = ["投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报", "威胁", "差评", "赔偿", "假", "骗", "欺诈", "虚假宣传", "严重", "重大", "紧急", "危险"]
    medium_kw = ["退", "换", "售后", "质量", "破损", "少发", "漏发", "错发", "未收到", "丢件", "催", "慢", "延迟", "纠纷", "争议", "矛盾"]
    for kw in high_kw:
        if kw in text:
            return "high"
    for kw in medium_kw:
        if kw in text:
            return "medium"
    return "low"


def _build_sops(sections: list, docx_paras: list) -> list:
    sops = []
    used_titles = set()

    # 从培训文本提取
    for sec in sections:
        title = sec["title"]
        content = "\n".join(sec["lines"])
        if len(content) < 30:
            continue
        scenario_type = _classify_scenario(title, sec["lines"])
        if scenario_type == "qa":
            continue  # QA 单独处理
        steps = _extract_steps(sec["lines"])
        forbidden = _extract_forbidden(sec["lines"])
        escalation = _extract_escalation_triggers(sec["lines"])
        risk = _infer_risk_level(title, content)

        sid = f"sop_{scenario_type}_{len(sops)+1:03d}"
        sops.append({
            "id": sid,
            "intent": scenario_type,
            "scenario": title,
            "risk_level": risk,
            "steps": steps,
            "required_checks": [],
            "required_customer_info": [],
            "forbidden_claims": forbidden,
            "escalation_triggers": escalation,
            "suggested_reply_style": "温和专业" if risk == "low" else ("诚恳安抚" if risk == "medium" else "谨慎处理"),
            "source_file": "基础培训.txt",
        })
        used_titles.add(title)

    # 从 docx 提取（作为补充）
    buf = []
    buf_title = ""
    for para in docx_paras:
        if len(para) < 15 and (para.endswith("：") or para.endswith(":") or not buf):
            if buf:
                content = "\n".join(buf)
                scenario_type = _classify_scenario(buf_title, buf)
                if scenario_type != "qa" and buf_title not in used_titles and len(content) > 30:
                    steps = _extract_steps(buf)
                    forbidden = _extract_forbidden(buf)
                    escalation = _extract_escalation_triggers(buf)
                    risk = _infer_risk_level(buf_title, content)
                    sid = f"sop_{scenario_type}_{len(sops)+1:03d}"
                    sops.append({
                        "id": sid,
                        "intent": scenario_type,
                        "scenario": buf_title,
                        "risk_level": risk,
                        "steps": steps,
                        "required_checks": [],
                        "required_customer_info": [],
                        "forbidden_claims": forbidden,
                        "escalation_triggers": escalation,
                        "suggested_reply_style": "温和专业" if risk == "low" else ("诚恳安抚" if risk == "medium" else "谨慎处理"),
                        "source_file": "基础规则.docx",
                    })
                    used_titles.add(buf_title)
            buf_title = para.rstrip("：:")
            buf = []
        else:
            buf.append(para)
    if buf:
        content = "\n".join(buf)
        scenario_type = _classify_scenario(buf_title, buf)
        if scenario_type != "qa" and buf_title not in used_titles and len(content) > 30:
            steps = _extract_steps(buf)
            forbidden = _extract_forbidden(buf)
            escalation = _extract_escalation_triggers(buf)
            risk = _infer_risk_level(buf_title, content)
            sid = f"sop_{scenario_type}_{len(sops)+1:03d}"
            sops.append({
                "id": sid,
                "intent": scenario_type,
                "scenario": buf_title,
                "risk_level": risk,
                "steps": steps,
                "required_checks": [],
                "required_customer_info": [],
                "forbidden_claims": forbidden,
                "escalation_triggers": escalation,
                "suggested_reply_style": "温和专业" if risk == "low" else ("诚恳安抚" if risk == "medium" else "谨慎处理"),
                "source_file": "基础规则.docx",
            })

    return sops


def _build_platform_rules(sections: list, docx_paras: list) -> list:
    rules = []
    seen = set()
    for sec in sections:
        for line in sec["lines"]:
            if any(k in line for k in ["禁止", "严禁", "不得", "不可以", "不许", "红线", "底线", "违规", "处罚", "罚款", "扣分", "降权", "封店", "拉黑"]):
                parts = re.split(r"[。；;!！\n]", line)
                for p in parts:
                    p = p.strip()
                    if len(p) > 5 and p not in seen:
                        rules.append({
                            "id": f"pr_{len(rules)+1:03d}",
                            "category": "平台规则",
                            "rule": p,
                            "severity": "high" if any(k in p for k in ["红线", "底线", "严禁", "封店", "拉黑", "罚款", "处罚"]) else "medium",
                            "source": "基础培训.txt",
                        })
                        seen.add(p)
    for para in docx_paras:
        if any(k in para for k in ["禁止", "严禁", "不得", "不可以", "不许", "红线", "底线", "违规"]):
            parts = re.split(r"[。；;!！\n]", para)
            for p in parts:
                p = p.strip()
                if len(p) > 5 and p not in seen:
                    rules.append({
                        "id": f"pr_{len(rules)+1:03d}",
                        "category": "平台规则",
                        "rule": p,
                        "severity": "high" if any(k in p for k in ["红线", "底线", "严禁"]) else "medium",
                        "source": "基础规则.docx",
                    })
                    seen.add(p)
    return rules[:80]


def _build_escalation_rules(sections: list, docx_paras: list) -> list:
    rules = []
    seen = set()
    for sec in sections:
        for line in sec["lines"]:
            if any(k in line for k in ["升级", "主管", "经理", "领导", "上报", "转交", "转接", "移交", "投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报", "威胁", "差评", "赔偿", "假", "骗", "欺诈", "虚假宣传", "严重", "重大", "紧急"]):
                parts = re.split(r"[。；;!！\n]", line)
                for p in parts:
                    p = p.strip()
                    if len(p) > 5 and p not in seen and any(k in p for k in ["升级", "主管", "经理", "领导", "上报", "转交", "转接", "移交", "投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报"]):
                        rules.append({
                            "id": f"er_{len(rules)+1:03d}",
                            "scenario": "投诉/高风险",
                            "trigger": p,
                            "action": "立即转交主管处理",
                            "source": "基础培训.txt",
                        })
                        seen.add(p)
    for para in docx_paras:
        if any(k in para for k in ["升级", "主管", "经理", "领导", "上报", "转交", "转接", "移交"]):
            parts = re.split(r"[。；;!！\n]", para)
            for p in parts:
                p = p.strip()
                if len(p) > 5 and p not in seen:
                    rules.append({
                        "id": f"er_{len(rules)+1:03d}",
                        "scenario": "投诉/高风险",
                        "trigger": p,
                        "action": "立即转交主管处理",
                        "source": "基础规则.docx",
                    })
                    seen.add(p)
    return rules[:50]


def _build_qa_checklist(sections: list, docx_paras: list) -> list:
    checklist = [
        {"id": "qa_001", "category": "安抚情绪", "check": "回复是否安抚了客户情绪", "weight": 10, "auto_checkable": False},
        {"id": "qa_002", "category": "信息核实", "check": "是否核实了订单/物流/售后信息", "weight": 15, "auto_checkable": False},
        {"id": "qa_003", "category": "禁止承诺", "check": "是否承诺了具体发货/到货时间", "weight": 20, "auto_checkable": True, "keywords": ["今天一定发", "明天一定到", "马上", "立刻", "保证", "肯定"]},
        {"id": "qa_004", "category": "禁止承诺", "check": "是否承诺了赔偿/退款金额", "weight": 20, "auto_checkable": True, "keywords": ["一定赔", "一定退", "全额退", "免费补", "赔偿", "退款"]},
        {"id": "qa_005", "category": "平台合规", "check": "是否引导客户线下交易", "weight": 25, "auto_checkable": True, "keywords": ["微信", "支付宝", "私下", "线下", "转账", "扫码", "加QQ", "加V", "电话", "私下联系"]},
        {"id": "qa_006", "category": "礼貌用语", "check": "是否使用了不礼貌或攻击性语言", "weight": 20, "auto_checkable": True, "keywords": ["傻", "蠢", "笨", "滚", "神经病", "脑子", "有病", "他妈", "去死", "垃圾", "骗子", "不要脸"]},
        {"id": "qa_007", "category": "升级动作", "check": "高风险场景是否遗漏升级/上报动作", "weight": 15, "auto_checkable": False},
        {"id": "qa_008", "category": "产品参数", "check": "L0/L1 产品是否做了确定性参数承诺", "weight": 10, "auto_checkable": False},
    ]
    # 从源文件补充
    seen = {c["check"] for c in checklist}
    for sec in sections:
        if "质检" in sec["title"] or "检查" in sec["title"] or "审核" in sec["title"] or "QA" in sec["title"]:
            for line in sec["lines"]:
                if len(line) > 8 and line not in seen:
                    checklist.append({
                        "id": f"qa_{len(checklist)+1:03d}",
                        "category": "文本提取",
                        "check": line,
                        "weight": 5,
                        "auto_checkable": False,
                    })
                    seen.add(line)
    return checklist[:30]


def _write_yaml(path: str, data: dict):
    import yaml
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def main():
    print("=" * 60)
    print("Build SOP & Rules")
    print("=" * 60)

    training_text = _load_training_txt(SRC_TRAINING)
    docx_paras = _load_docx(SRC_RULES_DOCX)

    print(f"  培训文本: {len(training_text)} 字符")
    print(f"  规则文档段落: {len(docx_paras)} 段")

    sections = _split_sections(training_text)
    print(f"  培训文本章节: {len(sections)} 个")

    # SOP
    sops = _build_sops(sections, docx_paras)
    _write_yaml(OUT_SOP, {"scenarios": sops, "meta": {"count": len(sops), "source": "基础培训.txt+基础规则.docx"}})
    print(f"[OK] SOP 场景: {len(sops)} -> {OUT_SOP}")

    # Platform rules
    prules = _build_platform_rules(sections, docx_paras)
    _write_yaml(OUT_PLATFORM, {"rules": prules, "meta": {"count": len(prules)}})
    print(f"[OK] 平台规则: {len(prules)} -> {OUT_PLATFORM}")

    # Escalation rules
    erules = _build_escalation_rules(sections, docx_paras)
    _write_yaml(OUT_ESCALATION, {"rules": erules, "meta": {"count": len(erules)}})
    print(f"[OK] 升级规则: {len(erules)} -> {OUT_ESCALATION}")

    # QA checklist
    qa = _build_qa_checklist(sections, docx_paras)
    _write_yaml(OUT_QA, {"checklist": qa, "meta": {"count": len(qa)}})
    print(f"[OK] 质检清单: {len(qa)} -> {OUT_QA}")

    print("=" * 60)


if __name__ == "__main__":
    main()
