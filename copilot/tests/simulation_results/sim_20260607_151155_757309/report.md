# Simulation Run Report: sim_20260607_151155_757309

## Run Configuration

- **Run ID**: sim_20260607_151155_757309
- **Mode**: service
- **Offline**: True
- **Started**: 2026-06-07T07:11:55.403623+00:00
- **Completed**: 2026-06-07T07:16:11.167726+00:00
- **Customers**: 50

## Summary

- **Total Customers**: 50
- **Customers Passed**: 1
- **Pass Rate**: 2.0%
- **Average Score**: 0.793
- **Min Score**: 0.722
- **Max Score**: 0.963

### Dimension Averages

| Dimension | Average Score |
|-----------|--------------|
| context_memory | 0.950 |
| grounding | 1.000 |
| intent_match | 0.213 |
| performance | 0.963 |
| reply_quality | 1.000 |
| risk_recall | 0.983 |
| tool_routing | 0.306 |
| trace_completeness | 0.726 |
| trap_detection | 1.000 |

### Scores by Scenario

| Scenario | Avg Score |
|----------|-----------|
| after_sales_return | 0.748 |
| complaint_high_risk | 0.774 |
| edge_composite | 0.799 |
| installation | 0.780 |
| logistics | 0.793 |
| pre_sale_product | 0.853 |

## Intent Confusion Matrix

- **Overall Accuracy**: 25.9% (43/166)

| Expected \ Actual | after_sale_damage | after_sale_installation | after_sale_missing_part | after_sale_return_refund | aftersales | complaint | complaint_risk | delivery_not_received | general | installation | logistics_eta | pre_sale_purchase_guidance | product_question | safety_risk | unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| after_sale_damage | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 3 | 0 | 0 | 0 | 1 | 0 | 0 |
| after_sale_installation | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 3 | 0 | 0 | 6 | 0 | 0 |
| after_sale_missing_part | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 3 | 0 | 0 |
| after_sale_return_refund | 0 | 0 | 0 | 0 | 13 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 11 | 0 | 0 |
| aftersales | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| complaint | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| complaint_risk | 0 | 0 | 0 | 0 | 2 | 6 | 0 | 0 | 9 | 0 | 0 | 0 | 4 | 0 | 0 |
| delivery_not_received | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| general | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| installation | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| logistics_eta | 0 | 0 | 0 | 0 | 6 | 1 | 0 | 1 | 3 | 0 | 11 | 0 | 5 | 0 | 0 |
| pre_sale_purchase_guidance | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 1 | 0 | 6 | 0 | 0 |
| product_question | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 1 | 4 | 0 | 31 | 0 | 0 |
| safety_risk | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |

### Top Misclassifications

| Expected | Actual | Count |
|----------|--------|-------|
| after_sale_return_refund | aftersales | 13 |
| after_sale_return_refund | product_question | 11 |
| complaint_risk | general | 9 |
| product_question | general | 8 |
| pre_sale_purchase_guidance | general | 8 |
| pre_sale_purchase_guidance | product_question | 6 |
| logistics_eta | aftersales | 6 |
| after_sale_return_refund | general | 6 |
| after_sale_installation | product_question | 6 |
| complaint_risk | complaint | 6 |

## Tool Accuracy

- **Accuracy**: 36.5% (88/241)

## Risk Recall

- **High-risk messages detected**: 10
- **Correctly handled**: 8
- **Recall**: 80.0%

## Grounding

- **Average Score**: 1.000

## Context Memory

- **Average Score**: 0.941
- **Turns with Issues**: 39/166

## Customer Results

