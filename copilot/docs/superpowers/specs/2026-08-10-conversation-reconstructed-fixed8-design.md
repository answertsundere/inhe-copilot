# 对话重建 Fixed-8 评测设计

## 文档状态

- 日期：2026-08-10
- 分支：`codex/recovery-conversation-eval-v1`
- 证据等级：`conversation_reconstructed`（根据历史对话重建）
- 用途：P1 坐席辅助模式的工程质量基线
- 禁止用途：真实客户准确率、Gold 人工批准、自动发送或生产晋升

## 问题背景

恢复后的仓库保留了正式 Pipeline、安全合同、P1 架构和历史工程检查点，
但原始 Fixed-8 数据集、数据清单、只读正式知识库快照和运行绑定尚未恢复。
仅凭文档和对话无法安全复原原文件哈希。

项目仍需要一套稳定的对话质量门槛。直接使用无关的旧模拟产物会混入不同
阶段的上下文和评分合同；伪造旧哈希则会破坏来源可追溯性。因此，新评测集
必须拥有独立身份，并明确使用较低的证据等级。

## 架构决定

新建版本化的八条评测集 `p1-conversation-reconstructed-v1`。来源等级固定为
`conversation_reconstructed`，清单明确说明：案例根据长期项目文档、历史对话
中确认过的失败类型和现有正式合同重建。它不是遗失的原始 Fixed-8，也不能
替代未来恢复出的真实数据。

评测必须走现有标准入口和正式 Pipeline：

```text
版本化重建案例
-> canonical conversation input（标准会话输入）
-> 现有 AnalysisPipeline
-> Evidence Admission（证据准入）
-> Claim Resolution（声明解析）
-> Model-first Composer 候选回复
-> Deterministic Final（确定性终审）
-> advisory Unified Audit（建议性统一审计）
-> 强制人工复核 / can_send=false
-> 运行后评测
```

不新增 Graph 节点、回复 Owner、生产服务、重试、修复、降级回复或发送条件。

## 备选方案

### 伪造原 Fixed-8 身份

不采用。原始内容和哈希已经缺失，沿用旧名称或预期哈希会让不可验证的重建
产物看起来像权威原件。

### 直接复用旧模拟候选

不采用。旧文件来自不同模型、评分器、上下文和合同版本，只能作为历史诊断，
不能定义恢复后的 P1 门槛。

### 建立可追溯的新重建集

采用。它能快速提供可重复的工程基线，同时严格区分“历史对话重建评测”、
“Synthetic 安全回归”和“经过批准的真实 Gold 准确率”。

## 固定覆盖矩阵

首版固定包含八条。商品和身份均使用通用匿名数据，生产逻辑不得按 SKU、订单号、
客户原句、案例别名或历史运行编号分支。

| 别名 | 对话能力 | 必须满足的合同 |
|---|---|---|
| `rc-01` | 订单引用先解析商品，再追问安装 | 保留结构化身份，不重复索要已知信息；安装继续人工复核 |
| `rc-02` | 同时询问材质、安全和防潮 | 回答已准入材质；缺失的安全或防潮证据不能被写成肯定或否定事实 |
| `rc-03` | 同时询问宽度和高度 | 保留两个目标，每项引用对应 evidence UID，不混入无关材质 |
| `rc-04` | 包装尺寸与商品尺寸并存 | 包装和商品作用域严格分离，禁止从包装尺寸推断商品尺寸 |
| `rc-05` | 安装问题带媒体候选，但没有实际媒体块 | 不承诺已经发送图片或视频，同时保留有证据支持的有效回答部分 |
| `rc-06` | 可见破损与退款、换货、赔偿结果混合 | 只描述已准入观察；退款、换货、赔偿和责任归属保持未解决或动作范围 |
| `rc-07` | 长对话追问携带尚未解决的商品目标 | 保留开放目标，不重复或删除当前目标，不重复询问已知信息 |
| `rc-08` | 绝对保证与有边界的日常解释 | 拒绝绝对保证；只允许基于 policy 和 premise、有归因且需复核的替代说明 |

## 数据集合同

数据集使用 UTF-8 JSON 和稳定的 canonical 排序。顶层字段为：

- `schema_version`：数据结构版本
- `dataset_id`：数据集标识
- `dataset_version`：数据集版本
- `source_class`：来源等级
- `source_summary`：来源说明
- `privacy_classification`：隐私等级
- `cases`：八条案例
- `manifest`：内容清单

每条案例包含：

