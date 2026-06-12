"""
ToolExecutor — 工具执行器

职责：
- 执行 tool_plan 中的工具调用
- 统一 timeout / 异常捕获
- 记录 trace_steps
- 输出 tool_results
"""

import logging
import re
import time
from typing import Optional

from app.agent.tools.base import ToolSpec
from app.agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)


def _looks_like_sku(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"[A-Z]{2}\d{2}K\d{2}", value, re.IGNORECASE) or re.search(r"[A-Z0-9]+B\d+S\d+", value, re.IGNORECASE))


class ToolExecutor:
    """工具执行器"""

    def __init__(self, registry=None):
        self._registry = registry or get_tool_registry()

    def execute_plan(
        self,
        tool_plan: list[dict],
        state: dict,
        total_timeout_ms: int = 5000,
    ) -> dict:
        """执行工具计划。

        tool_plan: [{"tool_name": str, "inputs": dict}, ...]
        state: 当前 AgentState
        total_timeout_ms: 总超时预算

        Returns:
            {
                "tool_results": {tool_name: result_dict, ...},
                "tool_traces": [trace_dict, ...],
                "total_duration_ms": int,
                "timed_out": bool,
            }
        """
        t0 = time.time()
        tool_results = {}
        tool_traces = []
        timed_out = False

        for call in tool_plan:
            elapsed_ms = int((time.time() - t0) * 1000)
            if elapsed_ms >= total_timeout_ms:
                timed_out = True
                remaining = [c["tool_name"] for c in tool_plan if c["tool_name"] not in tool_results]
                tool_traces.append({
                    "node": "tool_executor",
                    "tool_name": "budget_exhausted",
                    "status": "skipped",
                    "duration_ms": 0,
                    "summary": f"总超时预算 {total_timeout_ms}ms 已用尽，跳过: {remaining}",
                })
                break

            tool_name = call.get("tool_name", "")
            inputs = call.get("inputs", {})

            spec = self._registry.get(tool_name)
            if spec is None:
                tool_traces.append({
                    "node": "tool_executor",
                    "tool_name": tool_name,
                    "status": "not_found",
                    "duration_ms": 0,
                    "summary": f"工具 {tool_name} 未注册",
                    "error_code": "tool_not_found",
                })
                continue

            # 单工具超时 = min(工具自身超时, 剩余总预算)
            remaining_budget = total_timeout_ms - elapsed_ms
            tool_timeout = min(spec.timeout_ms, remaining_budget)

            result, trace = self._execute_single(spec, inputs, state, tool_timeout)
            tool_results[tool_name] = result
            tool_traces.append(trace)

        total_duration_ms = int((time.time() - t0) * 1000)
        return {
            "tool_results": tool_results,
            "tool_traces": tool_traces,
            "total_duration_ms": total_duration_ms,
            "timed_out": timed_out,
        }

    def _execute_single(
        self,
        spec: ToolSpec,
        inputs: dict,
        state: dict,
        timeout_ms: int,
    ) -> tuple[dict, dict]:
        """执行单个工具，返回 (result, trace)"""
        t0 = time.time()

        if spec.handler is None:
            duration_ms = int((time.time() - t0) * 1000)
            return {}, {
                "node": "tool_executor",
                "tool_name": spec.name,
                "status": "no_handler",
                "duration_ms": duration_ms,
                "input_summary": _summarize_inputs(inputs),
                "summary": f"工具 {spec.name} 无 handler",
                "error_code": "no_handler",
            }

        try:
            result = spec.handler(inputs, state)
            duration_ms = int((time.time() - t0) * 1000)

            # 超时检测（事后）
            if duration_ms > timeout_ms:
                logger.warning("工具 %s 超时: %dms > %dms", spec.name, duration_ms, timeout_ms)

            trace = {
                "node": "tool_executor",
                "tool_name": spec.name,
                "status": "success",
                "duration_ms": duration_ms,
                "provider": "tool_registry",
                "input_summary": _summarize_inputs(inputs),
                "output_summary": _summarize_output(result),
                "can_create_fact_types": spec.can_create_fact_types,
                "summary": f"{spec.name}: ok ({duration_ms}ms)",
            }
            return result, trace

        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            error_code = type(e).__name__
            logger.warning("工具 %s 执行失败: %s", spec.name, e)
            return {"error": str(e)}, {
                "node": "tool_executor",
                "tool_name": spec.name,
                "status": "error",
                "duration_ms": duration_ms,
                "provider": "tool_registry",
                "input_summary": _summarize_inputs(inputs),
                "error_code": error_code,
                "summary": f"{spec.name}: {error_code}",
            }


