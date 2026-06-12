# Simulation Run Report: sim_20260607_152210_8af285

## Run Configuration

- **Run ID**: sim_20260607_152210_8af285
- **Mode**: service
- **Offline**: True
- **Started**: 2026-06-07T07:22:10.729339+00:00
- **Completed**: 2026-06-07T07:22:17.621222+00:00
- **Customers**: 1

## Summary

- **Total Customers**: 1
- **Customers Passed**: 0
- **Pass Rate**: 0.0%
- **Average Score**: 0.881
- **Min Score**: 0.881
- **Max Score**: 0.881

### Dimension Averages

| Dimension | Average Score |
|-----------|--------------|
| context_memory | 0.917 |
| grounding | 1.000 |
| intent_match | 0.667 |
| performance | 0.933 |
| reply_quality | 1.000 |
| risk_recall | 1.000 |
| tool_routing | 0.667 |
| trace_completeness | 0.750 |
| trap_detection | 1.000 |

### Scores by Scenario

| Scenario | Avg Score |
|----------|-----------|
| pre_sale_product | 0.881 |

## Intent Confusion Matrix

- **Overall Accuracy**: 66.7% (2/3)

| Expected \ Actual | general | product_question |
|---|---|---|
| general | 0 | 0 |
| product_question | 1 | 2 |

### Top Misclassifications

| Expected | Actual | Count |
|----------|--------|-------|
| product_question | general | 1 |

## Tool Accuracy

- **Accuracy**: 66.7% (4/6)

## Risk Recall

- **High-risk messages detected**: 0
- **Correctly handled**: 0

## Grounding

- **Average Score**: 1.000

## Context Memory

- **Average Score**: 0.917
- **Turns with Issues**: 1/3

## Customer Results

| ID | Name | Scenario | Score | Turns | Passed |
|----|------|----------|-------|-------|--------|
| C001 | 新手妈妈_小林 | pre_sale_product | 0.881 | 3 | N |

## Failed Turns

### C001 Turn 1 (score: 0.728)
- Failure types: required_tool_missing
- intent_match: Expected 'product_question', got 'general'

### C001 Turn 2 (score: 0.972)
- Failure types: guard_failure

### C001 Turn 3 (score: 0.944)
- Failure types: guard_failure

## Bad Case Candidates

- **Total candidates**: 4
- By type: {'intent_error': 1, 'required_tool_missing': 1, 'unknown': 1, 'context_memory_error': 1}
- **Directory**: `D:\桌面文件\客服\copilot\tests\golden_cases\simulated_customers\candidates`
