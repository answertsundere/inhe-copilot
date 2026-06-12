"""
线程安全的内存指标服务 - 统计请求计数、延迟等运行指标
"""

import threading
import time


class MetricsService:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {
            "request_count": 0,
            "jst_call_count": 0,
            "jst_success_count": 0,
            "jst_failure_count": 0,
            "jst_timeout_count": 0,
            "llm_call_count": 0,
            "llm_success_count": 0,
            "llm_failure_count": 0,
            "llm_unconfigured_count": 0,
            "rag_retrieval_count": 0,
            "rag_no_evidence_count": 0,
            "hallucination_guard_block_count": 0,
            "factual_guard_rewrite_count": 0,
            "human_review_count": 0,
            "fallback_count": 0,
            # Phase 1D: extended metrics
            "accepted_count": 0,
            "edited_count": 0,
            "rejected_count": 0,
            "escalated_count": 0,
            "tool_planner_count": 0,
            "request_tool_planner_count": 0,
            "bad_case_open_count": 0,
            "bad_case_verified_count": 0,
            # Embedding shadow mode
            "embedding_shadow_query_count": 0,
            "embedding_shadow_success_count": 0,
            "embedding_shadow_error_count": 0,
            "embedding_enabled_query_count": 0,
        }
        self._latencies = []
        self._start_time = time.time()

    def increment(self, key, amount=1):
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def record_latency(self, duration_ms):
        with self._lock:
            self._latencies.append(duration_ms)
            if len(self._latencies) > 1000:
                self._latencies = self._latencies[-1000:]

    def get_snapshot(self):
        with self._lock:
            latencies = list(self._latencies)
        avg_lat = sum(latencies) / len(latencies) if latencies else 0
        sorted_lat = sorted(latencies)
        p50 = sorted_lat[len(sorted_lat)//2] if sorted_lat else 0
        p95_idx = int(len(sorted_lat) * 0.95)
        p95 = sorted_lat[min(p95_idx, len(sorted_lat)-1)] if sorted_lat else 0
        return {
            "counters": dict(self._counters),
            "latency": {
                "avg_ms": round(avg_lat, 1),
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "samples": len(latencies),
            },
            "uptime_seconds": round(time.time() - self._start_time, 1),
        }


_metrics_service = None


def get_metrics_service():
    global _metrics_service
    if _metrics_service is None:
        _metrics_service = MetricsService()
    return _metrics_service