- `case_alias`：不透明的 `rc-NN` 别名
- `category`：稳定的能力分类
- `conversation_turns`：按顺序排列的 `CUSTOMER` 与 `AGENT` 回合
- `current_customer_message`：唯一的当前买家消息
- `identity_context`：只包含匿名商品和订单引用
- `evidence_candidates`：证据角色、审核状态、身份、FactType、属性、值、
  来源和准入元数据
- `service_actions`、`media_candidates`：始终标记为非事实
- `expected_contract`：仅供运行后评分，禁止进入 Agent
- `prohibited_outcomes`：仅供运行后检查，禁止进入 Agent

Agent 请求只能由会话、匿名身份和候选上下文构成。`expected_contract`、
`prohibited_outcomes`、案例别名、数据哈希和评测标签必须在调用正式 Pipeline
前剔除。

## 来源与清单

配套 manifest 必须记录：

- 数据集 ID、版本和 schema 版本
- 精确案例数量和分类分布
- canonical 数据集 SHA-256
- 每条案例 SHA-256
- 来源等级 `conversation_reconstructed`
- 来源限制
- 隐私扫描结果
- `real_customer_accuracy=null`
- `original_fixed8_restored=false`

任何哈希不匹配、别名重复、分类计数不一致或 schema 错误，都必须在调用
Agent 或 Provider 前失败关闭。

## 正式知识与证据边界

重建过程不复制、不修改生产数据库。案例 sidecar 中携带版本化候选证据，
但仍必须通过现有证据准入合同。运行器必须验证：

- 配置数据库时，正式知识库处于 query-only；
- 正式知识库 DML 为 0；
- rejected、conflicting、reference_only、service_action、media_reference
  和身份错配候选不能进入 selected evidence；
- 不得从参考答案反推证据值。

sidecar 证据只是评测 fixture，不能证明线上知识覆盖率。

## 评分合同

评分按声明和业务合同进行，不匹配固定句子。报告至少记录：

- 执行是否成功、候选回复是否为空
- 权威客户目标是否完整保留
- 已支持声明覆盖率和证据归因
- unresolved/prohibited 边界是否保留
- Partial Answer 是否成功
- 问答匹配和上下文连续性
- 无证据高风险声明
- 无实际媒体块的媒体发送承诺
- 无依据服务动作声明
- 重复索要已知信息
- 不必要的通用转人工
- `can_send` 和 `requires_human_review`
- Pipeline、Composer 和 Audit 延迟
- Provider 调用、重试、修复、fallback、超时和错误

报告可以生成 `reconstructed_baseline_status`，但必须始终保持
`real_customer_accuracy=null` 和 `optimization_unverified=true`，直到恢复并
运行经过批准的真实数据集。

## 失败关闭规则

出现以下任一情况，本次运行无效并返回非零退出码：

- 数据集或 manifest 哈希不匹配；
- 案例数量不是 8；
- 别名重复或排序不稳定；
- 期望结果、禁止结果或评测标签进入 Agent 请求；
- 回合顺序非法或存在未解析角色；
- 身份或证据 schema 不完整；
- 正式知识库可写或发生 DML；
- 出现 `can_send=true`；
- 报告宣称真实准确率或等同于原 Fixed-8；
- 运行期间 runtime 或 evaluator 源码身份漂移。

只有在数据集和运行身份完整性检查已经通过时，Provider 故障才可记录为有效的
基础设施失败；不得把它换算成业务质量分数。

## 实现边界

实现应扩展现有 P1 baseline/evaluation Owner，不建立第二套评测子系统。长期修改
范围限定为：

- 一份版本化数据集 fixture；
- 一份配套 manifest；
- 现有 P1 runner 的重建模式支持，或仅供该 runner 复用的窄 loader；
- 数据完整性、标签泄漏和失败关闭测试；
- 现有 P1 架构与模块索引更新。

生产 Agent 行为保持不变。

## 验证顺序

1. 数据集、manifest schema 和隐私测试。
2. manifest 篡改、重复别名、标签泄漏和零案例反例测试。
3. Agent payload 投影等价性和评测字段隔离测试。
4. 不调用 Provider 的单案例 dry run。
5. 八案例确定性预检。
6. 通过现有正式 Pipeline 运行一次重建 Fixed-8。
7. Synthetic smoke `5/5`、full `22/22`，只作为安全回归。
8. `py_compile`、Python JSON、PowerShell JSON 和 `git diff --check`。

任何成功结果都不能开启生产功能。

## 恢复后的晋升规则

如果之后找回原 Fixed-8 资产，必须按原独立身份和已验证哈希重新纳入。重建集
结果只保留为历史工程证据，不能并入恢复后的真实数据得分。
