import json
import sqlite3

import pytest

from app.services.material_knowledge_governance_service import (
    MaterialKnowledgeAuditError,
    build_material_governance_report,
    classify_material_value,
)
from app.services.material_review_batch_service import (
    MaterialReviewBatchError,
    MaterialReviewStagingStore,
    build_material_review_batches,
)


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE kb_product (
          i_id TEXT, category_l1 TEXT, category_l2 TEXT, category_l3 TEXT,
          specs_json TEXT, status TEXT
        );
        CREATE TABLE knowledge_entries (
          source_type TEXT, status TEXT, fact_type TEXT, fact_review_status TEXT,
          auto_reply_allowed INTEGER, human_review_required INTEGER,
          product_id TEXT, sku_id TEXT, product_scope_json TEXT,
          sku_scope_json TEXT, content TEXT
        );
        CREATE TABLE knowledge_chunks (id INTEGER);
        CREATE TABLE kb_qa (id INTEGER);
        """
    )
    products = (
        ("ITEM-A", "家居", "收纳", "柜", {"material": "PP"}, "published"),
        ("ITEM-B", "母婴", "用品", "餐具", {"material": "食品级HDPE塑料"}, "published"),
        ("ITEM-C", "家居", "家具", "架", {"material": "未在现有结构化资料中明确材质，以人工复核结果为准"}, "published"),
        ("ITEM-D", "家居", "家具", "架", {"material": ""}, "published"),
        (
            "ITEM-E", "家居", "收纳", "架",
            {"material": "ABS", "_auto_backfill": {"batch": {"sources": {"material": "conservative_placeholder"}}}},
            "published",
        ),
    )
    connection.executemany(
        "INSERT INTO kb_product VALUES (?,?,?,?,?,?)",
        [(a, b, c, d, json.dumps(specs, ensure_ascii=False), status) for a, b, c, d, specs, status in products],
    )
    connection.executemany(
        "INSERT INTO knowledge_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("product_facts", "published", "material", "published", 1, 0, "ITEM-A", "", '["ITEM-A"]', "[]", "主体材质为PP。"),
            ("product_facts", "published", "material", "published", 1, 0, "ITEM-E", "", '["ITEM-E"]', "[]", "主体材质为ABS。"),
            ("product_facts", "published", "material", "draft_unverified", 0, 1, "ITEM-C", "", '["ITEM-C"]', "[]", "材质未明确，需要人工确认。"),
            ("dingtalk_product_detail", "published", "material", "published", 1, 0, "", "", "[]", "[]", "主体材质为PE。"),
        ],
    )
    connection.commit()
    connection.close()


def test_material_value_classification_separates_composition_and_strong_claims():
    assert classify_material_value("PP") == "composition_ready"
    assert classify_material_value("食品级HDPE塑料") == "composition_with_strong_claim"
    assert classify_material_value("未在现有结构化资料中明确材质，以人工复核结果为准") == "placeholder_material"
    assert classify_material_value("") == "missing_material"


def test_report_is_query_only_pseudonymous_and_groups_reusable_decisions(tmp_path):
    database = tmp_path / "knowledge.db"
    _database(database)
    before = database.read_bytes()

    report = build_material_governance_report(database, pseudonymization_key="review-secret")

    assert report["summary"]["reviewed_product_count"] == 5
    assert report["summary"]["composition_ready"] == 1
    assert report["summary"]["composition_with_strong_claim"] == 1
    assert report["summary"]["placeholder_material"] == 1
    assert report["summary"]["missing_material"] == 1
    assert report["summary"]["composition_with_untrusted_provenance"] == 1
    assert report["summary"]["direct_scoped_reviewed_entry_count"] == 2
    assert report["summary"]["placeholder_entry_count"] == 1
    assert report["summary"]["unscoped_entry_count"] == 1
    assert report["summary"]["direct_entry_revalidation_count"] == 1
    assert database.read_bytes() == before
    assert report["source"]["source_database_mutated"] is False
    assert report["safety_contract"]["writes_formal_knowledge"] is False
    assert report["safety_contract"]["can_change_can_send"] is False
    raw = json.dumps(report, ensure_ascii=False)
    assert "ITEM-A" not in raw
    assert all(item["product_uid"].startswith("product_") for item in report["product_review_candidates"])
    policies = {item["query_family"]: item for item in report["query_policy_profiles"]}
    assert policies["material_composition"]["composition_may_answer"] is True
    assert policies["material_safety"]["strong_claim_requires_direct_evidence"] is True


def test_missing_pseudonymization_key_fails_closed(tmp_path):
    database = tmp_path / "knowledge.db"
    _database(database)
    with pytest.raises(MaterialKnowledgeAuditError, match="pseudonymization_key_required"):
        build_material_governance_report(database, pseudonymization_key="")


def test_review_batches_are_grouped_and_staging_never_writes_formal_knowledge(tmp_path):
    database = tmp_path / "knowledge.db"
    _database(database)
    report = build_material_governance_report(database, pseudonymization_key="review-secret")
    batches = build_material_review_batches(report)

    assert batches
    assert sum(item["impacted_count"] for item in batches) == report["summary"]["direct_entry_revalidation_count"]
    assert all(item["dry_run"]["formal_kb_writes"] == 0 for item in batches)
    assert all("ITEM-" not in json.dumps(item) for item in batches)

    store = MaterialReviewStagingStore(tmp_path / "staging.db")
    store.seed(batches)
    decided = store.decide(
        batch_uid=batches[0]["batch_uid"],
        action="downgrade_to_human_review",
        reviewer_uid="reviewer-hmac",
        expected_version=1,
    )
    assert decided["formal_kb_writes"] == 0
    with pytest.raises(MaterialReviewBatchError, match="optimistic_lock_conflict"):
        store.decide(
            batch_uid=batches[0]["batch_uid"],
            action="downgrade_to_human_review",
            reviewer_uid="reviewer-hmac",
            expected_version=1,
        )
