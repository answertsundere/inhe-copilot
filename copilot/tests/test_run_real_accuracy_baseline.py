from __future__ import annotations

import json
import sqlite3

import scripts.run_real_accuracy_baseline as runner
from app.services.real_accuracy_gold_set_service import build_gold_dataset


def _source_db(path):
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE kb_training_sample (
        id INTEGER, customer_quote TEXT, full_context TEXT, product_title TEXT, sku TEXT,
        order_no TEXT, question_type TEXT, correct_answer TEXT, review_status TEXT,
        risk_level TEXT, need_media INTEGER, auto_reply_type TEXT, notes TEXT)""")
    connection.executemany("INSERT INTO kb_training_sample VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (1, "宽度是多少", "买家：宽度是多少", "测试商品", "SKU-1", "ORDER-1", "尺寸", "80cm", "已确认", "low", 0, "需人工确认", ""),
        (2, "怎么安装", "买家：怎么安装", "测试商品", "SKU-2", "ORDER-2", "安装", "", "已确认", "medium", 0, "需人工确认", ""),
    ])
    connection.commit(); connection.close()


def test_baseline_continues_after_timeout_and_keeps_accuracy_null_without_claims(monkeypatch, tmp_path):
    source = tmp_path / "source.db"; _source_db(source)
    samples = runner.load_reviewed_training_samples(source)
    dataset, _ = build_gold_dataset("test-gold-key", samples)
    gold = tmp_path / "gold.json"; gold.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "report.json"
    calls = iter([
        (0, {}, 45.0, "TimeoutError"),
        (200, {"analysis_pipeline": {"version": "v1"}, "requires_human_review": True}, 12.0, ""),
    ])
    monkeypatch.setenv("COPILOT_GOLD_SET_HMAC_KEY", "test-gold-key")
    monkeypatch.setattr(runner, "_post", lambda *_: next(calls))
    assert runner.main(["--gold-set", str(gold), "--source-db", str(source), "--analyze-url", "http://test", "--json-output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["attempted_count"] == 2
    assert report["summary"]["timeout_count"] == 1
    assert report["summary"]["execution_success_count"] == 1
    assert report["summary"]["claim_accuracy_denominator"] == 0
    assert report["summary"]["claim_accuracy_rate"] is None
