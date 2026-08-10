# 对话重建 Fixed-8 实施计划

> **执行要求：** 实施本计划时必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，逐项勾选并在每个任务后独立验证。

**目标：** 建立一套来源明确、固定八案例、不会冒充真实准确率的 P1 长对话工程评测，并通过现有正式 Pipeline 运行。

**架构：** 保留 scripts/run_p1_gold_conversation_baseline.py 作为唯一 P1 baseline Owner，通过不可变 DatasetContract 同时支持原 26 条合同和新的重建 8 条合同。数据标签在 api_request_template 外保存，现有 _agent_payload() 继续作为标签泄漏边界；生产 Agent、Graph、Safety 和 Delivery 均不修改。

**技术栈：** Python 3.11、pytest、UTF-8 JSON、SQLite query-only、现有 AnalysisPipeline 和 P1 baseline runner。

## 全局约束

- 数据集身份固定为 p1-conversation-reconstructed-v1，来源固定为 conversation_reconstructed。
- 结果必须保持 real_customer_accuracy=null、optimization_unverified=true、original_fixed8_restored=false。
- 不新增 Graph 节点、生产服务、回复 Owner、模型调用、retry、repair、fallback 或发送条件。
- 不修改正式 Agent、RAG、Evidence、Safety Gate、媒体合同、Delivery 或 can_send。
- 不按案例别名、商品、SKU、订单号或客户原句修改生产逻辑。
- 评测标签、参考答案、期望合同和禁止结果不得进入 Agent payload。
- 正式知识库必须 query-only，正式知识 DML 必须为 0。
- 版本化 fixture 可以提交；运行输出、数据库、凭证、.env 和构建产物不得提交。

---

### 任务一：固定 DatasetContract 和失败关闭验证

**文件：**

- 修改：scripts/run_p1_gold_conversation_baseline.py
- 新建测试：tests/test_p1_reconstructed_conversation_baseline.py

**接口：**

- 输入：CLI --dataset-contract legacy-real-derived-v4|conversation-reconstructed-v1
- 输出：不可变 DatasetContract，包含 ID、版本、案例数、数据哈希、manifest 文件哈希、来源等级和准确率声明边界。

- [ ] **步骤 1：先写合同解析失败测试**

~~~python
def test_reconstructed_contract_is_distinct_from_missing_original_fixed8():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )
    assert contract.dataset_id == "p1-conversation-reconstructed-v1"
    assert contract.case_count == 8
    assert contract.source_class == "conversation_reconstructed"
    assert contract.real_customer_accuracy is None
    assert contract.original_fixed8_restored is False


def test_unknown_dataset_contract_fails_closed():
    with pytest.raises(
        P1BaselineIntegrityError,
        match="dataset_contract_unknown",
    ):
        p1_baseline._resolve_dataset_contract("fixed8")
~~~

- [ ] **步骤 2：运行测试并确认 RED**

运行：

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py -q
~~~

预期：因 _resolve_dataset_contract 尚不存在而失败。

- [ ] **步骤 3：实现最小不可变合同**

~~~python
@dataclass(frozen=True)
class DatasetContract:
    contract_name: str
    dataset_id: str
    dataset_version: str
    case_count: int
    dataset_sha256: str
    manifest_file_sha256: str
    source_class: str
    real_customer_accuracy: None = None
    original_fixed8_restored: bool = False


def _resolve_dataset_contract(name: str) -> DatasetContract:
    contract = _DATASET_CONTRACTS.get(str(name or "").strip())
    if contract is None:
        raise P1BaselineIntegrityError("dataset_contract_unknown")
    return contract
~~~

保留原 26 条合同为默认值，避免破坏旧命令。重建合同的两个哈希在任务二生成 fixture 后填入。

- [ ] **步骤 4：让 _preflight_dataset() 使用显式合同**

函数签名固定为：

