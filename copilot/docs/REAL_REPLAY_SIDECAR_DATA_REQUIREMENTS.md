# Real Replay Sidecar Data Requirements

真实回放要评估 Agent 能力，输入必须尽量模拟千牛工作台侧栏。买家消息里的商品链接、平台 item id、item hash 只能作为补充身份线索，不能替代商品标题、SKU、订单号。

## 为什么需要侧栏字段

真实客服在千牛里回答时通常能看到当前商品卡片、订单卡片或商品编码。缺少这些字段时，Replay 只能看到聊天文本和链接，Agent 无法可靠判断当前商品，也不能安全使用结构化商品字段或素材。此时失败应归因到输入上下文缺口，而不是 Agent 主链路错误。

## 售前最小字段

售前商品问题至少需要：

- 商品标题
- SKU 或内部 i_id，如果上游能提供
- 商品链接或平台 item_id，作为补充字段
- 规格、颜色、尺寸等买家当前选择信息，如果上游能提供

商品链接、item_id、item_hash 不能单独算完整商品上下文。

## 售后最小字段

售后、物流、退款、补发、少件、破损等问题至少需要：

- 订单号或平台订单号
- 商品标题
- SKU 或内部 i_id，如果上游能提供
- 订单卡片摘要，例如购买规格、数量、售后状态
- 商品链接或平台 item_id，作为补充字段

只有商品标题、没有订单号时，售后 replay 只能算 partial context。

## 推荐字段名

导入层优先识别这些字段名：

- `sidecar_product_title`
- `product_title`
- `product_name`
- `item_title`
- `sidecar_sku_code`
- `sku_code`
- `sku`
- `order_sku_code`
- `sidecar_i_id`
- `i_id`
- `internal_i_id`
- `sidecar_order_id`
- `order_id`
- `order_no`
- `tid`
- `product_url`
- `item_url`
- `item_id_hash`
- `platform_item_id_hash`

中文列名建议：

- 商品标题
- 商品名称
- 宝贝标题
- 商家编码
- 商品编码
- SKU
- 货号
- 内部 i_id
- 订单号
- 子订单号
- 交易单号
- 商品链接
- 商品规格
- 订单卡片摘要

## 缺字段时的 replay 归因

- `per_sample_missing_context`: 每条样本自己的侧栏字段缺失。
- `sidecar_partial`: 只有商品或只有订单，不能满足当前问题需要。
- `sidecar_missing`: 没有可用商品/订单侧栏。
- `eval_fixture_gap`: 使用全局商品夹具导致样本商品错配。

这些都不应算作 Agent 主链路错误。

## 禁止做法

- 不要从买家原话猜 SKU 或 i_id。
- 不要把商品链接、平台 item_id、item hash 当完整商品上下文。
- 不要用单一全局商品夹具替代每条样本自己的侧栏。
- 不要为了降低 context_gap 放宽 final gate 或 sendable contract。
