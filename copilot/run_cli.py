"""
INHE 客服 Copilot - 命令行交互入口

用法:
    python run_cli.py

命令:
    /help     - 显示帮助
    /order    - 查询订单 (如: /order 202501010001)
    /sku      - 查询SKU  (如: /sku YH66K02B02S23)
    /product  - 查询商品 (如: /product YH66K02)
    /stats    - 显示数据统计
    /quit     - 退出
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

from app.config import LLM_API_KEY
from app.logging_config import setup_logging
from app.main import (
    get_order_repo,
    get_product_repo,
    get_reply_service,
)
from app.services.reply_service import format_suggestion


def print_banner():
    print("""
╔══════════════════════════════════════════════╗
║        INHE 客服 Copilot v0.2                ║
║        AI 客服建议生成器 (模块化架构)          ║
╚══════════════════════════════════════════════╝

使用方法:
  输入客户消息，AI 会分析意图并生成建议回复
  可选附带订单号，AI 会自动查询订单/物流/售后数据

命令:
  /help     - 显示帮助
  /order    - 查询订单 (如: /order 202501010001)
  /sku      - 查询SKU  (如: /sku YH66K02B02S23)
  /product  - 查询商品 (如: /product YH66K02)
  /stats    - 显示数据统计
  /quit     - 退出
""")


def cmd_order(order_id):
    order_repo = get_order_repo()
    order = order_repo.get_order(order_id)
    if not order:
        print(f"  未找到订单: {order_id}")
        return

    print(f"\n  订单: {order.get('o_id')}")
    print(f"  店铺: {order.get('shop_name', '未知')}")
    print(f"  状态: {order.get('status', '未知')} / {order.get('shop_status', '未知')}")
    print(f"  金额: {order.get('pay_amount', 0)}")
    print(f"  创建: {order.get('created', '未知')}")
    print(f"  发货: {order.get('send_date', '未发货')}")
    if order.get("l_id"):
        print(f"  快递: {order.get('logistics_company', '')} {order['l_id']}")

    items = order.get("items", [])
    if items:
        print("  商品:")
        for item in items:
            print(f"    - {item.get('name', item.get('sku_id', ''))} "
                  f"x{item.get('qty', 1)} ¥{item.get('price', 0)}")

    logistics = order_repo.get_logistics(order_id)
    if logistics:
        print(f"  物流记录: {len(logistics)} 条")

    refunds = order_repo.get_refunds(order_id)
    if refunds:
        print(f"  退款记录: {len(refunds)} 条")


def cmd_sku(sku_id):
    product_repo = get_product_repo()
    sku = product_repo.get_sku(sku_id)
    if not sku:
        print(f"  未找到SKU: {sku_id}")
        return
    print(f"\n  SKU: {sku.get('sku_id')}")
    print(f"  款号: {sku.get('i_id', '')}")
    print(f"  名称: {sku.get('name', '')}")
    print(f"  品牌: {sku.get('brand', '')}")
    print(f"  规格: {sku.get('properties_value', '')}")
    print(f"  售价: {sku.get('sale_price', '')}")


def cmd_product(i_id):
    product_repo = get_product_repo()
    product = product_repo.get_product(i_id)
    if not product:
        print(f"  未找到商品: {i_id}")
        return
    print(f"\n  款号: {product.get('i_id')}")
    print(f"  名称: {product.get('name', '')}")
    print(f"  品牌: {product.get('brand', '')}")
    print(f"  分类: {product.get('category', '')}")
    skus = product.get("skus", [])
    if skus:
        print("  SKU列表:")
        for s in skus:
            print(f"    - {s.get('sku_id')} {s.get('properties_value', '')} ¥{s.get('sale_price', '')}")


def cmd_stats():
    order_repo = get_order_repo()
    product_repo = get_product_repo()
    print(f"\n  数据统计:")
    print(f"    订单: {order_repo.count_orders()} 条")
    print(f"    SKU: {product_repo.count_skus()} 条")
    print(f"    商品: {product_repo.count_products()} 条")
    print(f"    物流: {order_repo.count_logistics()} 条")
    print(f"    退款: {order_repo.count_refunds()} 条")


def main():
    setup_logging()
    print_banner()

    if not LLM_API_KEY:
        print("[警告] 未配置 COPILOT_LLM_API_KEY，AI 建议功能不可用")
        print("       查询命令（/order, /sku, /product, /stats）仍可使用\n")

    print("正在初始化...")
    # 触发初始化
    get_reply_service()
    print("初始化完成!\n")

    while True:
        try:
            user_input = input("\n客户消息> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit"):
                print("再见!")
                break
            elif cmd == "/help":
                print_banner()
            elif cmd == "/order":
                cmd_order(arg) if arg else print("  用法: /order <订单号>")
            elif cmd == "/sku":
                cmd_sku(arg) if arg else print("  用法: /sku <SKU编码>")
            elif cmd == "/product":
                cmd_product(arg) if arg else print("  用法: /product <款号>")
            elif cmd == "/stats":
                cmd_stats()
            else:
                print(f"  未知命令: {cmd}，输入 /help 查看帮助")
            continue

        # 解析输入：支持 "消息 [订单号]" 格式
        order_id = ""
        message = user_input
        if "[" in user_input and "]" in user_input:
            start = user_input.rfind("[")
            end = user_input.rfind("]")
            if start < end:
                possible = user_input[start + 1 : end].strip()
                if possible.isdigit():
                    order_id = possible
                    message = user_input[:start].strip()

        if not LLM_API_KEY:
            print("  [错误] 未配置 API Key，无法生成 AI 建议")
            continue

        print("  正在分析...")
        reply_service = get_reply_service()
        result = reply_service.analyze(message, order_id=order_id)
        print(format_suggestion(result))


if __name__ == "__main__":
    main()
