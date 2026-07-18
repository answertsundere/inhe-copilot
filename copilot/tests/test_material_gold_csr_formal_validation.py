import json
import sqlite3

from scripts.run_material_gold_csr_formal_validation import (
    _family_claim_status,
    _load_products,
    _redact,
    _response_contract_error,
    _response_diagnostics,
    _reply_block_summary,
)


def test_formal_runner_loads_only_direct_composition_ready_products(tmp_path):
    database = tmp_path / "knowledge.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE kb_product (i_id TEXT, product_name TEXT, specs_json TEXT, status TEXT)"
    )
    connection.executemany(
        "INSERT INTO kb_product VALUES (?,?,?,?)",
        [
            ("IID-A", "商品A", json.dumps({"material": "PP"}), "published"),
            (
                "IID-B",
                "商品B",
                json.dumps({
                    "material": "ABS",
                    "_auto_backfill": {"batch": {"sources": {"material": "conservative_placeholder"}}},
                }),
                "published",
            ),
            ("IID-C", "商品C", json.dumps({"material": "食品级塑料"}), "published"),
        ],
    )
    connection.commit()
    connection.close()

    products, fingerprint = _load_products(database, limit=5)

    assert products == [{"i_id": "IID-A", "product_name": "商品A", "material": "PP"}]
    assert len(fingerprint) == 64


def test_formal_runner_product_offset_uses_the_same_eligible_product_order(tmp_path):
    database = tmp_path / "knowledge.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE kb_product (i_id TEXT, product_name TEXT, specs_json TEXT, status TEXT)")
    connection.executemany(
        "INSERT INTO kb_product VALUES (?,?,?,?)",
        [
            ("IID-A", "Product A", json.dumps({"material": "PP"}), "published"),
            ("IID-B", "Product B", json.dumps({"material": "PE"}), "published"),
        ],
    )
    connection.commit()
    connection.close()

    products, _ = _load_products(database, limit=1, offset=1)

    assert products == [{"i_id": "IID-B", "product_name": "Product B", "material": "PE"}]


def test_formal_runner_redacts_real_product_identity_from_customer_copy():
    product = {"i_id": "REAL-IID-1", "product_name": "真实商品标题", "material": "PP"}

    text = _redact("真实商品标题 REAL-IID-1 的材质是PP", product, "product_SAFE")

    assert "真实商品标题" not in text
    assert "REAL-IID-1" not in text
    assert "这款商品" in text
    assert "product_SAFE" in text


def test_formal_runner_diagnostics_keep_only_bounded_contract_fields():
    result = _response_diagnostics({
        "answer_mode": "product_fact_answer",
        "generation_mode": "rule_based",
        "query_fact_type": "material",
        "final_answer_audit": {"issues": []},
        "final_semantic_fit": {"issues": []},
        "evidence_debug": {
            "admitted_answer_context": {
                "claim_resolutions": [{
                    "claim_type": "material",
                    "status": "supported",
                    "reason": "admitted_direct_evidence",
                    "evidence_uids": ["private-evidence-id"],
                }]
            }
        },
    })

    assert result["claim_resolutions"] == [{
        "claim_type": "material",
        "status": "supported",
        "reason": "admitted_direct_evidence",
        "evidence_count": 1,
    }]
    assert "private-evidence-id" not in json.dumps(result)


def test_formal_runner_uses_actual_claim_resolution_and_sanitizes_reply_blocks():
    response = {
        "reply_blocks": [{"type": "image", "send_mode": "manual", "content": "private text"}],
        "evidence_debug": {"admitted_answer_context": {"claim_resolutions": [
            {"claim_type": "cleaning_care", "status": "supported"},
            {"claim_type": "moisture_resistance", "status": "unresolved"},
        ]}},
    }

    status, statuses = _family_claim_status(response, "cleaning_or_moisture")

    assert status == "unresolved"
    assert statuses == {"cleaning_care": "supported", "moisture_resistance": "unresolved"}
    assert _reply_block_summary(response) == [{"type": "image", "send_mode": "manual"}]


def test_formal_runner_accepts_legacy_material_claim_as_composition_only():
    status, statuses = _family_claim_status({
        "evidence_debug": {"admitted_answer_context": {"claim_resolutions": [
            {"claim_type": "material", "status": "supported"},
        ]}},
    }, "material_composition")

    assert status == "supported"
    assert statuses["material"] == "supported"
    assert statuses["material_composition"] == "missing"


def test_formal_runner_marks_empty_http_response_as_a_contract_failure():
    assert _response_contract_error({"suggested_reply": ""}) == "response_contract_missing_suggested_reply"
    assert _response_contract_error({"suggested_reply": "draft"}) == ""