def _summarize_inputs(inputs: dict) -> dict:
    """脱敏摘要输入参数"""
    summary = {}
    for k, v in inputs.items():
        if isinstance(v, str) and len(v) > 30:
            summary[k] = v[:30] + "..."
        elif isinstance(v, list) and len(v) > 3:
            summary[k] = v[:3]
        else:
            summary[k] = v
    return summary


def _summarize_output(result: dict) -> dict:
    """脱敏摘要输出"""
    if not result:
        return {}
    summary = {}
    for k, v in result.items():
        if k == "chunks":
            summary[k] = f"{len(v)} items" if isinstance(v, list) else v
        elif isinstance(v, str) and len(v) > 50:
            summary[k] = v[:50] + "..."
        elif isinstance(v, list):
            summary[k] = f"{len(v)} items"
        else:
            summary[k] = v
    return summary


# ========== Tool Planner ==========

def plan_tools(state: dict) -> dict:
    """工具规划节点。

    如果有 LLM: LLM 在 allowed_tools 中选择，漏选 required_tools 自动补上，选了 forbidden_tools 丢弃。
    如果无 LLM: 直接执行 required_tools。
    """
    from app.agent.tools.registry import get_tool_registry

    t0 = time.time()
    _metrics_increment("request_tool_planner_count")
    registry = get_tool_registry()

    allowed_tools = state.get("allowed_tools", [])
    required_tools = state.get("required_tools", [])
    forbidden_tools = state.get("forbidden_tools", [])
    intent = state.get("intent", "general")
    risk_level = state.get("risk_level", "low")
    msg = state.get("normalized_message", state.get("customer_message", ""))
    slots = state.get("slots", {})

    identity = state.get("order_product_identity") or {}
    if identity.get("source") == "sidecar_product_name" and identity.get("status") == "ambiguous":
        # Only skip tools when there are truly multiple distinct candidates
        candidates = identity.get("candidates") or []
        distinct_ids = set()
        for c in candidates:
            if not isinstance(c, dict):
                continue
            pid = c.get("i_id") or c.get("name") or ""
            if pid:
                distinct_ids.add(pid)
        if len(distinct_ids) >= 2:
            trace = {
                "node": "tool_planner",
                "status": "skipped",
                "duration_ms": int((time.time() - t0) * 1000),
                "cache_hit": False,
                "planner_source": "ambiguous_product_guard",
                "selected_tools": [],
                "required_tools": required_tools,
                "allowed_tools": allowed_tools,
                "forbidden_tools": forbidden_tools,
                "summary": "ambiguous sidecar product name (multiple products); skip tools",
            }
            return {
                "tool_plan": [],
                "tool_planner_source": "ambiguous_product_guard",
                "answer_mode": "no_evidence_clarification",
                "should_query_knowledge": False,
                "trace_steps": state.get("trace_steps", []) + [trace],
            }

    # 构建每个工具的默认 inputs
    default_inputs = _build_default_inputs(state)

    # 尝试用 LLM 选择工具
    llm_plan = _try_llm_tool_selection(state, allowed_tools, forbidden_tools, registry)

    if llm_plan is not None:
        # LLM 选择了工具
        selected_names = [c["tool_name"] for c in llm_plan]
        # 补上遗漏的 required_tools
        for rt in required_tools:
            if rt not in selected_names and rt in allowed_tools:
                llm_plan.append({"tool_name": rt, "inputs": default_inputs.get(rt, {})})
                selected_names.append(rt)
        plan = llm_plan
        source = "llm"
    else:
        # 无 LLM，直接执行 required_tools
        plan = [
            {"tool_name": rt, "inputs": default_inputs.get(rt, {})}
            for rt in required_tools if rt in allowed_tools
        ]
        source = "auto_required"

    # 安全过滤：移除 forbidden 和不在 allowed 中的工具
    safe_plan = []
    for call in plan:
        tn = call.get("tool_name", "")
        if tn in forbidden_tools:
            continue
        if allowed_tools and tn not in allowed_tools:
            continue
        if not registry.get(tn):
            continue
        # 合并默认 inputs。LLM 可能只给部分参数，不能让空 source_types
        # 覆盖系统根据 state 推导出的必填检索范围。
        merged_inputs = dict(default_inputs.get(tn, {}))
        for key, value in (call.get("inputs") or {}).items():
            if tn == "rag_search_tool" and key in {"source_types", "product_scope", "product_name", "sku_name"}:
                # 这些字段来自策略路由和已解析商品身份，比 LLM 自行填写更可信。
                continue
            if value not in ("", None, [], {}):
                merged_inputs[key] = value
        call["inputs"] = merged_inputs
        safe_plan.append(call)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "tool_planner",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "planner_source": source,
        "selected_tools": [c["tool_name"] for c in safe_plan],
        "required_tools": required_tools,
        "allowed_tools": allowed_tools,
        "forbidden_tools": forbidden_tools,
        "summary": f"planner={source}, tools={[c['tool_name'] for c in safe_plan]}",
    }

    return {
        "tool_plan": safe_plan,
        "tool_planner_source": source,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }


