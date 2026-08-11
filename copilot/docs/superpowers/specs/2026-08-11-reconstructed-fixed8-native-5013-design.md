# 重建 Fixed-8 原生 5013 基线设计

## 文档状态

- 日期：2026-08-11
- 阶段：P1.5 Reconstructed Fixed-8 Native 5013 Baseline
- 数据合同：`conversation-reconstructed-v1`
- 运行身份：当前分支干净提交和实际源码哈希
- 用途：P1 坐席辅助模式的原生模型工程基线
- 禁止用途：真实客户准确率、自动发送、生产晋升或替代遗失的原始 Fixed-8

## 当前缺口

重建评测已经完成固定 8 条、40 个历史回合、独立 manifest、标签隔离、
query-only 预检和 Synthetic `5/5`、`22/22` 安全回归，但当前源码还没有在
独立 5013 运行时中实际调用正式模型。旧 5011/5012 的提交和源码身份不同，
不能作为本轮结果。

因此下一步不是修改 Agent，而是冻结当前运行身份并取得一次不可替换的原生
`8×1` 观察。无论回答质量高低，只要评测基础设施完整，结果都必须保留。

## 架构决定

继续复用唯一的 `scripts/run_p1_gold_conversation_baseline.py` 和正式
`/api/analyze` Pipeline：

```text
重建 Fixed-8 fixture
-> 不可变 DatasetContract 与标签隔离
-> reviewed direct evidence 的隔离快照投影
-> 当前源码 5013 /api/analyze
-> 现有 AnalysisPipeline
-> Evidence Admission / Claim Resolution
-> 唯一 Composer 候选回复
-> Deterministic Final / advisory Audit
-> requires_human_review=true / can_send=false
-> 同一 Runner 的 checkpoint、报告和离线评分
```

不新增 Graph 节点、服务、模型调用角色、回复 Owner、重试、修复、fallback、
发送条件或平行评测系统。生产默认配置继续保持 Formal Evidence Convergence
和 Model-first Composer 关闭；本轮仅在隔离 5013 中按既有 P1 Runner 合同临时
开启这两个开关，以验证正式 Evidence 到 Composer 的候选链路。该隔离配置不得
写回 5011/5012 或成为生产默认值。

源知识库在恢复后只有正式表结构、没有可供这 8 条重建案例使用的商品事实。为避免
绕过正式 Evidence 链路，P1 Runner 在复制出隔离 SQLite 快照后，只从已通过
preflight 的 `evidence_candidates` 投影 `reviewed/approved/published/verified` 且
角色为 `direct_product_fact` 的候选。投影保留 evidence UID、商品身份、FactType、
attribute、scope、value、unit 和审核 provenance；unresolved、pending、媒体候选及
评测标签不得进入快照。源数据库字节和行数据保持不变。

readiness 所需的 `kb_qa` 非空条件由一条 `archived + auto_reply=0` 的评测哨兵满足。
该哨兵没有业务事实、不能参与检索，也不能支持回复。投影在快照哈希和运行绑定冻结
前完成；manifest 只记录投影哈希和数量，不保存原始事实值。

## 5013 运行合同

5013 必须是独立进程，且不得停止或修改 5011/5012。启动后必须满足：

- runtime commit 与当前干净 HEAD 一致；
- boot/end source tree SHA-256 一致，`source_tree_drift=false`；
- `ready=true`；
- 正式知识库通过 SQLite query-only 实际验证；
- 快照投影固定为 8 个商品身份、7 条 direct evidence、4 条排除候选和 1 条不可检索哨兵；
- `formal_knowledge_query_only=true`；
- `formal_evidence_convergence=true`；
- `model_first_answer_composer=true`；
- 上述两个开关仅属于隔离 P1 评测运行，生产默认状态仍为关闭；
- Provider/model 身份与 Runner 预期一致；
- 不输出 API key、完整 Provider URL、数据库内容或本地私密路径。

Provider 凭证只能来自当前未跟踪安全配置或当前进程环境。不得读取聊天历史中
暴露过的密钥，不得搜索历史文件，不得写入仓库、报告、日志或 Windows 用户环境。

## 分层执行门槛

### 第一层：1 条 × 1 次

只运行固定首条案例，验证：

- HTTP、Provider、Schema 和 Pipeline 成功；
- checkpoint 与 observation JSON 可解析；
- 评测字段没有进入 Agent payload；
- 正式知识库 DML 为 0；
- `can_send=false`、`requires_human_review=true`；
- runtime 和 Runner 源码没有漂移。

任一基础设施错误立即停止，不提高 timeout、不替换案例、不修改 Agent。

### 第二层：固定 8 条 × 1 次

第一层通过后，用相同 runtime、Provider、fixture、manifest、知识快照和 feature
flags 运行全部八条。禁止对失败案例重跑以等待偶然通过。

有效运行要求：

- `scenario_count=8`、`trial_count=8`；
- Provider/HTTP/Schema/Runner 错误为 0；
- 标签泄漏为 0；
- 正式知识 DML 为 0；
- `can_send=true` 为 0；
- 八条均保持人工复核；
- checkpoint、case observation 和 final report 数量及哈希一致。

## 观察与评分

每条报告只保存脱敏、最小、可复算的业务观察：

- 案例匿名别名、当前问题和必要历史摘要；
- authoritative goals 和 unresolved goals；
- selected evidence UID、角色、FactType 和准入状态摘要；
- 完整客户可见候选回复；
- Final/Audit 结果及 reason code；
- `can_send`、`requires_human_review` 和 reply status；
- Pipeline、Composer、Audit 延迟；
- 模型调用、timeout、retry、repair 和 fallback 数量。

评分按语义合同而不是固定句子，至少统计：上下文连续性、目标完整性、已支持
事实覆盖、证据归因、Partial Answer、无证据声明、媒体承诺、重复索要已知信息、
通用转人工和答非所问。

报告必须保持：

- `source_class=conversation_reconstructed`；
- `real_customer_accuracy=null`；
- `optimization_unverified=true`；
- `original_fixed8_restored=false`。

## 失败与后续归因

基础设施失败和业务质量失败必须分开：

- runtime/provider/schema/hash/DML/标签泄漏属于无效运行；
- 回答不完整、答非所问、无证据声明或重复转人工属于有效业务基线失败。

有效 `8×1` 完成后，按最早责任 Owner 分类到 Turn Understanding、Context、
Identity、RAG/Evidence、Claim Resolution、Composer 或 Final/Audit。下一阶段只修
出现频率最高且最早的一个通用断点，不按案例、商品或原句补规则。

## 验证与提交

运行 P1 Runner 专项、Pipeline、Final、docs governance、`py_compile`、JSON 双解析、
Synthetic `5/5` 和 `22/22`。运行产物、数据库、凭证和环境文件保留在仓库外。

只有原生 `8×1` 基础设施完整且报告可复算时，才提交本阶段运行合同和文档。
回答分数低不阻止提交可信基线，但不能触发生产开关或准确率声明。
