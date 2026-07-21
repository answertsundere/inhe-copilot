from __future__ import annotations

import hashlib
import json

import pytest

import scripts.build_authoritative_output_manifest as manifest_script
from app.services.real_accuracy_gold_set_service import build_gold_dataset


def _gold(tmp_path):
    dataset, _ = build_gold_dataset("manifest-key", [{
        "id": 1,
        "customer_quote": "请核对当前问题",
        "full_context": '<div class="imui-msg imui-msg-l"><div class="msg-body-text">请核对当前问题</div></div>',
        "product_title": "测试商品",
        "sku": "TEST-SKU",
        "order_no": "TEST-ORDER",
        "question_type": "尺寸",
        "correct_answer": "",
        "review_status": "已确认",
        "risk_level": "medium",
        "need_media": False,
        "auto_reply_type": "",
        "notes": "",
    }])
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    return path, dataset


def _report(path, status="passed"):
    path.write_text(json.dumps({"status": status}, ensure_ascii=False), encoding="utf-8")
    return path


def test_manifest_uses_explicit_report_roles_and_verifies_hashes(monkeypatch, tmp_path):
    gold, dataset = _gold(tmp_path)
    final = _report(tmp_path / "final.json")
    attempt = _report(tmp_path / "attempt.json", "failed")
    superseded = tmp_path / "legacy.json"
    superseded.write_text("not-json", encoding="utf-8")
    output = tmp_path / "manifest.json"
    monkeypatch.setattr(manifest_script, "_git_commit", lambda: "a" * 40)
    monkeypatch.setattr(manifest_script, "_source_tree_sha256", lambda: "b" * 64)

    assert manifest_script.main([
        "--phase", "Phase 0.8D", "--dataset", str(gold),
        "--authoritative-report", str(final), "--attempt-report", str(attempt),
        "--superseded-report", f"{superseded}::legacy_invalid",
        "--feature-flag", "formal_evidence_convergence=false",
        "--acceptance-status", "awaiting_supervisor_approval",
        "--json-output", str(output),
    ]) == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["dataset"]["content_sha256"] == dataset["manifest"]["content_sha256"]
    assert manifest["authoritative_reports"][0]["json_valid"] is True
    assert manifest["attempt_reports"][0]["json_valid"] is True
    assert manifest["superseded_reports"][0]["json_valid"] is False
    assert manifest["superseded_reports"][0]["reason"] == "legacy_invalid"
    assert manifest["feature_flags"] == {"formal_evidence_convergence": False}
    assert manifest["report_sha256"] == hashlib.sha256(
        json.dumps({
            "authoritative_reports": manifest["authoritative_reports"],
            "attempt_reports": manifest["attempt_reports"],
            "superseded_reports": manifest["superseded_reports"],
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_manifest_rejects_invalid_authoritative_report(tmp_path):
    gold, _ = _gold(tmp_path)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")

    assert manifest_script.main([
        "--phase", "Phase 0.8D", "--dataset", str(gold),
        "--authoritative-report", str(invalid),
        "--acceptance-status", "blocked",
        "--json-output", str(tmp_path / "manifest.json"),
    ]) == 2