def _build_default_inputs(state: dict) -> dict:
    """根据 state 为每个工具构建默认 inputs"""
    msg = state.get("normalized_message", state.get("customer_message", ""))
    slots = state.get("slots", {})
    intent = state.get("intent", "general")
    identity = state.get("order_product_identity") or {}
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or slots.get("product_name", "")
    )
    slot_sku = slots.get("sku_name") or slots.get("sku_code") or ""
    sku_name = slot_sku if _looks_like_sku(slot_sku) else (identity.get("sku_id") or identity.get("i_id") or slot_sku)

    product_scope = [product_name] if product_name else []
    for value in identity.get("candidates", []) or []:
        if value and value not in product_scope:
            product_scope.append(value)
    for candidate in state.get("product_candidates", []) or []:
        if isinstance(candidate, str):
            values = [candidate]
        elif isinstance(candidate, dict):
            values = [
                str(candidate.get(k) or "").strip()
                for k in ("value", "name", "product_name", "title", "sku_name", "sku_id", "i_id")
            ]
        else:
            values = []
        for value in values:
            if value and value not in product_scope:
                product_scope.append(value)

    return {
        "jst_lookup_order_tool": {
            "identifier": slots.get("order_id", ""),
            "identifier_type": slots.get("identifier_type", "internal_order_id"),
        },
        "jst_lookup_outbound_tool": {
            "outer_so_id": slots.get("platform_trade_id", ""),
        },
        "jst_lookup_tracking_tool": {
            "tracking_no": slots.get("tracking_no", ""),
        },
        "rag_search_tool": {
            "query": msg,
            "source_types": state.get("allowed_source_types", []),
            "intent": intent,
            "product_scope": product_scope,
            "product_name": product_name,
            "sku_name": sku_name,
            "fact_type": state.get("query_fact_type", ""),
        },
        "product_resolver_tool": {
            "message": msg,
        },
        "sop_lookup_tool": {
            "message": msg,
            "intent": intent,
        },
        "template_select_tool": {
            "message": msg,
            "intent": intent,
        },
    }


