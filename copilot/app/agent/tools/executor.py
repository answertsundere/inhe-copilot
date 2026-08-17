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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Optional

from app.agent.tools.base import ToolSpec
from app.agent.tools.registry import get_tool_registry

logger = logging.getLogger(__name__)

_EXTERNAL_TOOL_NAMES = {
    "jst_lookup_order_tool",
    "jst_lookup_outbound_tool",
    "jst_lookup_tracking_tool",
}


def get_replay_tool_control(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {
            "disable_external_tools": False,
            "external_tool_timeout_seconds": 0.0,
        }
    copilot_context = state.get("copilot_context") if isinstance(state.get("copilot_context"), dict) else {}
    options = copilot_context.get("eval_replay_options") if isinstance(copilot_context.get("eval_replay_options"), dict) else {}
    if not options and isinstance(state.get("eval_replay_options"), dict):
        options = state.get("eval_replay_options") or {}
    try:
        timeout_seconds = float(options.get("external_tool_timeout_seconds") or 0)
    except (TypeError, ValueError):
        timeout_seconds = 0.0
    return {
        "disable_external_tools": bool(options.get("disable_external_tools")),
        "external_tool_timeout_seconds": max(timeout_seconds, 0.0),
    }


def _is_external_tool(tool_name: str) -> bool:
    return str(tool_name or "") in _EXTERNAL_TOOL_NAMES


def _looks_like_sku(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"[A-Z]{2}\d{2}K\d{2}", value, re.IGNORECASE) or re.search(r"[A-Z0-9]+B\d+S\d+", value, re.IGNORECASE))


def _merge_ranked_results(primary: list[dict], supplemental: list[dict], limit: int = 8) -> list[dict]:
    merged: list[dict] = []
    seen = set()
    for item in [*(primary or []), *(supplemental or [])]:
        if not isinstance(item, dict):
            continue
        key = item.get("chunk_id") or item.get("entry_id") or item.get("title")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(item)
    merged.sort(key=lambda r: float(r.get("rerank_score", r.get("score", 0)) or 0), reverse=True)
    return merged[:limit]