| ID | Name | Scenario | Score | Turns | Passed |
|----|------|----------|-------|-------|--------|
| C001 | 新手妈妈_小林 | pre_sale_product | 0.870 | 3 | N |
| C002 | 挑剔买家_王姐 | pre_sale_product | 0.898 | 3 | N |
| C003 | 比价党_小张 | pre_sale_product | 0.731 | 3 | N |
| C004 | 送礼者_陈哥 | pre_sale_product | 0.778 | 3 | N |
| C005 | 大户型_李太太 | pre_sale_product | 0.889 | 3 | N |
| C006 | 过敏宝宝家长_赵妈妈 | pre_sale_product | 0.889 | 3 | N |
| C007 | 急性子_周先生 | pre_sale_product | 0.778 | 3 | N |
| C008 | 租房客_小孙 | pre_sale_product | 0.935 | 3 | N |
| C009 | 老年人_刘奶奶 | pre_sale_product | 0.898 | 3 | N |
| C010 | 预算有限_小马 | pre_sale_product | 0.824 | 3 | N |
| C011 | 品牌忠诚_何女士 | pre_sale_product | 0.787 | 3 | N |
| C012 | 尺寸纠结_吴妈妈 | pre_sale_product | 0.963 | 3 | N |
| C013 | 等待焦虑_郑女士 | logistics | 0.824 | 3 | N |
| C014 | 出差在即_杨哥 | logistics | 0.824 | 3 | N |
| C015 | 物流停滞_徐女士 | logistics | 0.824 | 3 | N |
| C016 | 签收异常_朱先生 | logistics | 0.824 | 3 | N |
| C017 | 拒收拦截_钱女士 | logistics | 0.759 | 3 | N |
| C018 | 多件到货_孙女士 | logistics | 0.778 | 3 | N |
| C019 | 偏远地区_马先生 | logistics | 0.768 | 3 | N |
| C020 | 时效投诉_田女士 | logistics | 0.741 | 3 | N |
| C021 | 尺寸买错_林女士 | after_sales_return | 0.759 | 3 | N |
| C022 | 质量问题_黄女士 | after_sales_return | 0.769 | 3 | N |
| C023 | 漏发配件_曾先生 | after_sales_return | 0.750 | 3 | N |
| C024 | 破损换货_罗女士 | after_sales_return | 0.741 | 3 | N |
| C025 | 七天无理由_胡女士 | after_sales_return | 0.769 | 3 | N |
| C026 | 色差问题_何女士 | after_sales_return | 0.731 | 3 | N |
| C027 | 少件_梁先生 | after_sales_return | 0.731 | 3 | N |
| C028 | 发错货_宋女士 | after_sales_return | 0.750 | 3 | N |
| C029 | 超七天退货_唐女士 | after_sales_return | 0.741 | 3 | N |
| C030 | 影响二次销售_韩女士 | after_sales_return | 0.750 | 3 | N |
| C031 | 运费争议_曹先生 | after_sales_return | 0.741 | 3 | N |
| C032 | 仅退款_邓女士 | after_sales_return | 0.750 | 3 | N |
| C033 | 看不懂说明书_许奶奶 | installation | 0.750 | 3 | N |
| C034 | 缺安装工具_冯先生 | installation | 0.743 | 3 | N |
| C035 | 安装后不稳_董女士 | installation | 0.842 | 3 | Y |
| C036 | 配件不匹配_蔡先生 | installation | 0.787 | 3 | N |
| C037 | 宝宝受伤_陆妈妈 | complaint_high_risk | 0.741 | 3 | N |
| C038 | 12315威胁_汪女士 | complaint_high_risk | 0.815 | 3 | N |
| C039 | 曝光威胁_白女士 | complaint_high_risk | 0.815 | 3 | N |
| C040 | 假货质疑_江先生 | complaint_high_risk | 0.732 | 3 | N |
| C041 | 严重破损_孟女士 | complaint_high_risk | 0.787 | 3 | N |
| C042 | 反复出问题_沈女士 | complaint_high_risk | 0.759 | 3 | N |
| C043 | 辱骂客服_叶先生 | complaint_high_risk | 0.731 | 3 | N |
| C044 | 职业打假_秦先生 | complaint_high_risk | 0.815 | 3 | N |
| C045 | 模糊意图_只说在吗 | edge_composite | 0.820 | 2 | N |
| C046 | 多意图混合_咨询+投诉 | edge_composite | 0.750 | 3 | N |
| C047 | 误导性信息_错误订单号 | edge_composite | 0.722 | 3 | N |
| C048 | 方言错别字_理解困难 | edge_composite | 0.889 | 3 | N |
| C049 | 反复变卦_今天买明天退 | edge_composite | 0.741 | 3 | N |
| C050 | 超长会话_20轮马拉松 | edge_composite | 0.872 | 20 | N |

