# 训练样本转入评测集操作说明

目标：把主管已复核的训练样本整理成可回放的评测集样本。

## 核心规则

1. 禁止批量自动转入评测集。
2. 必须逐条阅读完整样本、客服回复和主管评价。
3. 评测集只保存两段核心文本：
   - `customer_said`：客户说了什么。可以包含商品/订单上下文和长对话。
   - `suggested_answer`：建议 Agent 应该如何回答。
4. 售后、物流、退换、补发、发错、破损类样本，必须有订单号或 SKU。
5. 售前样本，必须有商品标题、商品链接、SKU 或其他商品身份。
6. 图片样本不能只写“图片消息”，必须人工理解图片内容后写成文本。
7. 转入评测集不会写知识库，也不会把客服原回复当作标准答案。

## 推荐文本格式

`customer_said` 建议使用：

```text
【商品/订单上下文】
场景：售后安装
订单号：3537476014789741
SKU：未结构化
商品标题：英禾儿童收纳柜...

【长对话】
买家：...
客服：...
买家：...
客服主管建议：...
```

`suggested_answer` 建议使用：

```text
亲，先承接客户的问题和情绪，然后按事实说明...
```

## 标准命令

先把两段整理好的文本分别保存为 UTF-8 文件，例如：

```powershell
notepad D:\eval_customer_said.txt
notepad D:\eval_suggested_answer.txt
```

然后执行：

```powershell
cd D:\桌面文件\客服\copilot
python scripts\curate_training_sample_eval_set.py --sample-id 29 --customer-said-file D:\eval_customer_said.txt --suggested-answer-file D:\eval_suggested_answer.txt
```

如果成功，会返回：

```json
{
  "converted": true,
  "review_status": "评测集"
}
```

如果失败，按 `reason` 补齐信息：

- `missing_customer_said`：缺客户文本。
- `missing_suggested_answer`：缺建议回答。
- `missing_curated_dialogue_context`：客户文本不是整理后的对话/上下文文本。
- `missing_aftersales_order_or_sku`：售后类样本缺订单号或 SKU。
- `missing_product_identity`：售前/安装类样本缺商品身份。

## 只预览，不转入

```powershell
python scripts\curate_training_sample_eval_set.py --sample-id 29 --preview
```

预览只看当前样本能自动生成什么，不会改状态。
