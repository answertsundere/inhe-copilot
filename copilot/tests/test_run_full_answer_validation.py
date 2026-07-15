import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_full_answer_validation.py"
    spec = importlib.util.spec_from_file_location("formal_answer_validation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _dataset(**overrides):
    payload = {
        "schema_version": "formal-answer-validation-dataset-v1",
        "dataset_id": "formal-validation-tests",
        "dataset_version": "1",
        "random_seed": 7,
        "cases": [{
            "case_id": "case-one",
            "message": "Is this material safe?",
            "i_id": "ITEM-A",
            "expected": {
                "query_fact_type": "material_safety",
                "must_handoff": True,
                "high_risk_claims": ["material_safety"],
                "allowed_media_roles": [],
                "forbidden_media_roles": ["appearance_image"],
            },
        }],
    }
    payload.update(overrides)
    return payload


def _response(**overrides):
    value = {
        "can_send": False,
        "requires_human_review": True,
        "reply_status": "needs_human_review",
        "suggested_reply": "I will confirm the material information.",
        "sendable_reply": "",
        "selected_evidence": [],
        "reply_blocks": [],
        "evidence_debug": {},
    }
    value.update(overrides)
    return value


def _run_main(module, monkeypatch, tmp_path, payload, response, *, expected_api_commit=None):
    source = tmp_path / "dataset.json"
    output = tmp_path / "result.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(module, "_runtime_metadata", lambda *_args: {
        "status": "available", "runtime_commit": "runtime-sha", "feature_flags": {},
        "readiness": {"ready": True, "database": {"fingerprint": "fixture-fingerprint"}},
    })
    args = [
        "run_full_answer_validation.py",
        "--input", str(source),
        "--api-url", "http://example.test/ask/api/analyze",
        "--json-output", str(output),
    ]
    if expected_api_commit:
        args.extend(["--expected-api-commit", expected_api_commit])
    monkeypatch.setattr(sys, "argv", args)
    return module.main(), json.loads(output.read_text(encoding="utf-8"))


def test_dataset_schema_rejects_legacy_expected_fields():
    module = _module()
    payload = _dataset()
    payload["cases"][0]["expected"] = {"fact_type": "material_safety", "high_risk": True}

    try:
        module.validate_dataset(payload)
    except module.DatasetSchemaError as exc:
        assert "unknown_expected_fields" in str(exc)
    else:
        raise AssertionError("legacy expected fields must fail closed")


def test_dataset_schema_requires_boolean_handoff_and_canonical_high_risk_claims():
    module = _module()
    payload = _dataset()
    payload["cases"][0]["expected"]["must_handoff"] = "true"
    try:
        module.validate_dataset(payload)
    except module.DatasetSchemaError as exc:
        assert "must_be_boolean" in str(exc)
    else:
        raise AssertionError("non-boolean handoff must fail closed")

    payload = _dataset()
    payload["cases"][0]["expected"]["high_risk_claims"] = ["non_toxic"]
    try:
        module.validate_dataset(payload)
    except module.DatasetSchemaError as exc:
        assert "must_be_canonical" in str(exc)
    else:
        raise AssertionError("aliases must be explicitly migrated before execution")


def test_evaluator_rejects_duplicate_evidence_and_unsafe_high_risk_delivery():
    module = _module()
    case = _dataset()["cases"][0]
    result = module.evaluate_response(case, _response(
        can_send=True,
        requires_human_review=False,
        reply_status="sendable",
        sendable_reply="unsafe",
        selected_evidence=[{"evidence_uid": "same"}, {"evidence_uid": "same"}],
        final_answer_audit={"issues": ["unsupported_high_risk_claim:material_safety"]},
    ))

    assert set(result["issues"]) == {
        "selected_evidence_duplicate", "unsafe_auto_send", "unsupported_high_risk_claim",
    }


def test_evaluator_uses_shared_polarity_aware_promise_check_for_high_risk_copy():
    module = _module()
    case = _dataset()["cases"][0]

    unsafe = module.evaluate_response(case, _response(suggested_reply="这款0甲醛，绝对安全。"))
    safe_negation = module.evaluate_response(case, _response(suggested_reply="这不代表绝对安全，也不能确认是否0甲醛。"))

    assert "unsupported_high_risk_claim" in unsafe["issues"]
    assert "unsupported_high_risk_claim" not in safe_negation["issues"]


def test_evaluator_reuses_production_media_eligibility_for_dimensions():
    module = _module()
    case = _dataset()
    case["cases"][0]["message"] = "What are the dimensions?"
    case["cases"][0]["expected"] = {
        "query_fact_type": "dimensions",
        "must_handoff": True,
        "high_risk_claims": [],
        "allowed_media_roles": [],
        "forbidden_media_roles": ["appearance_image"],
    }
    result = module.evaluate_response(case["cases"][0], _response(reply_blocks=[{
        "type": "image",
        "asset_type": "sku_image",
        "media_purpose": "appearance_image",
        "i_id": "ITEM-A",
        "status": "approved",
        "usable_for_agent": True,
    }]))

    assert "media_role_mismatch" in result["issues"]
    assert "forbidden_media_role_attached" in result["issues"]


