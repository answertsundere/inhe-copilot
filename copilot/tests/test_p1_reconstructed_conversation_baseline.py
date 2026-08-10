from __future__ import annotations

import pytest

import scripts.run_p1_gold_conversation_baseline as p1_baseline
from scripts.run_p1_gold_conversation_baseline import (
    P1BaselineIntegrityError,
)


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
