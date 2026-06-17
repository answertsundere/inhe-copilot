"""
从编译后的 customer_service_graph 自动导出 Mermaid 流程图和文档。

用法:
    python scripts/export_customer_service_graph.py
"""

import os
import sys
import subprocess
import textwrap

# 把项目根目录加入路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "docs", "agent")

# 节点中文显示名（Mermaid 图中显示的中文）
NODE_LABELS = {
    "normalize_input": "输入清洗",
    "detect_intent": "意图识别",
    "risk_check": "风险检测",
    "build_base_context": "构建上下文",
    "route_by_intent": "意图路由",
    "query_jst_order": "查聚水潭订单",
    "query_local_order_fallback": "本地订单降级",
    "check_shipment_status": "检查发货状态",
    "match_order_products": "匹配订单商品",
    "match_product_from_message": "消息匹配商品",
    "match_shipping_policy": "匹配物流政策",
    "generate_reply": "生成回复",
    "quality_guard": "质量守卫",
    "human_review_gate": "人工复核门",
}

# 业务条件标签映射（让非技术人员也能看懂边）
CONDITION_LABELS = {
    ("route_by_intent", "query_jst_order"): "物流意图 & 有订单号",
    ("route_by_intent", "match_product_from_message"): "非物流 或 无订单号",
    ("query_jst_order", "query_local_order_fallback"): "JST 查询后降级本地",
    ("query_local_order_fallback", "check_shipment_status"): "检查发货状态",
    ("match_order_products", "match_product_from_message"): "无订单 或 订单无商品",
    ("match_order_products", "match_shipping_policy"): "已匹配订单商品",
    ("match_product_from_message", "match_shipping_policy"): "已匹配/未匹配商品",
    ("check_shipment_status", "match_order_products"): "发货状态已确定",
    ("match_shipping_policy", "generate_reply"): "物流政策已匹配",
    ("generate_reply", "quality_guard"): "回复已生成",
    ("quality_guard", "human_review_gate"): "守卫检查通过",
    ("human_review_gate", "__end__"): "流程结束",
    ("__start__", "normalize_input"): "开始",
    ("normalize_input", "detect_intent"): "输入已清洗",
    ("detect_intent", "risk_check"): "意图已识别",
    ("risk_check", "build_base_context"): "风险已评估",
    ("build_base_context", "route_by_intent"): "上下文已构建",
}


def build_mermaid(graph) -> str:
    """构建带业务条件标签的 Mermaid 流程图"""
    lines = [
        "---",
        "title: 客服 Copilot - customer_service_graph",
        "---",
        "flowchart TD",
    ]

    # 样式定义
    lines.append("    classDef startEnd fill:#e1f5fe,stroke:#01579b,stroke-width:2px")
    lines.append("    classDef decision fill:#fff3e0,stroke:#e65100,stroke-width:2px")
    lines.append("    classDef query fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px")
    lines.append("    classDef guard fill:#fce4ec,stroke:#c2185b,stroke-width:2px")
    lines.append("    classDef action fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px")

    # 节点分类
    decision_nodes = {"route_by_intent", "match_order_products", "human_review_gate"}
    query_nodes = {"query_jst_order", "query_local_order_fallback", "check_shipment_status",
                   "match_order_products", "match_product_from_message", "match_shipping_policy"}
    guard_nodes = {"risk_check", "quality_guard", "human_review_gate"}
    action_nodes = {"normalize_input", "detect_intent", "build_base_context", "generate_reply"}

    # 渲染节点（ID 保持英文，显示文本用中文）
    for node_id in graph.nodes:
        if node_id in ("__start__", "__end__"):
            continue
        cn_label = NODE_LABELS.get(node_id, node_id)
        shape = '(["{}"])' if node_id in decision_nodes else '["{}"]'
        line = f'    {node_id}{shape.format(cn_label)}'
        if node_id in decision_nodes:
            line += ":::decision"
        elif node_id in query_nodes:
            line += ":::query"
        elif node_id in guard_nodes:
            line += ":::guard"
        elif node_id in action_nodes:
            line += ":::action"
        lines.append(line)

    # 特殊节点
    lines.append('    START(["开始<br/>__start__"]):::startEnd')
    lines.append('    END(["结束<br/>__end__"]):::startEnd')

    # 渲染边
    for edge in graph.edges:
        src = edge.source
        dst = edge.target
        if src == "__start__":
            src = "START"
        if dst == "__end__":
            dst = "END"

        label = CONDITION_LABELS.get((edge.source, edge.target), "")
        if getattr(edge, "conditional", False):
            arrow = "-.->"
        else:
            arrow = "-->"

        if label:
            line = f'    {src} {arrow}|"{label}"| {dst}'
        else:
            line = f'    {src} {arrow} {dst}'
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def export_mmd(mermaid_text: str, filepath: str):
    """导出 .mmd 文件"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(mermaid_text)
    print(f"[OK] Mermaid 源码已保存: {filepath}")


def export_png(mmd_path: str, png_path: str) -> bool:
    """尝试用 mermaid-cli 生成 PNG"""
    # 方案1: 全局 mmdc
    for cmd_name in ["mmdc", "mermaid"]:
        cmd = [cmd_name, "-i", mmd_path, "-o", png_path, "-b", "white"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and os.path.exists(png_path):
                print(f"[OK] PNG 已生成 ({cmd_name}): {png_path}")
                return True
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            print(f"[WARN] {cmd_name} 执行超时")

    # 方案2: npx -y @mermaid-js/mermaid-cli
    cmd = ["npx", "-y", "@mermaid-js/mermaid-cli", "-i", mmd_path, "-o", png_path, "-b", "white"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(png_path):
            print(f"[OK] PNG 已生成 (npx mermaid-cli): {png_path}")
            return True
        else:
            print(f"[WARN] npx mermaid-cli 失败: {result.stderr[:300]}")
    except FileNotFoundError:
        print("[WARN] 未找到 npx，无法安装 mermaid-cli")
    except subprocess.TimeoutExpired:
        print("[WARN] npx mermaid-cli 安装/执行超时（网络慢或环境受限）")

    return False


def main():
    from app.agent.graph import customer_service_graph

    print("=" * 60)
    print("customer_service_graph 可视化导出工具")
    print("=" * 60)

    # 1. 获取图结构
    graph = customer_service_graph.get_graph()
    nodes = list(graph.nodes.keys())
    edges = [(e.source, e.target, getattr(e, "conditional", False), getattr(e, "data", None))
             for e in graph.edges]

    print(f"节点数: {len(nodes)}")
    print(f"边数: {len(edges)}")

    # 2. 生成 Mermaid
    mermaid_text = build_mermaid(graph)

    mmd_path = os.path.join(OUTPUT_DIR, "customer_service_graph.mmd")
    png_path = os.path.join(OUTPUT_DIR, "customer_service_graph.png")

    export_mmd(mermaid_text, mmd_path)

    # 3. 尝试生成 PNG
    png_ok = export_png(mmd_path, png_path)
    if not png_ok:
        print("[INFO] PNG 未生成，原因: 当前环境缺少 mermaid-cli 或网络受限。")
        print("[INFO] 你可以:")
        print("       1) 本地安装 Node.js 后运行: npm install -g @mermaid-js/mermaid-cli")
        print("       2) 使用 VS Code 插件 'Markdown Preview Mermaid Support' 预览 .mmd")
        print("       3) 把 .mmd 内容粘贴到 https://mermaid.live/ 在线查看")

    print("=" * 60)
    print("导出完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