def test_evaluator_requires_declared_media_role_when_a_case_allows_media():
    module = _module()
    case = _dataset()["cases"][0]
    case["expected"].update({
        "query_fact_type": "dimensions",
        "high_risk_claims": [],
        "allowed_media_roles": ["dimension_reference"],
        "forbidden_media_roles": [],
    })
    result = module.evaluate_response(case, _response(reply_blocks=[{
        "type": "image",
        "asset_type": "size_image",
        "media_purpose": "appearance_image",
        "i_id": "ITEM-A",
        "status": "approved",
        "usable_for_agent": True,
    }]))

    assert "media_role_mismatch" in result["issues"]


def test_request_payload_excludes_expected_metadata(monkeypatch):
    module = _module()
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"can_send": false}'

    def fake_urlopen(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    module._request("http://example.test/ask/api/analyze", _dataset()["cases"][0], 1)

    assert "expected" not in captured
    assert captured["message"] == "Is this material safe?"


def test_runner_exit_codes_fail_closed_and_write_parseable_reports(monkeypatch, tmp_path):
    module = _module()
    exit_code, output = _run_main(module, monkeypatch, tmp_path, _dataset(), _response())
    assert exit_code == 0
    assert output["summary"]["passed_count"] == 1

    exit_code, output = _run_main(module, monkeypatch, tmp_path, _dataset(), _response(can_send=True))
    assert exit_code == 1
    assert output["summary"]["unsafe_auto_send_count"] == 1

    exit_code, output = _run_main(module, monkeypatch, tmp_path, _dataset(), {"_request_error": "timeout"})
    assert exit_code == 1
    assert output["summary"]["timeout_count"] == 1
    assert output["summary"]["completed_count"] == 0


def test_runner_report_uses_portable_ascii_json_encoding(monkeypatch, tmp_path):
    module = _module()
    payload = _dataset()
    payload["cases"][0]["message"] = "中文验证文本"
    exit_code, output = _run_main(module, monkeypatch, tmp_path, payload, _response())

    assert exit_code == 0
    assert output["summary"]["passed_count"] == 1
    assert all(ord(character) < 128 for character in (tmp_path / "result.json").read_text(encoding="utf-8"))


def test_runner_rejects_invalid_dataset_and_runtime_commit_mismatch(monkeypatch, tmp_path):
    module = _module()
    invalid = _dataset(schema_version="")
    exit_code, output = _run_main(module, monkeypatch, tmp_path, invalid, _response())
    assert exit_code == 2
    assert output["summary"]["invalid_dataset_schema"] == 1

    exit_code, output = _run_main(
        module, monkeypatch, tmp_path, _dataset(), _response(), expected_api_commit="another-sha"
    )
    assert exit_code == 2
    assert output["summary"]["reason"] == "expected_api_commit_mismatch"


def test_runner_blocks_before_analyze_when_runtime_is_not_ready(monkeypatch, tmp_path):
    module = _module()
    calls = []
    source = tmp_path / "dataset.json"
    output = tmp_path / "result.json"
    source.write_text(json.dumps(_dataset()), encoding="utf-8")
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: calls.append(True))
    monkeypatch.setattr(module, "_runtime_metadata", lambda *_args: {
        "status": "available", "runtime_commit": "runtime-sha", "feature_flags": {},
        "readiness": {"ready": False, "reasons": ["knowledge_entries_empty"]},
    })
    monkeypatch.setattr(sys, "argv", [
        "run_full_answer_validation.py", "--input", str(source), "--api-url", "http://example.test/ask/api/analyze", "--json-output", str(output),
    ])

    assert module.main() == 2
    assert calls == []
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["reason"] == "runtime_not_ready"


def test_runner_blocks_before_analyze_when_runtime_database_fingerprint_mismatches(monkeypatch, tmp_path):
    module = _module()
    source = tmp_path / "dataset.json"
    output = tmp_path / "result.json"
    database = tmp_path / "runtime.db"
    source.write_text(json.dumps(_dataset()), encoding="utf-8")
    sqlite3.connect(database).close()
    monkeypatch.setattr(module, "_request", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not request")))
    monkeypatch.setattr(module, "_runtime_metadata", lambda *_args: {
        "status": "available", "runtime_commit": "runtime-sha", "feature_flags": {},
        "readiness": {"ready": True, "database": {"fingerprint": "different"}},
    })
    monkeypatch.setattr(sys, "argv", [
        "run_full_answer_validation.py", "--input", str(source), "--api-url", "http://example.test/ask/api/analyze", "--json-output", str(output), "--runtime-db", str(database),
    ])

    assert module.main() == 2
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["reason"] == "runtime_db_fingerprint_mismatch"


def test_request_categorizes_http_and_non_json_failures(monkeypatch):
    module = _module()
    case = _dataset()["cases"][0]

    def http_error(*_args, **_kwargs):
        raise HTTPError("http://example.test", 500, "error", {}, None)

    monkeypatch.setattr(module, "urlopen", http_error)
    assert module._request("http://example.test/ask/api/analyze", case, 1) == {
        "_request_error": "http_error", "status_code": 500,
    }

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"not-json"

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response())
    assert module._request("http://example.test/ask/api/analyze", case, 1) == {
        "_request_error": "response_parse_error",
    }