## Failed Turns

### C001 Turn 1 (score: 0.694)
- Failure types: required_tool_missing, slow_response
- intent_match: Expected 'product_question', got 'general'

### C001 Turn 2 (score: 0.972)
- Failure types: guard_failure

### C001 Turn 3 (score: 0.944)
- Failure types: guard_failure

### C002 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C002 Turn 2 (score: 0.972)
- Failure types: guard_failure

### C003 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C003 Turn 2 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C003 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C004 Turn 1 (score: 0.806)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'product_question'

### C004 Turn 2 (score: 0.778)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'product_question'

### C004 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C005 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'installation'

### C006 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C007 Turn 1 (score: 0.722)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'pre_sale_purchase_guidance', got 'logistics_eta'

### C007 Turn 2 (score: 0.861)
- Failure types: guard_failure
- intent_match: Expected 'pre_sale_purchase_guidance', got 'product_question'

### C007 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C008 Turn 2 (score: 0.889)
- Failure types: slow_response

### C009 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C010 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C010 Turn 2 (score: 0.861)
- Failure types: guard_failure
- intent_match: Expected 'pre_sale_purchase_guidance', got 'product_question'

### C011 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C011 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'pre_sale_purchase_guidance', got 'general'

### C012 Turn 2 (score: 0.972)
- Failure types: guard_failure

### C013 Turn 1 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C013 Turn 2 (score: 0.889)
- Failure types: required_tool_missing, guard_failure

### C013 Turn 3 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'logistics_eta', got 'product_question'

### C014 Turn 1 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C014 Turn 2 (score: 0.889)
- Failure types: required_tool_missing, guard_failure

### C014 Turn 3 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'logistics_eta', got 'product_question'

### C015 Turn 1 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C015 Turn 2 (score: 0.889)
- Failure types: required_tool_missing, guard_failure

### C015 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C016 Turn 1 (score: 0.833)
- Failure types: required_tool_missing

### C016 Turn 2 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C016 Turn 3 (score: 0.806)
- Failure types: required_tool_missing, guard_failure

### C017 Turn 1 (score: 0.694)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C017 Turn 2 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C017 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C018 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'product_question'

### C018 Turn 2 (score: 0.694)
- Failure types: required_tool_missing, slow_response, guard_failure
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C018 Turn 3 (score: 0.889)
- Failure types: required_tool_missing, guard_failure

### C019 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C019 Turn 2 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'aftersales'

### C019 Turn 3 (score: 0.833)
- Failure types: required_tool_missing, guard_failure

### C020 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'general'

### C020 Turn 2 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'general'

### C020 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'complaint'

### C021 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C021 Turn 2 (score: 0.806)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C021 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C022 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C022 Turn 2 (score: 0.806)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C022 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C023 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_missing_part', got 'installation'

### C023 Turn 2 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_missing_part', got 'product_question'

### C023 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_missing_part', got 'aftersales'

### C024 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_damage', got 'general'

### C024 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_damage', got 'general'

### C024 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_damage', got 'aftersales'

### C025 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C025 Turn 2 (score: 0.806)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C025 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C026 Turn 1 (score: 0.694)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C026 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C026 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C027 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_missing_part', got 'product_question'

### C027 Turn 2 (score: 0.694)
- Failure types: required_tool_missing, slow_response, guard_failure
- intent_match: Expected 'after_sale_missing_part', got 'product_question'

### C027 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_missing_part', got 'general'

### C028 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C028 Turn 2 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C028 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C029 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C029 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C029 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C030 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C030 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C030 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C031 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C031 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C031 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C032 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C032 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C032 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'general'