def _prefer_matching_fact_type(results: list[dict], query_fact_type: str) -> list[dict]:
    if not query_fact_type or not results:
        return results
    try:
        from app.services.fact_type_service import fact_type_matches
    except Exception:
        return results
    matched = [
        item for item in results
        if fact_type_matches(query_fact_type, str(item.get("fact_type") or item.get("evidence_fact_type") or ""))
    ]
    return matched if matched else results


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
        requires_human_review = False
        control = get_replay_tool_control(state)
        replay_timeout_ms = int(control["external_tool_timeout_seconds"] * 1000) if control["external_tool_timeout_seconds"] else 0
        disabled_tools: list[str] = []
        timed_out_tools: list[str] = []

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

            if control["disable_external_tools"] and _is_external_tool(tool_name):
                result, trace = self._disabled_external_tool_result(tool_name, inputs)
                tool_results[tool_name] = result
                tool_traces.append(trace)
                disabled_tools.append(tool_name)
                requires_human_review = True
                continue

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
            if replay_timeout_ms > 0:
                tool_timeout = min(tool_timeout, replay_timeout_ms)

            result, trace = self._execute_single(
                spec,
                inputs,
                state,
                tool_timeout,
                hard_timeout=replay_timeout_ms > 0,
            )
            tool_results[tool_name] = result
            tool_traces.append(trace)
            if trace.get("timed_out") or trace.get("error_code") == "timeout":
                timed_out = True
                timed_out_tools.append(tool_name)
                requires_human_review = True

        total_duration_ms = int((time.time() - t0) * 1000)
        return {
            "tool_results": tool_results,
            "tool_traces": tool_traces,
            "total_duration_ms": total_duration_ms,
            "timed_out": timed_out,
            "requires_human_review": requires_human_review,
            "external_tool_control": {
                **control,
                "disabled_tools": disabled_tools,
                "timed_out_tools": timed_out_tools,
            },
        }

    def _disabled_external_tool_result(self, tool_name: str, inputs: dict) -> tuple[dict, dict]:
        result = {
            "found": False,
            "safe_fallback_reason": "external_tools_disabled_for_replay",
            "requires_human_review": True,
        }
        trace = {
            "node": "tool_executor",
            "tool_name": tool_name,
            "status": "skipped",
            "duration_ms": 0,
            "provider": "tool_registry",
            "input_summary": _summarize_inputs(inputs),
            "error_code": "external_tools_disabled_for_replay",
            "requires_human_review": True,
            "summary": f"{tool_name}: skipped by eval replay external tool control",
        }
        return result, trace

    def _execute_single(
        self,
        spec: ToolSpec,
        inputs: dict,
        state: dict,
        timeout_ms: int,
        hard_timeout: bool = False,
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
            if hard_timeout:
                executor = ThreadPoolExecutor(max_workers=1)
                future = executor.submit(spec.handler, inputs, state)
                try:
                    result = future.result(timeout=max(float(timeout_ms) / 1000, 0.001))
                except FutureTimeoutError:
                    future.cancel()
                    duration_ms = int((time.time() - t0) * 1000)
                    return {
                        "found": False,
                        "error": f"{spec.name} timed out",
                        "safe_fallback_reason": "tool_timeout",
                        "requires_human_review": True,
                    }, {
                        "node": "tool_executor",
                        "tool_name": spec.name,
                        "status": "timeout",
                        "duration_ms": duration_ms,
                        "provider": "tool_registry",
                        "input_summary": _summarize_inputs(inputs),
                        "error_code": "timeout",
                        "timed_out": True,
                        "requires_human_review": True,
                        "summary": f"{spec.name}: timeout ({duration_ms}ms > {timeout_ms}ms)",
                    }
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            else:
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

    try:
        from app.services.logistics_fast_path import get_explicit_logistics_identifier
        explicit_identifier = get_explicit_logistics_identifier(state)
    except Exception:
        explicit_identifier = None

    if explicit_identifier and required_tools:
        plan = [
            {"tool_name": rt, "inputs": default_inputs.get(rt, {})}
            for rt in required_tools if rt in allowed_tools
        ]
        source = "explicit_logistics_identifier_fast_path"
    else:
        plan = None

    # 尝试用 LLM 选择工具
    llm_plan = None if plan is not None else _try_llm_tool_selection(state, allowed_tools, forbidden_tools, registry)

    if plan is not None:
        pass
    elif llm_plan is not None:
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
    try:
        from app.services.logistics_fast_path import get_explicit_logistics_identifier
        explicit_identifier = get_explicit_logistics_identifier(state) or {}
    except Exception:
        explicit_identifier = {}
    explicit_type = explicit_identifier.get("identifier_type", "")
    explicit_value = explicit_identifier.get("identifier_value", "")
    order_identifier = slots.get("order_id") or state.get("order_id") or ""
    order_identifier_type = slots.get("identifier_type") or "internal_order_id"
    if explicit_value and explicit_type in ("internal_order_id", "order_id", "platform_order_id"):
        order_identifier = explicit_value
        order_identifier_type = explicit_type
    elif not order_identifier and slots.get("possible_numeric_id"):
        order_identifier = slots.get("possible_numeric_id")
        order_identifier_type = "internal_order_id"
    platform_trade_id = slots.get("platform_trade_id") or state.get("platform_trade_id") or ""
    if explicit_value and explicit_type == "platform_trade_id":
        platform_trade_id = explicit_value
    tracking_no = slots.get("tracking_no") or state.get("tracking_no") or ""
    if explicit_value and explicit_type == "tracking_no":
        tracking_no = explicit_value

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
            "identifier": order_identifier,
            "identifier_type": order_identifier_type,
        },
        "jst_lookup_outbound_tool": {
            "outer_so_id": platform_trade_id,
        },
        "jst_lookup_tracking_tool": {
            "tracking_no": tracking_no,
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

        response = llm_client.create_chat_completion(
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


def _normalize_order_status(status: str) -> str:
    status = str(status or "").strip()
    mapping = {
        "已发货": "shipped",
        "发货中": "shipped",
        "待发货": "pending_shipment",
        "待出库": "pending_shipment",
        "备货中": "pending_shipment",
        "已签收": "signed",
        "已完成": "finished",
        "已取消": "canceled",
    }
    return mapping.get(status, status)


def _lookup_local_order_from_state(state: dict | None) -> dict:
    if not state:
        return {}
    slots = state.get("slots") or {}
    order_id = (
        state.get("order_id")
        or slots.get("order_id")
        or slots.get("possible_numeric_id")
        or ""
    )
    tracking_no = state.get("tracking_no") or slots.get("tracking_no") or ""
    if not order_id and not tracking_no:
        return {}
    try:
        from app.repositories.json_order_repository import JsonOrderRepository
        repo = JsonOrderRepository()
        repo.load()
        if order_id:
            order = repo.get_order(order_id)
            if order:
                return order
        if tracking_no:
            order = repo.get_order_by_tracking_no(tracking_no)
            if order:
                return order
    except Exception:
        return {}
    return {}


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
        "external_tool_control": exec_result.get("external_tool_control", {}),
    }
    if exec_result.get("requires_human_review"):
        result["requires_human_review"] = True
        result["reason_for_review"] = "external_tool_unavailable_for_replay"

    # 从 JST 工具结果中提取 legacy 字段，供 generate_logistics_reply 等节点使用
    legacy = _extract_legacy_fields(exec_result["tool_results"], state)
    result.update(legacy)
    result.update(
        _extract_rag_and_product_fields(
            exec_result["tool_results"],
            {**state, **legacy},
        )
    )

    return result


def _extract_legacy_fields(tool_results: dict, state: dict | None = None) -> dict:
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
        fields["order"] = live_order
        fields["order_found"] = True
        fields["order_source"] = "jst_tool_registry"
        fields["order_status"] = _normalize_order_status(_map_status(tr.get("status", "")))
        fields["shipment_status"] = "shipped" if live_order.get("l_id") else "pending"
        logistics_trace = _build_logistics_trace(live_order)
        if tool_name == "jst_lookup_outbound_tool":
            logistics_trace["source"] = "jst_sales_out"
        fields["logistics_trace"] = logistics_trace
        fields["used_fact_tool"] = tool_name
        fields["used_endpoint"] = tr.get("endpoint", "")
        if live_order.get("l_id"):
            fields["tracking_no"] = live_order["l_id"]

        current_state = state or {}
        existing_identity = current_state.get("order_product_identity") or {}
        if existing_identity.get("status") != "resolved":
            slots = current_state.get("slots") or {}
            identifier_type = str(slots.get("identifier_type") or "").strip()
            identifier = str(
                slots.get(identifier_type)
                or slots.get("platform_trade_id")
                or slots.get("order_id")
                or slots.get("tracking_no")
                or ""
            ).strip()
            from app.agent.nodes.order_product_resolver import (
                build_order_product_identity_from_order_data,
            )

            identity = build_order_product_identity_from_order_data(
                live_order,
                current_state,
                identifier=identifier,
                identifier_type=identifier_type,
            )
            fields["order_product_identity"] = identity
            fields["product_candidates"] = identity.get("candidates", [])
            if identity.get("status") == "resolved":
                fields["matched_product_name"] = identity.get("matched_product_name", "")
                fields["need_clarification"] = False
            elif identity.get("status") == "ambiguous":
                fields["need_clarification"] = True

        # 只取第一个成功结果
        break

    if not fields and state:
        local_order = state.get("order") or state.get("live_order") or _lookup_local_order_from_state(state)
        if isinstance(local_order, dict) and local_order:
            live_order = {
                "o_id": local_order.get("o_id", ""),
                "so_id": local_order.get("so_id", ""),
                "outer_so_id": local_order.get("outer_so_id", ""),
                "status": local_order.get("status", ""),
                "logistics_company": local_order.get("logistics_company", ""),
                "l_id": local_order.get("l_id", ""),
                "send_date": local_order.get("send_date", ""),
                "sign_time": local_order.get("sign_time", ""),
                "items": local_order.get("items", []),
            }
            fields["live_order"] = live_order
            fields["order"] = live_order
            fields["order_found"] = True
            fields["order_source"] = "local_order_fallback"
            mapped_status = _normalize_order_status(_map_status(live_order.get("status", "")))
            fields["order_status"] = mapped_status
            fields["shipment_status"] = "shipped" if live_order.get("l_id") else "pending"
            fields["logistics_trace"] = _build_logistics_trace(live_order)
            fields["local_order_fallback_used"] = True

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
    if isinstance(rag, dict) and not (rag.get("chunks") or []):
        retry_rag = _retry_rag_after_product_resolver(state, resolver)
        if retry_rag.get("chunks"):
            rag = retry_rag
    if isinstance(rag, dict):
        chunks = rag.get("chunks", []) or []
        product_context_pack = {"facts": [], "stats": {}}
        try:
            from app.services.product_context_pack_service import build_product_context_pack
            pack_state = {**state, **fields}
            query = pack_state.get("normalized_message") or pack_state.get("customer_message", "")
            product_context_pack = build_product_context_pack(
                pack_state,
                query=query,
                allowed_source_types=pack_state.get("allowed_source_types", []),
                query_fact_type=pack_state.get("query_fact_type", ""),
                top_k=8,
            )
            chunks = _merge_ranked_results(chunks, product_context_pack.get("facts", []), limit=8)
            chunks = _prefer_matching_fact_type(chunks, pack_state.get("query_fact_type", ""))
        except Exception as exc:
            logger.warning("Product context pack failed in tool executor: %s", exc)
        try:
            from app.agent.nodes.evidence_filter_node import _has_compare_evidence, _is_compare_query
            from app.services.evidence_fact_gate_service import evaluate_evidence_item, sanitize_risky_convenience_claim
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
                if query_fact_type == "installation" and chunk["evidence_fact_type"] == "installation":
                    new_text, sanitized = sanitize_risky_convenience_claim(chunk.get("chunk_text", ""))
                    if sanitized:
                        chunk["chunk_text"] = new_text
                        chunk["sanitized_risky_convenience_claim"] = True
                if "evidence_allowed_for_exact_answer" not in chunk:
                    score = chunk.get("rerank_score", chunk.get("score", 0)) or 0
                    chunk["evidence_allowed_for_exact_answer"] = float(score) >= 0.3
                chunk.update(evaluate_evidence_item(chunk, state))
        except Exception:
            pass
        fields["retrieved_chunks"] = chunks
        fields["rag_retrieval_mode"] = rag.get("retrieval_mode", "")
        fields["product_context_pack"] = product_context_pack
        fields["product_context_pack_stats"] = product_context_pack.get("stats", {})
        if chunks:
            # Tool Registry path skips evidence_filter_node, so expose equivalent
            # state fields for debug and used_knowledge_* extraction.
            fields["knowledge_evidence"] = chunks
            fields["filtered_evidence"] = chunks

    return fields


def _retry_rag_after_product_resolver(state: dict, resolver: dict | None) -> dict:
    if not isinstance(resolver, dict):
        return {}
    matched = str(resolver.get("matched_product_name") or "").strip()
    if not matched:
        return {}

    source_types = state.get("allowed_source_types", []) or []
    if not source_types:
        return {}

    product_scope = []
    for value in [matched, *(resolver.get("candidates") or [])]:
        if isinstance(value, dict):
            values = [
                str(value.get(k) or "").strip()
                for k in ("matched_product_name", "value", "name", "product_name", "title", "i_id")
            ]
        else:
            values = [str(value or "").strip()]
        for item in values:
            if item and item not in product_scope:
                product_scope.append(item)

    sku_scope = []
    for value in (
        resolver.get("sku_id", ""),
        resolver.get("i_id", ""),
        (state.get("slots") or {}).get("sku_code", ""),
    ):
        value = str(value or "").strip()
        if value and value not in sku_scope:
            sku_scope.append(value)
    for candidate in resolver.get("candidates") or []:
        if isinstance(candidate, dict):
            values = [
                str(candidate.get(k) or "").strip()
                for k in ("sku_code", "sku_id", "i_id")
            ]
        else:
            values = [str(candidate or "").strip()]
        for value in values:
            if value and value.upper().startswith("YH") and value not in sku_scope:
                sku_scope.append(value)

    try:
        from app.retrieval.retriever_factory import get_retriever

        query = state.get("normalized_message") or state.get("customer_message", "")
        retriever = get_retriever()
        chunks = retriever.retrieve(
            query=" ".join([query, matched, *sku_scope])[:500],
            source_types=source_types,
            product_scope=product_scope if product_scope else None,
            sku_scope=sku_scope if sku_scope else None,
            fact_type=state.get("query_fact_type", ""),
            top_k=5,
            min_score=0.1,
            sku_name=sku_scope[0] if sku_scope else "",
            product_name=matched,
        )
    except Exception:
        chunks = []

    return {
        "chunks": chunks,
        "count": len(chunks),
        "retrieval_mode": "retriever_hybrid_after_product_resolver",
        "debug": {
            "query": state.get("normalized_message") or state.get("customer_message", ""),
            "source_types": source_types,
            "product_scope": product_scope,
            "sku_scope": sku_scope,
            "product_name": matched,
            "sku_name": sku_scope[0] if sku_scope else "",
            "fact_type": state.get("query_fact_type", ""),
        },
    }


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
