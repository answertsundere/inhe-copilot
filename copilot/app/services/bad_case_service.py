"""
Bad Case 数据模型与服务

自动从 feedback 和 guard 事件中创建 Bad Case 候选，
支持标注、筛选、回归测试导出。
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
import tempfile
from datetime import datetime
from typing import Optional

from app.config import BASE_DIR

BAD_CASES_FILE = os.environ.get(
    "COPILOT_BAD_CASES_FILE",
    os.path.join(BASE_DIR, "data", "bad_cases.jsonl"),
)

FAILURE_TYPES = (
    "capture_error", "intent_error", "identifier_error", "routing_error",
    "tool_error", "product_mapping_error", "rag_miss", "rag_wrong_scope",
    "evidence_filter_error", "grounding_error", "reply_quality_error",
    "context_memory_error", "risk_error", "performance_error", "unknown",
)

SEVERITY_LEVELS = ("P0", "P1", "P2", "P3")

STATUS_FLOW = ("open", "triaged", "fixing", "fixed", "verified", "wont_fix")


def _new_id() -> str:
    return "BC-" + uuid.uuid4().hex[:6].upper()


def _now() -> str:
    return datetime.now().isoformat()


class BadCaseStore:
    """JSONL-based Bad Case 存储（线程安全、原子写入）。"""

    _global_lock = threading.Lock()

    def __init__(self, filepath: str = ""):
        self.filepath = filepath or BAD_CASES_FILE
        self._ensure_dir()

    def _ensure_dir(self):
        dirpath = os.path.dirname(self.filepath)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

    def create(self, case: dict) -> dict:
        """创建 Bad Case（线程安全、原子追加）。"""
        case.setdefault("id", _new_id())
        case.setdefault("status", "open")
        case.setdefault("failure_type", "unknown")
        case.setdefault("severity", "P2")
        case.setdefault("created_at", _now())
        case.setdefault("updated_at", _now())
        # Validate fields
        if case.get("failure_type") not in FAILURE_TYPES:
            case["failure_type"] = "unknown"
        if case.get("severity") not in SEVERITY_LEVELS:
            case["severity"] = "P2"
        if case.get("status") not in STATUS_FLOW:
            case["status"] = "open"
        # Ensure required fields
        for field in ("request_id", "message_id", "customer_message"):
            case.setdefault(field, "")
        for field in ("conversation_history_json", "sidecar_context_json",
                      "expected_intent", "actual_intent",
                      "expected_tools_json", "actual_tools_json",
                      "retrieved_evidence_json", "used_evidence_json",
                      "ai_suggested_reply", "csr_final_reply",
                      "csr_action", "failure_layer", "root_cause",
                      "fix_note", "regression_test_id",
                      "reviewer", "scenario", "source",
                      "graph_version", "prompt_version", "knowledge_version", "model_name"):
            case.setdefault(field, "")

        with self._global_lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")
        return case

    def load_all(self, limit: int = 10000) -> list:
        if not os.path.exists(self.filepath):
            return []
        records = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return records[:limit]

    def get_by_id(self, case_id: str) -> Optional[dict]:
        for r in self.load_all(limit=100000):
            if r.get("id") == case_id:
                return r
        return None

    def update(self, case_id: str, updates: dict) -> Optional[dict]:
        """更新 Bad Case（全量重写文件）。"""
        records = self.load_all(limit=100000)
        found = None
        for r in records:
            if r.get("id") == case_id:
                r.update(updates)
                r["updated_at"] = _now()
                found = r
                break
        if found:
            self._rewrite(records)
        return found

    def delete(self, case_id: str) -> bool:
        records = self.load_all(limit=100000)
        new_records = [r for r in records if r.get("id") != case_id]
        if len(new_records) < len(records):
            self._rewrite(new_records)
            return True
        return False

    def _rewrite(self, records: list):
        """原子写入：先写临时文件再替换。"""
        dirpath = os.path.dirname(self.filepath) or "."
        with self._global_lock:
            fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix=".jsonl")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                os.replace(tmp_path, self.filepath)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def query(
        self,
        status: str = "",
        failure_type: str = "",
        severity: str = "",
        scenario: str = "",
        intent: str = "",
        tool_name: str = "",
        graph_version: str = "",
        prompt_version: str = "",
        model_name: str = "",
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """分页筛选 Bad Cases。"""
        records = self.load_all(limit=100000)

        if status:
            records = [r for r in records if r.get("status") == status]
        if failure_type:
            records = [r for r in records if r.get("failure_type") == failure_type]
        if severity:
            records = [r for r in records if r.get("severity") == severity]
        if scenario:
            records = [r for r in records if r.get("scenario") == scenario]
        if intent:
            records = [r for r in records if intent in (r.get("actual_intent", ""), r.get("expected_intent", ""))]
        if tool_name:
            records = [r for r in records if tool_name in json.dumps(r.get("actual_tools_json", ""))]
        if graph_version:
            records = [r for r in records if r.get("graph_version") == graph_version]
        if prompt_version:
            records = [r for r in records if r.get("prompt_version") == prompt_version]
        if model_name:
            records = [r for r in records if r.get("model_name") == model_name]
        if date_from:
            records = [r for r in records if r.get("created_at", "") >= date_from]
        if date_to:
            records = [r for r in records if r.get("created_at", "") <= date_to]

        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        items = records[start:end]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
        }

    def get_metrics(self) -> dict:
        """Bad Case 指标。"""
        records = self.load_all(limit=100000)
        total = len(records)

        by_status = {}
        by_severity = {}
        by_failure_type = {}
        for r in records:
            s = r.get("status", "open")
            by_status[s] = by_status.get(s, 0) + 1
            sev = r.get("severity", "P2")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            ft = r.get("failure_type", "unknown")
            by_failure_type[ft] = by_failure_type.get(ft, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "by_severity": by_severity,
            "by_failure_type": by_failure_type,
            "open_count": by_status.get("open", 0),
            "verified_count": by_status.get("verified", 0),
        }


# ========== Auto-creation logic ==========

def should_auto_create_bad_case(
    action: str = "",
    execution_debug: dict | None = None,
    evidence_debug: dict | None = None,
    final_reply: str = "",
    suggested_reply: str = "",
) -> tuple[bool, str]:
    """判断是否应自动创建 Bad Case 候选。返回 (should_create, reason)。"""
    ed = execution_debug or {}
    eved = evidence_debug or {}

    # 1. csr_action=rejected
    if action == "rejected":
        return True, "rejected"

    # 2. csr_action=edited 且事实字段变化
    if action == "edited" and suggested_reply and final_reply:
        if _has_fact_change(suggested_reply, final_reply):
            return True, "edited_fact_change"

    # 3. tool error/timeout
    for tc in ed.get("tool_calls", []):
        if tc.get("status") in ("error", "timeout"):
            return True, f"tool_error:{tc.get('tool_name', '')}"

    # 5. RAG miss
    rag = ed.get("rag", {})
    if rag and rag.get("metrics", {}).get("retrieved_count", 0) == 0:
        routing = ed.get("routing", {})
        if routing.get("final_intent") in ("product_question", "product_consult"):
            return True, "rag_miss"

    # 6. hallucination_guard fallback
    for g in ed.get("guards", []):
        if g.get("guard_name") == "hallucination_guard" and not g.get("passed"):
            return True, "hallucination_blocked"

    # 7. factual_guard rewrite
    for g in ed.get("guards", []):
        if g.get("guard_name") == "factual_guard" and not g.get("passed"):
            return True, "factual_guard_rewrite"

    # 8. intent 被 validation/fusion 修正
    routing = ed.get("routing", {})
    overrides = routing.get("overrides", [])
    if overrides:
        return True, "intent_corrected"

    return False, ""


def create_bad_case_from_context(
    store: BadCaseStore,
    action: str,
    reason: str,
    execution_debug: dict | None = None,
    evidence_debug: dict | None = None,
    customer_message: str = "",
    suggested_reply: str = "",
    final_reply: str = "",
    conversation_id: str = "",
    scenario: str = "",
    source: str = "",
    reject_reason: str = "",
) -> dict:
    """从上下文创建 Bad Case 候选。"""
    ed = execution_debug or {}
    routing = ed.get("routing", {})
    gen = ed.get("generation", {})
    ver = ed.get("versions", {})

    case = {
        "request_id": ed.get("request", {}).get("request_id", ""),
        "message_id": ed.get("request", {}).get("message_id", ""),
        "conversation_id": conversation_id,
        "scenario": scenario,
        "source": source,
        "customer_message": customer_message,
        "actual_intent": routing.get("final_intent", ""),
        "actual_tools_json": json.dumps([
            tc.get("tool_name") for tc in ed.get("tool_calls", [])
            if tc.get("status") not in ("skipped", "planned")
        ], ensure_ascii=False),
        "ai_suggested_reply": suggested_reply,
        "csr_final_reply": final_reply,
        "csr_action": action,
        "failure_type": _infer_failure_type(reason),
        "auto_create_reason": reason,
        "reject_reason": reject_reason,
        "graph_version": ver.get("graph_version", ""),
        "prompt_version": ver.get("prompt_version", ""),
        "knowledge_version": ver.get("knowledge_version", ""),
        "model_name": ver.get("model_name", ""),
        "execution_debug_json": json.dumps(ed, ensure_ascii=False),
    }

    return store.create(case)


def _infer_failure_type(reason: str) -> str:
    """从自动创建原因推断 failure_type。"""
    if "tool_error" in reason:
        return "tool_error"
    if "rag_miss" in reason:
        return "rag_miss"
    if "hallucination" in reason:
        return "grounding_error"
    if "factual_guard" in reason:
        return "grounding_error"
    if "intent_corrected" in reason:
        return "intent_error"
    if "fact_change" in reason:
        return "reply_quality_error"
    if "rejected" in reason:
        return "unknown"
    if "human_review" in reason:
        return "risk_error"
    return "unknown"


def _has_fact_change(suggested: str, final: str) -> bool:
    """检测事实字段是否发生变化（数字、材质、物流状态、商品名称、赔偿）。"""
    if not suggested or not final:
        return False

    # Number change
    s_nums = set(re.findall(r'\d+\.?\d*', suggested))
    f_nums = set(re.findall(r'\d+\.?\d*', final))
    if s_nums != f_nums:
        return True

    # Material/product terms change
    material_terms = ["实木", "松木", "橡胶木", "PP塑料", "ABS", "记忆棉", "海绵", "棉", "涤纶", "不锈钢"]
    for term in material_terms:
        if (term in suggested) != (term in final):
            return True

    # Logistics status change
    status_terms = ["已发货", "已签收", "待发货", "运输中", "派件中", "已揽收"]
    for term in status_terms:
        if (term in suggested) != (term in final):
            return True

    # Compensation promises
    comp_terms = ["赔偿", "退款", "补偿", "免单", "包邮", "返现"]
    for term in comp_terms:
        if (term in suggested) != (term in final):
            return True

    return False


def compute_edit_diff(suggested: str, final: str) -> dict:
    """计算 AI 回复与最终回复的差异摘要。"""
    if not suggested or not final:
        return {}

    # Simple text similarity (character overlap)
    s_chars = set(suggested)
    f_chars = set(final)
    if not s_chars and not f_chars:
        similarity = 1.0
    elif not s_chars or not f_chars:
        similarity = 0.0
    else:
        similarity = len(s_chars & f_chars) / max(len(s_chars | f_chars), 1)

    has_fact = _has_fact_change(suggested, final)

    return {
        "text_similarity": round(similarity, 2),
        "changed_numbers": list(set(re.findall(r'\d+\.?\d*', final)) - set(re.findall(r'\d+\.?\d*', suggested))),
        "changed_order_status": any(
            (t in suggested) != (t in final)
            for t in ["已发货", "已签收", "待发货"]
        ),
        "changed_product_fact_terms": [
            t for t in ["实木", "PP塑料", "ABS", "记忆棉", "海绵"]
            if (t in suggested) != (t in final)
        ],
        "tone_only_change": not has_fact and similarity > 0.8,
        "possible_fact_correction": has_fact,
    }