def _try_llm_tool_selection(
    state: dict,
    allowed_tools: list,
    forbidden_tools: list,
    registry,
) -> Optional[list]:
    """尝试用 LLM 从 allowed_tools 中选择工具。返回 tool_calls list 或 None。"""
    try:
        from app.llm.client import get_llm_client
        llm_client = get_llm_client()
        if not llm_client or not llm_client.api_key:
            return None

        import json
        tool_metas = registry.get_tool_metas(allowed_tools)
        if not tool_metas:
            return None

        msg = state.get("normalized_message", state.get("customer_message", ""))
        intent = state.get("intent", "general")
        slots = state.get("slots", {})

        system_prompt = f"""你是客服系统的工具选择器。根据用户消息和意图，从可用工具中选择要调用的工具。

可用工具: {json.dumps(tool_metas, ensure_ascii=False)}

禁止工具: {json.dumps(forbidden_tools, ensure_ascii=False)}

输出 JSON:
{{"tool_calls": [{{"tool_name": "工具名", "inputs": {{"参数名": "值"}}}}]}}

规则:
- 只能选择可用工具列表中的工具
- 不要选择禁止工具
- 根据意图选择最相关的工具
- 物流查询有订单号选 jst_lookup_order_tool，有外部交易号选 jst_lookup_outbound_tool
- 商品咨询选 product_resolver_tool + rag_search_tool
- 投诉选 sop_lookup_tool
"""

        response = llm_client.client.chat.completions.create(
            model=llm_client.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({
                    "message": msg,
                    "intent": intent,
                    "identifier_type": slots.get("identifier_type", ""),
                    "platform_trade_id": slots.get("platform_trade_id", ""),
                    "order_id": slots.get("order_id", ""),
                    "tracking_no": slots.get("tracking_no", ""),
                }, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        tool_calls = parsed.get("tool_calls", [])

        # 验证每调用
        valid_calls = []
        for call in tool_calls:
            tn = call.get("tool_name", "")
            if tn in forbidden_tools:
                continue
            if tn not in [t["name"] for t in tool_metas]:
                continue
            valid_calls.append(call)

        return valid_calls if valid_calls else None

    except Exception as e:
        logger.debug("LLM 工具选择失败，回退到 auto_required: %s", e)
        return None


# ========== 工具执行节点（供 LangGraph 使用） ==========

# JST 工具名列表
_JST_TOOLS = {
    "jst_lookup_order_tool", "jst_lookup_outbound_tool", "jst_lookup_tracking_tool"
}


def tool_executor_node(state: dict) -> dict:
    """LangGraph 节点：执行 tool_plan 中的工具"""
    t0 = time.time()
    tool_plan = state.get("tool_plan", [])

    if not tool_plan:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "tool_results": {},
            "tool_traces": [],
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "tool_executor",
                "status": "skipped",
                "duration_ms": duration_ms,
                "summary": "无工具计划，跳过执行",
            }],
        }

    executor = ToolExecutor()
    exec_result = executor.execute_plan(tool_plan, state, total_timeout_ms=5000)
    _record_tool_metrics(exec_result)

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "tool_executor",
        "status": "success",
        "duration_ms": duration_ms,
        "tools_executed": len(exec_result["tool_results"]),
        "timed_out": exec_result["timed_out"],
        "summary": f"执行 {len(exec_result['tool_results'])} 个工具, 总耗时 {exec_result['total_duration_ms']}ms",
    }

    result = {
        "tool_results": exec_result["tool_results"],
        "tool_traces": exec_result["tool_traces"],
        "trace_steps": state.get("trace_steps", []) + [trace] + exec_result["tool_traces"],
    }

    # 从 JST 工具结果中提取 legacy 字段，供 generate_logistics_reply 等节点使用
    legacy = _extract_legacy_fields(exec_result["tool_results"])
    result.update(legacy)
    result.update(_extract_rag_and_product_fields(exec_result["tool_results"], state))

    return result


def _extract_legacy_fields(tool_results: dict) -> dict:
    """从 tool_results 提取 live_order, logistics_trace, order_status 等字段。

    这些字段是 generate_logistics_reply 等旧节点依赖的，
    Tool Registry 链路需要填充它们以保持兼容。
    """
    from app.agent.nodes.jst_live_query import _build_logistics_trace, _map_status

    fields = {}

    # 遍历 JST 工具，找到第一个有数据的
    for tool_name in _JST_TOOLS:
        tr = tool_results.get(tool_name)
        if not isinstance(tr, dict) or not tr.get("found"):
            continue

        # 构建 live_order（从工具输出重组为 jst_live_query 输出的格式）
        live_order = {
            "o_id": tr.get("o_id", ""),
            "so_id": tr.get("so_id", ""),
            "outer_so_id": tr.get("outer_so_id", ""),
            "status": tr.get("status", ""),
            "logistics_company": tr.get("logistics_company", ""),
            "l_id": tr.get("l_id", ""),
            "send_date": tr.get("send_date", ""),
            "sign_time": tr.get("sign_time", ""),
            "items": tr.get("items", []),
        }

        fields["live_order"] = live_order
        fields["order_found"] = True
        fields["order_source"] = "jst_tool_registry"
        fields["order_status"] = _map_status(tr.get("status", ""))
        logistics_trace = _build_logistics_trace(live_order)
        if tool_name == "jst_lookup_outbound_tool":
            logistics_trace["source"] = "jst_sales_out"
        fields["logistics_trace"] = logistics_trace
        fields["used_fact_tool"] = tool_name
        fields["used_endpoint"] = tr.get("endpoint", "")
        if live_order.get("l_id"):
            fields["tracking_no"] = live_order["l_id"]

        # 只取第一个成功结果
        break

    return fields


