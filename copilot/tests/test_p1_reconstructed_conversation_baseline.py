from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.run_p1_gold_conversation_baseline as p1_baseline
from app.services.high_quality_long_conversation_review_service import (
    load_and_validate_review_dataset,
)
from scripts.run_p1_gold_conversation_baseline import (
    P1BaselineIntegrityError,
)
from scripts import compare_model_first_answer_composer as evaluator


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = (
    _PROJECT_ROOT / "tests" / "fixtures" / "p1_conversation_reconstructed"
)
_DATASET_PATH = _FIXTURE_ROOT / "v1.json"
_MANIFEST_PATH = _FIXTURE_ROOT / "v1.manifest.json"


def _create_empty_formal_knowledge_source(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE kb_product (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            i_id TEXT NOT NULL UNIQUE,
            product_name TEXT NOT NULL,
            brand TEXT NOT NULL DEFAULT '',
            category_l1 TEXT NOT NULL DEFAULT '',
            category_l2 TEXT NOT NULL DEFAULT '',
            category_l3 TEXT NOT NULL DEFAULT '',
            sku_list_json TEXT NOT NULL DEFAULT '[]',
            specs_json TEXT NOT NULL DEFAULT '{}',
            logistics_json TEXT NOT NULL DEFAULT '{}',
            warranty_json TEXT NOT NULL DEFAULT '{}',
            domain_policy_id TEXT NOT NULL DEFAULT '',
            completeness_score REAL NOT NULL DEFAULT 0,
            missing_fields_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            updated_at TEXT,
            import_batch_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE kb_qa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT 'general',
            sub_intent TEXT NOT NULL DEFAULT '',
            category_l1 TEXT NOT NULL DEFAULT '',
            category_l2 TEXT NOT NULL DEFAULT '',
            category_l3 TEXT NOT NULL DEFAULT '',
            product_id INTEGER,
            sku_codes_json TEXT NOT NULL DEFAULT '[]',
            risk_level TEXT NOT NULL DEFAULT 'low',
            auto_reply INTEGER NOT NULL DEFAULT 1,
            human_review INTEGER NOT NULL DEFAULT 0,
            keywords_json TEXT NOT NULL DEFAULT '[]',
            source_type TEXT NOT NULL DEFAULT 'faq',
            scenario_category TEXT NOT NULL DEFAULT '',
            issue_type TEXT NOT NULL DEFAULT '',
            sop_id INTEGER,
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            import_batch_id TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT 'general',
            sub_intent TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '',
            category_l3 TEXT NOT NULL DEFAULT '',
            search_keywords TEXT NOT NULL DEFAULT '',
            scene_tag TEXT NOT NULL DEFAULT '',
            product_line TEXT NOT NULL DEFAULT '',
            product_scope_json TEXT NOT NULL DEFAULT '[]',
            sku_scope_json TEXT NOT NULL DEFAULT '[]',
            platform_scope_json TEXT NOT NULL DEFAULT '[]',
            risk_level TEXT NOT NULL DEFAULT 'low',
            auto_reply_allowed INTEGER NOT NULL DEFAULT 1,
            human_review_required INTEGER NOT NULL DEFAULT 0,
            condition_text TEXT NOT NULL DEFAULT '',
            forbidden_usage TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            version INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            source_sheet TEXT NOT NULL DEFAULT '',
            row_number INTEGER NOT NULL DEFAULT 0,
            import_batch_id TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            parent_entry_id INTEGER,
            business_key TEXT,
            product_id TEXT,
            sku_id TEXT,
            fact_type TEXT,
            fact_scope TEXT,
            source_confidence REAL,
            fact_review_status TEXT,
            index_status TEXT NOT NULL DEFAULT 'pending'
        );
        CREATE TABLE knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT 'general',
            product_scope_json TEXT NOT NULL DEFAULT '[]',
            sku_scope_json TEXT NOT NULL DEFAULT '[]',
            platform_scope_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            category TEXT NOT NULL DEFAULT '',
            category_l3 TEXT NOT NULL DEFAULT '',
            search_keywords TEXT NOT NULL DEFAULT '',
            embedding_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT,
            embedding_json TEXT,
            source_confidence REAL,
            fact_review_status TEXT,
            fact_source_type TEXT,
            updated_at TEXT
        );
        """
    )
    connection.commit()
    connection.close()


def _snapshot_rows(path: Path) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(path)
    try:
        return {
            "products": connection.execute(
                "SELECT i_id, product_name, status, domain_policy_id "
                "FROM kb_product ORDER BY i_id"
            ).fetchall(),
            "entries": connection.execute(
                "SELECT business_key, fact_type, fact_scope, content, product_scope_json "
                "FROM knowledge_entries ORDER BY business_key"
            ).fetchall(),
            "chunks": connection.execute(
                "SELECT metadata_json, fact_review_status, fact_source_type "
                "FROM knowledge_chunks ORDER BY id"
            ).fetchall(),
            "qa": connection.execute(
                "SELECT status, auto_reply, source_type FROM kb_qa ORDER BY id"
            ).fetchall(),
        }
    finally:
        connection.close()


def test_reconstructed_contract_is_distinct_from_missing_original_fixed8():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )

    assert contract.dataset_id == "p1-conversation-reconstructed-v1"
    assert contract.case_count == 8
    assert contract.source_class == "conversation_reconstructed"
    assert contract.real_customer_accuracy is None
    assert contract.original_fixed8_restored is False


def test_unknown_dataset_contract_fails_closed():
    with pytest.raises(
        P1BaselineIntegrityError,
        match="dataset_contract_unknown",
    ):
        p1_baseline._resolve_dataset_contract("fixed8")


def test_parser_keeps_legacy_contract_as_default():
    args = p1_baseline.build_parser().parse_args([])

    assert args.dataset_contract == "legacy-real-derived-v4"


def test_parser_accepts_explicit_reconstructed_contract():
    args = p1_baseline.build_parser().parse_args([
        "--dataset-contract",
        "conversation-reconstructed-v1",
    ])

    assert args.dataset_contract == "conversation-reconstructed-v1"


def test_reconstructed_fixture_has_fixed_coverage_and_no_accuracy_claim():
    dataset, validation = load_and_validate_review_dataset(_DATASET_PATH)
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert validation["validation_status"] == "passed"
    assert len(dataset["scenarios"]) == 8
    assert [row["reconstruction_alias"] for row in dataset["scenarios"]] == [
        f"rc-{index:02d}" for index in range(1, 9)
    ]
    assert dataset["source_class"] == "conversation_reconstructed"
    assert manifest["real_customer_accuracy"] is None
    assert manifest["optimization_unverified"] is True
    assert manifest["original_fixed8_restored"] is False
    assert manifest["privacy_declaration"]["scan_passed"] is True

    p1_baseline._validate_reconstructed_dataset_contract(dataset, manifest)


def test_reconstructed_fixture_passes_runner_preflight():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )

    dataset, inventory, manifest = p1_baseline._preflight_dataset(
        _DATASET_PATH,
        _MANIFEST_PATH,
        contract=contract,
    )

    assert dataset["dataset_id"] == contract.dataset_id
    assert inventory["scenario_count"] == contract.case_count
    assert inventory["conversation_history_turn_count"] == 40
    assert manifest["content_sha256"] == contract.dataset_sha256


def test_reconstructed_fixture_is_pinned_to_lf_bytes():
    attributes = (_PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert (
        "tests/fixtures/p1_conversation_reconstructed/*.json text eol=lf"
        in attributes.splitlines()
    )
    assert b"\r\n" not in _DATASET_PATH.read_bytes()
    assert b"\r\n" not in _MANIFEST_PATH.read_bytes()


def test_reconstructed_labels_remain_outside_agent_payload():
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))

    payload = evaluator._agent_payload(dataset["scenarios"][0])
    serialized = json.dumps(payload, ensure_ascii=False)

    for field in (
        "expected_contract",
        "prohibited_outcomes",
        "reconstruction_alias",
        "source_class",
    ):
        assert field not in serialized


@pytest.mark.parametrize(
    "field",
    (
        "expected_contract",
        "prohibited_outcomes",
        "reconstruction_alias",
        "source_class",
    ),
)
def test_reconstructed_evaluation_fields_are_rejected_inside_agent_payload(
    field,
):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    scenario = deepcopy(dataset["scenarios"][0])
    scenario["api_request_template"][field] = "forbidden"

    with pytest.raises(ValueError, match=f"evaluation_field_leakage:{field}"):
        evaluator._agent_payload(scenario)


def test_reconstructed_checkpoint_and_summary_keep_evidence_class_explicit():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )
    checkpoint = p1_baseline._checkpoint_payload(
        contract=contract,
        dataset_hash=contract.dataset_sha256,
        runtime={
            "runtime_commit": "a" * 40,
            "source_tree_sha256": "b" * 64,
        },
        runner_source_sha256="c" * 64,
        formal_knowledge_before={},
        dml_start_offset=0,
        completed_files=[],
    )
    summary = p1_baseline._summary_payload(
        contract=contract,
        observations=[],
        scored_rows=[],
        deterministic_summary={},
        status="incomplete_execution",
        integrity_stop_reason="",
        owner_counts={},
        formal_knowledge={},
    )

    for payload in (checkpoint, summary):
        assert payload["dataset_contract"] == contract.contract_name
        assert payload["source_class"] == "conversation_reconstructed"
        assert payload["real_customer_accuracy"] is None
        assert payload["optimization_unverified"] is True
        assert payload["original_fixed8_restored"] is False
    assert summary["scenario_count"] == 8


@pytest.mark.parametrize(
    ("delivery", "reason"),
    [
        (
            {"can_send": True, "requires_human_review": True},
            "reconstructed_can_send_forbidden",
        ),
        (
            {"can_send": False, "requires_human_review": False},
            "reconstructed_human_review_required",
        ),
    ],
)
def test_reconstructed_delivery_boundary_fails_closed(delivery, reason):
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )

    with pytest.raises(P1BaselineIntegrityError, match=reason):
        p1_baseline._validate_reconstructed_delivery_boundary(
            [{"delivery": delivery}],
            contract=contract,
        )


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda dataset, manifest: dataset.__setitem__(
                "source_class", "real_customer"
            ),
            "reconstructed_source_class_mismatch",
        ),
        (
            lambda dataset, manifest: dataset["scenarios"][1].__setitem__(
                "reconstruction_alias", "rc-01"
            ),
            "reconstructed_alias_sequence_mismatch",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "real_customer_accuracy", 1.0
            ),
            "reconstructed_accuracy_claim_forbidden",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "original_fixed8_restored", True
            ),
            "reconstructed_original_equivalence_forbidden",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "optimization_unverified", False
            ),
            "reconstructed_optimization_claim_forbidden",
        ),
    ],
)
def test_reconstructed_contract_fails_closed_on_identity_or_claim_mutation(
    mutator,
    reason,
):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    mutated_dataset = deepcopy(dataset)
    mutated_manifest = deepcopy(manifest)
    mutator(mutated_dataset, mutated_manifest)

    with pytest.raises(P1BaselineIntegrityError, match=reason):
        p1_baseline._validate_reconstructed_dataset_contract(
            mutated_dataset,
            mutated_manifest,
        )


def test_reconstructed_prepare_projects_only_reviewed_direct_evidence(
    tmp_path,
):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )
    source = tmp_path / "empty-formal.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _create_empty_formal_knowledge_source(source)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    manifest = p1_baseline._prepare_knowledge_snapshot(
        source_path=source,
        snapshot_path=snapshot,
        hmac_key="reconstructed-snapshot-test",
        dataset_sha256=contract.dataset_sha256,
        source_manifest_file_sha256=contract.manifest_file_sha256,
        runner_source_sha256="a" * 64,
        evaluator_source_sha256="b" * 64,
        source_tree_sha256="c" * 64,
        git_head="d" * 40,
        git_dirty=False,
        provider_identity={
            "provider_name": "formal_agent",
            "host_fingerprint": "e" * 12,
            "model_name": "qualified-model",
            "configured": True,
        },
        feature_flags={
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
        },
        dml_start_offset=0,
        contract=contract,
        dataset=dataset,
    )

    rows = _snapshot_rows(snapshot)
    assert len(rows["products"]) == 8
    assert all(row[2] == "published" for row in rows["products"])
    assert all(row[3] == "maternal_child_home" for row in rows["products"])
    assert len(rows["entries"]) == 7
    assert len(rows["chunks"]) == 7
    assert rows["qa"] == [
        ("archived", 0, "evaluation_readiness_sentinel")
    ]
    metadata = [json.loads(row[0]) for row in rows["chunks"]]
    assert {item["evidence_uid"] for item in metadata} == {
        "evidence-00000000000000000002",
        "evidence-00000000000000000003",
        "evidence-00000000000000000004",
        "evidence-00000000000000000005",
        "evidence-00000000000000000006",
        "evidence-00000000000000000009",
        "evidence-0000000000000000000b",
    }
    assert all(
        item["evidence_role"] == "direct_product_fact"
        for item in metadata
    )
    assert all(row[1] == "reviewed" for row in rows["chunks"])
    assert all(row[2] == "direct_product_fact" for row in rows["chunks"])
    seed = manifest["snapshot"]["evaluation_seed"]
    assert seed["product_count"] == 8
    assert seed["direct_evidence_count"] == 7
    assert seed["excluded_candidate_count"] == 4
    assert seed["readiness_sentinel_count"] == 1
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256
    source_rows = _snapshot_rows(source)
    assert all(not rows for rows in source_rows.values())


def test_reconstructed_snapshot_seed_ignores_evaluation_labels(tmp_path):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(dataset)
    for scenario in mutated["scenarios"]:
        scenario["expected_claims"] = [{"tampered": True}]
        scenario["forbidden_claims"] = ["tampered"]
        scenario["expected_contract"] = {"tampered": True}
        scenario["prohibited_outcomes"] = ["tampered"]

    original = p1_baseline._reconstructed_snapshot_seed_projection(dataset)
    changed = p1_baseline._reconstructed_snapshot_seed_projection(mutated)

    assert original == changed


def test_reconstructed_snapshot_requires_dataset_for_seed(tmp_path):
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )
    source = tmp_path / "empty-formal.sqlite"
    _create_empty_formal_knowledge_source(source)

    with pytest.raises(
        P1BaselineIntegrityError,
        match="reconstructed_snapshot_dataset_required",
    ):
        p1_baseline._prepare_knowledge_snapshot(
            source_path=source,
            snapshot_path=tmp_path / "snapshot.sqlite",
            hmac_key="reconstructed-snapshot-test",
            dataset_sha256=contract.dataset_sha256,
            source_manifest_file_sha256=contract.manifest_file_sha256,
            runner_source_sha256="a" * 64,
            evaluator_source_sha256="b" * 64,
            source_tree_sha256="c" * 64,
            git_head="d" * 40,
            git_dirty=False,
            provider_identity={
                "provider_name": "formal_agent",
                "host_fingerprint": "e" * 12,
                "model_name": "qualified-model",
                "configured": True,
            },
            feature_flags={},
            dml_start_offset=0,
            contract=contract,
        )