~~~python
def _preflight_dataset(
    dataset_path: Path,
    manifest_path: Path,
    *,
    contract: DatasetContract,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
~~~

所有案例数、dataset ID/version/hash 和 manifest 文件哈希校验都从 contract 读取，不得从输入文件自报值反向构造合同。

- [ ] **步骤 5：运行合同测试和原 runner 测试**

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py tests/test_p1_gold_conversation_baseline.py -q
~~~

- [ ] **步骤 6：提交任务一**

~~~powershell
git add scripts/run_p1_gold_conversation_baseline.py tests/test_p1_reconstructed_conversation_baseline.py
git commit -m "test: add reconstructed conversation dataset contract"
~~~

---

### 任务二：建立固定八案例 fixture 和 manifest

**文件：**

- 新建：tests/fixtures/p1_conversation_reconstructed/v1.json
- 新建：tests/fixtures/p1_conversation_reconstructed/v1.manifest.json
- 修改测试：tests/test_p1_reconstructed_conversation_baseline.py

**接口：**

- 输入：无外部数据；使用设计文档冻结的八类通用场景。
- 输出：符合 high-quality-long-conversation-review/v1 的数据集和独立 manifest。

- [ ] **步骤 1：先写数据完整性测试**

~~~python
def test_reconstructed_fixture_has_fixed_coverage_and_no_real_accuracy_claim():
    dataset, validation = load_and_validate_review_dataset(DATASET_PATH)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert validation["validation_status"] == "passed"
    assert len(dataset["scenarios"]) == 8
    assert [row["reconstruction_alias"] for row in dataset["scenarios"]] == [
        f"rc-{index:02d}" for index in range(1, 9)
    ]
    assert dataset["source_class"] == "conversation_reconstructed"
    assert manifest["real_customer_accuracy"] is None
    assert manifest["optimization_unverified"] is True
    assert manifest["original_fixed8_restored"] is False
~~~

- [ ] **步骤 2：运行测试并确认 fixture 缺失导致 RED**

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py::test_reconstructed_fixture_has_fixed_coverage_and_no_real_accuracy_claim -q
~~~

- [ ] **步骤 3：用 apply_patch 写入八案例 JSON**

每条 scenario 必须包含符合现有 validator 的 scenario_uid、content_sha256、conversation_history、current_buyer_message、api_request_template、expected_claims、forbidden_claims、must_handoff 和 draft review。八条分别覆盖身份安装、材质/安全/防潮、多事实尺寸、包装/商品作用域、媒体承诺、售后动作、长上下文目标延续和绝对保证边界。匿名 ID 不得匹配真实订单或 SKU 格式。

- [ ] **步骤 4：按现有 canonical 规则生成哈希**

使用 app.services.long_conversation_simulation_service._content_hash() 生成每条 content_sha256 和 dataset manifest.content_sha256。独立 manifest 保存数据文件 SHA-256、分类计数、隐私声明和证据等级，不读取生产数据库。

- [ ] **步骤 5：加入反例测试**

~~~python
@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("duplicate_alias", "reconstruction_alias_duplicate"),
        ("wrong_case_count", "scenario_count_mismatch"),
        ("real_accuracy_claim", "reconstructed_accuracy_claim_forbidden"),
        ("original_fixed8_claim", "original_fixed8_equivalence_forbidden"),
    ],
)
def test_reconstructed_fixture_mutations_fail_closed(mutation, reason):
    payload, manifest = _fixture_copy()
    _apply_mutation(payload, manifest, mutation)
    with pytest.raises(P1BaselineIntegrityError, match=reason):
        p1_baseline._validate_reconstructed_contract(payload, manifest)
~~~

- [ ] **步骤 6：运行数据和隐私测试**

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py tests/test_real_accuracy_privacy_and_labels.py -q
~~~

- [ ] **步骤 7：将真实哈希填入 DatasetContract 并提交**

~~~powershell
git add tests/fixtures/p1_conversation_reconstructed scripts/run_p1_gold_conversation_baseline.py tests/test_p1_reconstructed_conversation_baseline.py
git commit -m "test: add reconstructed fixed8 conversation fixture"
~~~

---

### 任务三：隔离评测标签并接入现有 runner

**文件：**

- 修改：scripts/compare_model_first_answer_composer.py
- 修改：scripts/run_p1_gold_conversation_baseline.py
- 修改测试：tests/test_p1_reconstructed_conversation_baseline.py
- 修改测试：tests/test_p1_gold_conversation_baseline.py

**接口：**

- 输入：任务一的 DatasetContract 和任务二的 fixture。
- 输出：现有 prepare/run/finalize 使用同一合同哈希、案例数和来源等级；Agent payload 不含评测标签。

- [ ] **步骤 1：先写标签泄漏 RED 测试**

~~~python
def test_reconstructed_expected_contract_never_enters_agent_payload():
    scenario = _load_first_case()
    scenario["api_request_template"]["expected_contract"] = {"pass": True}
    with pytest.raises(ValueError, match="evaluation_field_leakage"):
        evaluator._agent_payload(scenario)


def test_labels_outside_api_template_are_not_serialized_to_agent():
    scenario = _load_first_case()
    payload = evaluator._agent_payload(scenario)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "expected_contract" not in encoded
    assert "prohibited_outcomes" not in encoded
    assert "reconstruction_alias" not in encoded
~~~

- [ ] **步骤 2：运行测试并确认 expected_contract 注入未被现有禁止字段捕获**

- [ ] **步骤 3：最小扩展 _PROHIBITED_AGENT_FIELDS**

只增加 expected_contract、prohibited_outcomes、reconstruction_alias 和 source_class 四个评测控制字段。

- [ ] **步骤 4：传播显式 DatasetContract**

