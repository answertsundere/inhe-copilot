"""测试 AI 建议功能"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import analyze_message, format_suggestion

print("正在加载数据...")

# 测试1: 催发货
print(">>> 测试: 催发货场景")
result = analyze_message("怎么还没发货？都好几天了，再不发我就退款了")
output = format_suggestion(result)
print(output)

# 保存到文件
with open(os.path.join(os.path.dirname(__file__), "test_output.txt"), "w", encoding="utf-8") as f:
    f.write(output)
    f.write("\n\n--- 原始返回 ---\n")
    import json
    f.write(json.dumps(result, ensure_ascii=False, indent=2))

print("\n已保存到 test_output.txt")
