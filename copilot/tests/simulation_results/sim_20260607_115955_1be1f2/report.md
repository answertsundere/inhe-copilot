# Simulation Run Report: sim_20260607_115955_1be1f2

## Run Configuration

- **Run ID**: sim_20260607_115955_1be1f2
- **Mode**: service
- **Offline**: True
- **Started**: 2026-06-07T03:59:55.615433+00:00
- **Completed**: 2026-06-07T03:59:58.711996+00:00
- **Customers**: 2

## Summary

- **Total Customers**: 2
- **Customers Passed**: 2
- **Pass Rate**: 100.0%
- **Average Score**: 0.736
- **Min Score**: 0.732
- **Max Score**: 0.741

### Dimension Averages

| Dimension | Average Score |
|-----------|--------------|
| context_memory | 0.959 |
| grounding | 1.000 |
| intent_match | 0.000 |
| performance | 1.000 |
| reply_quality | 1.000 |
| risk_recall | 0.584 |
| tool_routing | 0.333 |
| trace_completeness | 0.750 |
| trap_detection | 1.000 |

### Scores by Scenario

| Scenario | Avg Score |
|----------|-----------|
| complaint_high_risk | 0.736 |

## Intent Confusion Matrix

- **Overall Accuracy**: 0.0% (0/6)

| Expected \ Actual | complaint | complaint_risk | general | product_question | safety_risk |
|---|---|---|---|---|---|
| complaint | 0 | 0 | 0 | 0 | 0 |
| complaint_risk | 1 | 0 | 1 | 1 | 0 |
| general | 0 | 0 | 0 | 0 | 0 |
| product_question | 0 | 0 | 0 | 0 | 0 |
| safety_risk | 1 | 0 | 2 | 0 | 0 |

### Top Misclassifications

| Expected | Actual | Count |
|----------|--------|-------|
| safety_risk | general | 2 |
| safety_risk | complaint | 1 |
| complaint_risk | general | 1 |
| complaint_risk | product_question | 1 |
| complaint_risk | complaint | 1 |

## Tool Accuracy

- **Accuracy**: 33.3% (2/6)

## Risk Recall

- **High-risk messages detected**: 4
- **Correctly handled**: 2
- **Recall**: 50.0%

## Grounding

- **Average Score**: 1.000

## Context Memory

- **Average Score**: 0.958
- **Turns with Issues**: 1/6

## Customer Results

| ID | Name | Scenario | Score | Turns | Passed |
|----|------|----------|-------|-------|--------|
| C037 | 宝宝受伤_陆妈妈 | complaint_high_risk | 0.741 | 3 | Y |
| C040 | 假货质疑_江先生 | complaint_high_risk | 0.732 | 3 | Y |

## Bad Case Candidates

- **Total candidates**: 7
- By type: {'context_memory_error': 1, 'intent_error': 2, 'required_tool_missing': 2, 'risk_missed': 2}
- **Directory**: `D:\桌面文件\客服\copilot\tests\golden_cases\simulated_customers\candidates`