prepare()、run()、finalize()、_summary_payload()、_checkpoint_payload() 和 _finalize_from_checkpoint() 必须使用同一合同的 dataset hash 与 case count。checkpoint、pre-run manifest 和最终报告均新增：

~~~python
{
    "dataset_contract": contract.contract_name,
    "source_class": contract.source_class,
    "real_customer_accuracy": None,
    "optimization_unverified": True,
    "original_fixed8_restored": False,
}
~~~

不得用重建合同覆盖旧合同的历史身份。

- [ ] **步骤 5：加入运行终态反例**

断言重建模式出现 can_send=true、案例数不足、source drift、正式知识 DML 或错误准确率声明时返回退出码 2。

- [ ] **步骤 6：运行 runner 专项回归**

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py tests/test_p1_gold_conversation_baseline.py tests/test_analysis_pipeline_entrypoints.py -q
~~~

- [ ] **步骤 7：提交任务三**

~~~powershell
git add scripts/compare_model_first_answer_composer.py scripts/run_p1_gold_conversation_baseline.py tests/test_p1_reconstructed_conversation_baseline.py tests/test_p1_gold_conversation_baseline.py
git commit -m "feat: support reconstructed conversation baseline"
~~~

---

### 任务四：确定性预检和原生八案例运行

**文件：**

- 仅在测试暴露真实缺口时修改任务三范围内的 evaluation 代码。
- 运行输出写入 outputs/，不提交。

**接口：**

- 输入：固定 fixture、manifest、当前 commit/source hash、query-only 快照、正式 Provider 子进程配置。
- 输出：八条 case observation、checkpoint、manifest 和重建工程基线报告。

- [ ] **步骤 1：运行不调用 Provider 的确定性 preflight**

使用 --operation prepare 和 --dataset-contract conversation-reconstructed-v1。确认案例 8/8、隐私 0、query-only 已启用、正式知识 DML 0。

- [ ] **步骤 2：验证 Agent payload 隔离**

对八条 _agent_payload() 结果做 canonical hash，并扫描禁止字段、真实订单/SKU 模式、参考答案和评分标签。命中任一项立即停止，不调用 Provider。

- [ ] **步骤 3：通过现有正式 API 跑一次八案例**

只允许每条运行一次，不因结果差重跑。Provider 凭证仅来自当前安全进程环境，不写文件、不打印。

- [ ] **步骤 4：核对运行完整性**

必须满足：执行场景数 8、source drift=false、checkpoint 与报告一致、正式知识 DML=0、can_send=true 为 0、requires_human_review=true 为 8。

- [ ] **步骤 5：输出工程质量指标**

报告 claim/goal 覆盖、证据归因、Partial Answer、上下文连续性、媒体/动作违规、重复询问、不必要转人工、模型调用和 p50/p95；同时固定 real_customer_accuracy=null、optimization_unverified=true 和 baseline_evidence_class=conversation_reconstructed。

---

### 任务五：完整回归、文档与恢复检查点

**文件：**

- 修改：docs/agent-core-priority-plan.md
- 修改：docs/architecture-overview.md
- 修改：docs/module-index.md
- 修改：docs/index.md

**接口：**

- 输入：任务四的可验证运行结果。
- 输出：准确描述工程基线状态的持久文档、代码提交和 Git bundle。

- [ ] **步骤 1：运行完整相关测试**

~~~powershell
python -m pytest tests/test_p1_reconstructed_conversation_baseline.py tests/test_p1_gold_conversation_baseline.py tests/test_analysis_pipeline_entrypoints.py tests/test_final_answer_auditor.py tests/test_final_response_orchestrator.py tests/test_docs_governance.py -q
~~~

- [ ] **步骤 2：运行 Synthetic 安全回归**

运行 smoke 5/5 和 full 22/22；只报告安全回归，不把结果并入重建基线或真实准确率。

- [ ] **步骤 3：运行静态和格式验证**

~~~powershell
python -m py_compile scripts/run_p1_gold_conversation_baseline.py scripts/compare_model_first_answer_composer.py
git diff --check
~~~

fixture、manifest 和报告分别用 Python json.load 与 PowerShell ConvertFrom-Json 解析。

- [ ] **步骤 4：更新现有文档**

记录数据来源等级、八案例结果、真实准确率仍为空、生产开关仍关闭和原 Fixed-8 恢复后的独立晋升规则。不得增加第二个文档索引。

- [ ] **步骤 5：精确暂存并提交**

只暂存本计划列出的源码、测试、fixture 和文档；检查不含 outputs、数据库、.env、凭证和构建产物。

- [ ] **步骤 6：建立恢复 bundle 并尝试推送**

在非仓库恢复目录生成包含当前分支的 Git bundle，验证后记录 SHA-256。网络可用时推送 codex/recovery-conversation-eval-v1；推送失败不得影响本地提交和 bundle。

