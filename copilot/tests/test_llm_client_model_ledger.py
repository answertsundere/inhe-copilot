from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _clear_env(monkeypatch):
    for prefix in ("COPILOT_STRONG_MODEL", "COPILOT_JUDGE_MODEL", "COPILOT_FAST_MODEL"):
        for suffix in ("PROVIDER", "NAME", "API_BASE", "API_KEY"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    for name in ("COPILOT_LLM_MODEL", "COPILOT_LLM_API_BASE", "COPILOT_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _isolated_db(monkeypatch):
    import app.db as db_module
    import app.services.model_call_ledger_service as ledger
    from app.models.model_call_log import ModelCallLog  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(ledger, "_TABLE_READY", False)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory


class _FakeChatCompletions:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def create(self, **kwargs):
        if self.exc:
            raise self.exc
        self.kwargs = kwargs
        return self.response


class _FakeOpenAI:
    next_response = None
    next_exc = None
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(
            completions=_FakeChatCompletions(self.next_response, self.next_exc)
        )
        self.instances.append(self)


def _response_with_usage():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"intent":"x","risk_level":"low","customer_emotion":"ok","need_lookup":[],"suggested_reply":"ok","reply_style":"x","policy_warnings":[],"action_proposal":{},"requires_human_review":false}'))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
    )


def test_successful_chat_completion_records_usage(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    monkeypatch.setenv("COPILOT_JUDGE_MODEL_NAME", "judge-test")
    monkeypatch.setenv("COPILOT_JUDGE_MODEL_API_BASE", "https://judge.example/v1")
    monkeypatch.setenv("COPILOT_JUDGE_MODEL_API_KEY", "judge-key")
    _FakeOpenAI.next_response = _response_with_usage()
    _FakeOpenAI.next_exc = None
    _FakeOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    response = client.chat_completion(
        messages=[{"role": "user", "content": "x"}],
        model_alias="judge_model",
        node_name="test_judge",
    )

    assert response.usage.total_tokens == 18
    assert client.last_model_call_trace["model_alias"] == "judge_model"
    assert client.last_model_call_trace["token_usage"]["total_tokens"] == 18
    db = session_factory()
    try:
        row = db.query(ModelCallLog).one()
        assert row.alias == "judge_model"
        assert row.model == "judge-test"
        assert row.total_tokens == 18
        assert row.status == "success"
        assert "judge-key" not in row.metadata_json
    finally:
        db.close()


def test_final_polish_style_node_name_is_recorded(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    monkeypatch.setenv("COPILOT_STRONG_MODEL_NAME", "strong-test")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_API_BASE", "https://strong.example/v1")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_API_KEY", "strong-key")
    _FakeOpenAI.next_response = _response_with_usage()
    _FakeOpenAI.next_exc = None
    _FakeOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    client.chat_completion(
        messages=[{"role": "user", "content": "polish"}],
        model_alias="strong_model",
        node_name="final_response_orchestrator_polish",
    )

    db = session_factory()
    try:
        row = db.query(ModelCallLog).one()
        assert row.alias == "strong_model"
        assert row.node_name == "final_response_orchestrator_polish"
        assert row.status == "success"
    finally:
        db.close()


def test_failed_chat_completion_records_error(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    monkeypatch.setenv("COPILOT_FAST_MODEL_NAME", "fast-test")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_BASE", "https://fast.example/v1")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_KEY", "fast-key")
    _FakeOpenAI.next_response = None
    _FakeOpenAI.next_exc = RuntimeError("provider down")
    _FakeOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    try:
        client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            model_alias="fast_model",
            node_name="test_fast",
            allow_fallback=False,
        )
        assert False, "expected provider error"
    except RuntimeError:
        pass

    db = session_factory()
    try:
        row = db.query(ModelCallLog).one()
        assert row.alias == "fast_model"
        assert row.status == "error"
        assert row.error_type == "RuntimeError"
        assert row.total_tokens == 0
    finally:
        db.close()


def test_unconfigured_chat_returns_fallback_without_real_request(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    _FakeOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    result = client.chat("system", "user", model_alias="fast_model")

    assert "UNCONFIGURED" in result["error"]
    assert _FakeOpenAI.instances == []
    db = session_factory()
    try:
        assert db.query(ModelCallLog).count() == 0
    finally:
        db.close()
