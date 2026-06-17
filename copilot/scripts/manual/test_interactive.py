"""模拟交互测试"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent import analyze_message, format_suggestion
from data_index import get_index

# 加载数据
get_index()

# 测试几个场景
test_cases = [
    ("我买的东西有质量问题，表面有裂痕，你们怎么处理？", None),
    ("快递显示已签收但我没收到啊", None),
    ("这个椅子承重多少？安装方便吗？", None),
    ("你们再不处理我就去12315投诉", None),
]

output_lines = []
for msg, oid in test_cases:
    output_lines.append(f"\n{'='*50}")
    output_lines.append(f"客户说: {msg}")
    output_lines.append(f"{'='*50}")
    result = analyze_message(msg, order_id=oid)
    output_lines.append(format_suggestion(result))

full_output = "\n".join(output_lines)

# 保存到文件
out_path = os.path.join(os.path.dirname(__file__), "test_results.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(full_output)

print("Done! Results saved to test_results.txt")
