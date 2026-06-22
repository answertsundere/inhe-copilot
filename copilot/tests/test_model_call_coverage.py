from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _read(path: str) -> str:
    return (APP_ROOT / path).read_text(encoding="utf-8")


def test_direct_chat_calls_are_routed_or_documented():
    direct_calls = []
    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ".client.chat.completions.create" in text:
            direct_calls.append(str(path.relative_to(APP_ROOT)).replace("\\", "/"))

    allowed = {
        # Unified compatibility wrappers for tests/legacy fake clients.
        "services/final_answer_auditor.py",
        "services/final_response_orchestrator.py",
        "services/final_semantic_quality_service.py",
        "services/semantic_fact_type_service.py",
        "api/kb_admin_routes.py",
        # The central LLM client is the only production chat transport.
        "llm/client.py",
    }
    assert set(direct_calls) <= allowed
    assert ".client.chat.completions.create" not in _read("services/final_response_orchestrator.py").split("def _optional_llm_language_polish", 1)[1]


def test_vlm_and_embedding_direct_sdks_have_ledger():
    vlm = _read("services/customer_image_vlm_service.py")
    embedding = _read("services/embedding_service.py")

    assert "OpenAI(" in vlm
    assert "record_model_call" in vlm
    assert "node_name=\"customer_image_vlm\"" in vlm
    assert ".embeddings.create" in embedding
    assert "record_model_call" in embedding
    assert "node_name=\"embedding_service\"" in embedding


def test_no_new_real_model_names_or_keys_in_model_governance_code():
    targets = [
        "services/model_router_service.py",
        "services/model_call_ledger_service.py",
        "llm/client.py",
    ]
    forbidden = ("deepseek-chat", "qwen-plus", "gpt-4o", "sk-")
    for target in targets:
        text = _read(target)
        lowered = text.lower()
        assert not any(item in lowered for item in forbidden)
