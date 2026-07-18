import json
import sqlite3

from scripts.run_material_gold_csr_formal_validation import (
    _load_products,
    _redact,
    _response_diagnostics,
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