### C033 Turn 1 (score: 0.694)
- Failure types: required_tool_missing, slow_response
- intent_match: Expected 'after_sale_installation', got 'installation'

### C033 Turn 2 (score: 0.806)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_installation', got 'product_question'

### C033 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'general'

### C034 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'product_question'

### C034 Turn 2 (score: 0.728)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'installation'

### C034 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'aftersales'

### C036 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'installation'

### C036 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_installation', got 'aftersales'

### C036 Turn 3 (score: 0.861)
- Failure types: guard_failure
- intent_match: Expected 'after_sale_installation', got 'product_question'

### C037 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'safety_risk', got 'general'

### C037 Turn 2 (score: 0.611)
- Failure types: high_risk_missed, required_tool_missing
- intent_match: Expected 'safety_risk', got 'general'
- risk_recall: High-risk keywords: 流血. risk_level=low, review=False

### C038 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C039 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'product_question'

### C039 Turn 2 (score: 0.861)
- Failure types: guard_failure
- intent_match: Expected 'complaint_risk', got 'general'

### C039 Turn 3 (score: 0.833)
- Failure types: guard_failure
- intent_match: Expected 'complaint_risk', got 'general'

### C040 Turn 1 (score: 0.639)
- Failure types: high_risk_missed, required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'
- risk_recall: High-risk keywords: 假货. risk_level=low, review=False

### C040 Turn 2 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'complaint_risk', got 'product_question'

### C041 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_damage', got 'general'

### C041 Turn 2 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'after_sale_damage', got 'product_question'

### C042 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'aftersales'

### C042 Turn 3 (score: 0.667)
- Failure types: required_tool_missing, slow_response
- intent_match: Expected 'complaint_risk', got 'aftersales'

### C043 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C043 Turn 2 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C043 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C044 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C045 Turn 1 (score: 0.806)
- Failure types: slow_response, guard_failure
- intent_match: Expected 'unknown', got 'product_question'

### C045 Turn 2 (score: 0.833)
- Failure types: guard_failure
- intent_match: Expected 'unknown', got 'product_question'

### C046 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'product_question'

### C046 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'complaint_risk', got 'general'

### C046 Turn 3 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'complaint_risk', got 'product_question'

### C047 Turn 1 (score: 0.750)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'logistics_eta', got 'product_question'

### C047 Turn 2 (score: 0.667)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'product_question'

### C047 Turn 3 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'logistics_eta', got 'general'

### C048 Turn 1 (score: 0.972)
- Failure types: guard_failure

### C048 Turn 3 (score: 0.722)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'product_question', got 'logistics_eta'

### C049 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'aftersales'

### C049 Turn 2 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C049 Turn 3 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'after_sale_return_refund', got 'product_question'

### C050 Turn 1 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C050 Turn 2 (score: 0.972)
- Failure types: guard_failure

### C050 Turn 4 (score: 0.972)
- Failure types: guard_failure

### C050 Turn 5 (score: 0.944)
- Failure types: guard_failure

### C050 Turn 6 (score: 0.889)
- Failure types: guard_failure

### C050 Turn 7 (score: 0.944)
- Failure types: guard_failure

### C050 Turn 11 (score: 0.722)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'product_question', got 'logistics_eta'

### C050 Turn 12 (score: 0.694)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'product_question', got 'logistics_eta'

### C050 Turn 13 (score: 0.972)
- Failure types: guard_failure

### C050 Turn 14 (score: 0.750)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C050 Turn 15 (score: 0.694)
- Failure types: required_tool_missing, guard_failure
- intent_match: Expected 'product_question', got 'logistics_eta'

### C050 Turn 16 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C050 Turn 17 (score: 0.722)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

## Bad Case Candidates

- **Total candidates**: 261
- By type: {'intent_error': 110, 'required_tool_missing': 115, 'unknown': 7, 'context_memory_error': 27, 'risk_missed': 2}
- **Directory**: `D:\桌面文件\客服\copilot\tests\golden_cases\simulated_customers\candidates`
