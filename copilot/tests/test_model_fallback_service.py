import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _clear_env(monkeypatch):
    for prefix in ("COPILOT_FAST_MODEL", "COPILOT_STRONG_MODEL", "COPILOT_JUDGE_MODEL"):
        for suffix in ("PROVIDER", "NAME", "API_BASE", "API_KEY", "TIMEOUT_SECONDS", "MAX_RETRIES"):
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


def _response(tokens=9):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=6, total_tokens=tokens),
    )


class _QueueCompletions:
    def __init__(self, outcome):
        self.outcome = outcome

    def create(self, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _QueueOpenAI:
    outcomes = []
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        outcome = self.outcomes.pop(0)
        self.chat = SimpleNamespace(completions=_QueueCompletions(outcome))
        self.instances.append(self)


def _configure_fast_and_strong(monkeypatch):
    monkeypatch.setenv("COPILOT_FAST_MODEL_PROVIDER", "test_provider")
    monkeypatch.setenv("COPILOT_FAST_MODEL_NAME", "fast-test")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_BASE", "https://fast.example/v1")
    monkeypatch.setenv("COPILOT_FAST_MODEL_API_KEY", "fast-key")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_PROVIDER", "test_provider")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_NAME", "strong-test")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_API_BASE", "https://strong.example/v1")
    monkeypatch.setenv("COPILOT_STRONG_MODEL_API_KEY", "strong-key")


def test_primary_failure_fallback_success_records_each_attempt(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    _configure_fast_and_strong(monkeypatch)
    _QueueOpenAI.outcomes = [RuntimeError("fast down"), _response()]
    _QueueOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _QueueOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    result = client.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model_alias="fast_model",
        node_name="fallback_test",
    )

    assert result.usage.total_tokens == 9
    trace = client.last_model_call_trace
    assert trace["primary_alias"] == "fast_model"
    assert trace["final_alias"] == "strong_model"
    assert trace["fallback_used"] is True
    assert [attempt["model_alias"] for attempt in trace["attempts"]] == ["fast_model", "strong_model"]
    assert [attempt["status"] for attempt in trace["attempts"]] == ["error", "success"]

    db = session_factory()
    try:
        rows = db.query(ModelCallLog).order_by(ModelCallLog.id.asc()).all()
        assert [row.alias for row in rows] == ["fast_model", "strong_model"]
        assert [row.status for row in rows] == ["error", "success"]
        primary_meta = json.loads(rows[0].metadata_json)
        fallback_meta = json.loads(rows[1].metadata_json)
        assert primary_meta["attempt_index"] == 0
        assert primary_meta["fallback_used"] is False
        assert fallback_meta["attempt_index"] == 1
        assert fallback_meta["fallback_of"] == "fast_model"
        assert fallback_meta["parent_alias"] == "fast_model"
        assert fallback_meta["fallback_used"] is True
    finally:
        db.close()


def test_primary_and_fallback_both_fail_record_two_errors(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    _configure_fast_and_strong(monkeypatch)
    _QueueOpenAI.outcomes = [RuntimeError("fast down"), ValueError("strong down")]
    _QueueOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _QueueOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    try:
        client.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            model_alias="fast_model",
            node_name="fallback_test",
        )
        assert False, "expected fallback error"
    except ValueError:
        pass

    assert client.last_model_call_trace["fallback_used"] is True
    assert len(client.last_model_call_trace["attempts"]) == 2
    db = session_factory()
    try:
        rows = db.query(ModelCallLog).order_by(ModelCallLog.id.asc()).all()
        assert [row.status for row in rows] == ["error", "error"]
        assert [row.error_type for row in rows] == ["RuntimeError", "ValueError"]
    finally:
        db.close()


def test_fallback_does_not_loop_forever(monkeypatch):
    _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    _configure_fast_and_strong(monkeypatch)
    _QueueOpenAI.outcomes = [RuntimeError("fast down"), _response(), _response()]
    _QueueOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _QueueOpenAI)

    from app.llm.client import LLMClient

    client = LLMClient()
    client.chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model_alias="fast_model",
        node_name="fallback_test",
        max_fallback_attempts=1,
    )

    assert len(_QueueOpenAI.instances) == 2
    assert len(client.last_model_call_trace["attempts"]) == 2


def test_fallback_can_be_disabled(monkeypatch):
    session_factory = _isolated_db(monkeypatch)
    _clear_env(monkeypatch)
    _configure_fast_and_strong(monkeypatch)
    _QueueOpenAI.outcomes = [RuntimeError("fast down"), _response()]
    _QueueOpenAI.instances = []
    monkeypatch.setattr("app.llm.client.OpenAI", _QueueOpenAI)

    from app.llm.client import LLMClient
    from app.models.model_call_log import ModelCallLog

    client = LLMClient()
    try:
        client.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            model_alias="fast_model",
            node_name="fallback_test",
            allow_fallback=False,
        )
        assert False, "expected primary error"
    except RuntimeError:
        pass

    assert len(_QueueOpenAI.instances) == 1
    db = session_factory()
    try:
        assert db.query(ModelCallLog).count() == 1
    finally:
        db.close()
