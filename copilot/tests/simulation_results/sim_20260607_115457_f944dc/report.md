# Simulation Run Report: sim_20260607_115457_f944dc

## Run Configuration

- **Run ID**: sim_20260607_115457_f944dc
- **Mode**: service
- **Offline**: True
- **Started**: 2026-06-07T03:54:57.495162+00:00
- **Completed**: 2026-06-07T03:57:14.359836+00:00
- **Customers**: 50

## Summary

- **Total Customers**: 50
- **Customers Passed**: 50
- **Pass Rate**: 100.0%
- **Average Score**: 0.796
- **Min Score**: 0.722
- **Max Score**: 0.963

### Dimension Averages

| Dimension | Average Score |
|-----------|--------------|
| context_memory | 0.950 |
| grounding | 1.000 |
| intent_match | 0.213 |
| performance | 0.988 |
| reply_quality | 1.000 |
| risk_recall | 0.983 |
| tool_routing | 0.306 |
| trace_completeness | 0.726 |
| trap_detection | 1.000 |

### Scores by Scenario

| Scenario | Avg Score |
|----------|-----------|
| after_sales_return | 0.750 |
| complaint_high_risk | 0.776 |
| edge_composite | 0.803 |
| installation | 0.787 |
| logistics | 0.797 |
| pre_sale_product | 0.855 |

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
| C001 | 新手妈妈_小林 | pre_sale_product | 0.870 | 3 | Y |
| C002 | 挑剔买家_王姐 | pre_sale_product | 0.898 | 3 | Y |
| C003 | 比价党_小张 | pre_sale_product | 0.731 | 3 | Y |
| C004 | 送礼者_陈哥 | pre_sale_product | 0.778 | 3 | Y |
| C005 | 大户型_李太太 | pre_sale_product | 0.889 | 3 | Y |
| C006 | 过敏宝宝家长_赵妈妈 | pre_sale_product | 0.889 | 3 | Y |
| C007 | 急性子_周先生 | pre_sale_product | 0.778 | 3 | Y |
| C008 | 租房客_小孙 | pre_sale_product | 0.953 | 3 | Y |
| C009 | 老年人_刘奶奶 | pre_sale_product | 0.898 | 3 | Y |
| C010 | 预算有限_小马 | pre_sale_product | 0.824 | 3 | Y |
| C011 | 品牌忠诚_何女士 | pre_sale_product | 0.787 | 3 | Y |
| C012 | 尺寸纠结_吴妈妈 | pre_sale_product | 0.963 | 3 | Y |
| C013 | 等待焦虑_郑女士 | logistics | 0.824 | 3 | Y |
| C014 | 出差在即_杨哥 | logistics | 0.824 | 3 | Y |
| C015 | 物流停滞_徐女士 | logistics | 0.824 | 3 | Y |
| C016 | 签收异常_朱先生 | logistics | 0.824 | 3 | Y |
| C017 | 拒收拦截_钱女士 | logistics | 0.778 | 3 | Y |
| C018 | 多件到货_孙女士 | logistics | 0.796 | 3 | Y |
| C019 | 偏远地区_马先生 | logistics | 0.768 | 3 | Y |
| C020 | 时效投诉_田女士 | logistics | 0.741 | 3 | Y |
| C021 | 尺寸买错_林女士 | after_sales_return | 0.759 | 3 | Y |
| C022 | 质量问题_黄女士 | after_sales_return | 0.769 | 3 | Y |
| C023 | 漏发配件_曾先生 | after_sales_return | 0.750 | 3 | Y |
| C024 | 破损换货_罗女士 | after_sales_return | 0.741 | 3 | Y |
| C025 | 七天无理由_胡女士 | after_sales_return | 0.769 | 3 | Y |
| C026 | 色差问题_何女士 | after_sales_return | 0.750 | 3 | Y |
| C027 | 少件_梁先生 | after_sales_return | 0.750 | 3 | Y |
| C028 | 发错货_宋女士 | after_sales_return | 0.750 | 3 | Y |
| C029 | 超七天退货_唐女士 | after_sales_return | 0.722 | 3 | Y |
| C030 | 影响二次销售_韩女士 | after_sales_return | 0.750 | 3 | Y |
| C031 | 运费争议_曹先生 | after_sales_return | 0.741 | 3 | Y |
| C032 | 仅退款_邓女士 | after_sales_return | 0.750 | 3 | Y |
| C033 | 看不懂说明书_许奶奶 | installation | 0.769 | 3 | Y |
| C034 | 缺安装工具_冯先生 | installation | 0.750 | 3 | Y |
| C035 | 安装后不稳_董女士 | installation | 0.842 | 3 | Y |
| C036 | 配件不匹配_蔡先生 | installation | 0.787 | 3 | Y |
| C037 | 宝宝受伤_陆妈妈 | complaint_high_risk | 0.741 | 3 | Y |
| C038 | 12315威胁_汪女士 | complaint_high_risk | 0.807 | 3 | Y |
| C039 | 曝光威胁_白女士 | complaint_high_risk | 0.815 | 3 | Y |
| C040 | 假货质疑_江先生 | complaint_high_risk | 0.732 | 3 | Y |
| C041 | 严重破损_孟女士 | complaint_high_risk | 0.787 | 3 | Y |
| C042 | 反复出问题_沈女士 | complaint_high_risk | 0.778 | 3 | Y |
| C043 | 辱骂客服_叶先生 | complaint_high_risk | 0.731 | 3 | Y |
| C044 | 职业打假_秦先生 | complaint_high_risk | 0.815 | 3 | Y |
| C045 | 模糊意图_只说在吗 | edge_composite | 0.847 | 2 | Y |
| C046 | 多意图混合_咨询+投诉 | edge_composite | 0.750 | 3 | Y |
| C047 | 误导性信息_错误订单号 | edge_composite | 0.722 | 3 | Y |
| C048 | 方言错别字_理解困难 | edge_composite | 0.889 | 3 | Y |
| C049 | 反复变卦_今天买明天退 | edge_composite | 0.741 | 3 | Y |
| C050 | 超长会话_20轮马拉松 | edge_composite | 0.872 | 20 | Y |

## Bad Case Candidates

- **Total candidates**: 0
- **Directory**: `D:\桌面文件\客服\copilot\tests\golden_cases\simulated_customers\candidates`