def _extract_rag_and_product_fields(tool_results: dict, state: dict) -> dict:
    fields = {}
    resolver = tool_results.get("product_resolver_tool")
    if isinstance(resolver, dict):
        existing_identity = state.get("order_product_identity") or {}
        has_resolved_identity = existing_identity.get("status") == "resolved"
        matched = resolver.get("matched_product_name", "")
        if matched and not has_resolved_identity:
            fields["matched_product_name"] = matched
            fields["product_candidates"] = resolver.get("candidates", [matched])
            fields["need_clarification"] = False
        elif resolver.get("candidates") and not has_resolved_identity:
            fields["product_candidates"] = resolver.get("candidates", [])
            fields["need_clarification"] = bool(resolver.get("need_clarification", False))

    rag = tool_results.get("rag_search_tool")
    if isinstance(rag, dict):
        chunks = rag.get("chunks", []) or []
        try:
            from app.agent.nodes.evidence_filter_node import _has_compare_evidence, _is_compare_query
            from app.services.evidence_fact_gate_service import evaluate_evidence_item
            from app.services.fact_type_service import infer_evidence_fact_type
            query = state.get("normalized_message") or state.get("customer_message", "")
            query_fact_type = state.get("query_fact_type", "")
            if _is_compare_query(query):
                for chunk in chunks:
                    if chunk.get("source_type") != "faq":
                        continue
                    doc = " ".join([
                        chunk.get("title", ""),
                        chunk.get("matched_title", ""),
                        chunk.get("chunk_text", ""),
                        chunk.get("category", ""),
                        chunk.get("category_l3", ""),
                    ])
                    if not _has_compare_evidence(doc):
                        chunk["evidence_allowed_for_exact_answer"] = False
                        chunk["evidence_allowed_for_direct_answer"] = False
                        chunk["mismatch_reason"] = chunk.get("mismatch_reason") or "compare_evidence_mismatch"
            for chunk in chunks:
                chunk["query_fact_type"] = query_fact_type
                chunk["evidence_fact_type"] = chunk.get("evidence_fact_type") or infer_evidence_fact_type(chunk)
                if "evidence_allowed_for_exact_answer" not in chunk:
                    score = chunk.get("rerank_score", chunk.get("score", 0)) or 0
                    chunk["evidence_allowed_for_exact_answer"] = float(score) >= 0.3
                chunk.update(evaluate_evidence_item(chunk, state))
        except Exception:
            pass
        fields["retrieved_chunks"] = chunks
        fields["rag_retrieval_mode"] = rag.get("retrieval_mode", "")
        if chunks:
            # Tool Registry path skips evidence_filter_node, so expose equivalent
            # state fields for debug and used_knowledge_* extraction.
            fields["knowledge_evidence"] = chunks
            fields["filtered_evidence"] = chunks

    return fields


def _metrics_increment(key: str, amount: int = 1) -> None:
    try:
        from app.services.metrics_service import get_metrics_service
        get_metrics_service().increment(key, amount)
    except Exception:
        pass


def _record_tool_metrics(exec_result: dict) -> None:
    traces = exec_result.get("tool_traces", [])
    for trace in traces:
        tool_name = trace.get("tool_name", "")
        if tool_name not in _JST_TOOLS:
            continue
        _metrics_increment("jst_call_count")
        status = trace.get("status", "")
        if status == "success":
            _metrics_increment("jst_success_count")
        else:
            _metrics_increment("jst_failure_count")
        if trace.get("error_code") == "timeout" or trace.get("timed_out"):
            _metrics_increment("jst_timeout_count")
