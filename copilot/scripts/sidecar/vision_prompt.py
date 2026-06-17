from __future__ import annotations

VISION_SYSTEM_PROMPT = """你是一个千牛客服聊天截图解析器。
请只根据截图中可见内容提取聊天消息，不要猜测、不要补全、不要生成客服回复。
请区分：
- 左侧买家气泡 / 左侧头像 / 灰色或白色气泡：customer
- 右侧客服气泡 / 右侧头像 / 蓝色气泡：agent
- 中间时间、已读、系统提示：system
- 顶部 AI 咨询摘要、工具栏、商品栏、订单栏：ignore，不要放入 messages

如果无法确定角色，role=unknown。如果看不清文字，不要猜测。如果订单号、快递单号不完整，不要补全。
只输出严格 JSON，不要输出解释文字。"""

VISION_USER_PROMPT_TEMPLATE = """请分析这张千牛客服聊天截图。
提取规则：
1. 按从上到下的时间顺序列出所有可见聊天消息。
2. 区分 customer / agent / system / unknown 角色。
3. 只把真正聊天区的买家和客服气泡放入 messages，不要提取右侧商品/订单栏、顶部摘要栏、按钮文字。
4. latest_customer_message 必须是最新一条买家消息；如果截图中只有买家气泡，就取最下面一条买家气泡。
5. 如果截图中有订单号、快递单号、商品名，也作为候选提取。
输出格式（严格 JSON）：
{
  "success": true,
  "messages": [
    {"role": "customer|agent|system|unknown", "text": "...", "time": "...", "confidence": 0.0}
  ],
  "latest_customer_message": "...",
  "latest_agent_message": "...",
  "order_candidates": [
    {"value": "...", "confidence": 0.0}
  ],
  "tracking_candidates": [
    {"value": "...", "confidence": 0.0}
  ],
  "product_candidates": [
    {"value": "...", "confidence": 0.0}
  ],
  "warnings": [],
  "overall_confidence": 0.0
}"""

VISION_MOCK_RESPONSE = {
    "success": True,
    "messages": [
        {"role": "customer", "text": "为什么只能手动摁呢", "time": "", "confidence": 0.9},
        {"role": "customer", "text": "我没找到，怎么让他自动感应", "time": "", "confidence": 0.9},
        {"role": "agent", "text": "拍下这边看下", "time": "", "confidence": 0.9},
    ],
    "latest_customer_message": "我没找到，怎么让他自动感应",
    "latest_agent_message": "拍下这边看下",
    "order_candidates": [],
    "tracking_candidates": [],
    "product_candidates": [],
    "warnings": [],
    "overall_confidence": 0.9,
}
