from __future__ import annotations


def test_jst_config_prefers_current_process_environment(monkeypatch):
    from app import config

    primary = "TEST_JST_PRIMARY_PROCESS_VALUE"
    alias = "TEST_JST_ALIAS_PROCESS_VALUE"
    monkeypatch.setenv(primary, "process-value")
    monkeypatch.delenv(alias, raising=False)

    def fail_if_registry_is_read(_name: str) -> str:
        raise AssertionError("process environment must take precedence")

    monkeypatch.setattr(config, "_read_windows_user_environment", fail_if_registry_is_read)

    assert config._read_jst_environment_value(primary, alias) == "process-value"


def test_jst_config_falls_back_to_windows_user_environment(monkeypatch):
    from app import config

    primary = "TEST_JST_PRIMARY_USER_VALUE"
    alias = "TEST_JST_ALIAS_USER_VALUE"
    monkeypatch.delenv(primary, raising=False)
    monkeypatch.delenv(alias, raising=False)
    reads: list[str] = []

    def read_user_environment(name: str) -> str:
        reads.append(name)
        return "user-value" if name == alias else ""

    monkeypatch.setattr(config, "_read_windows_user_environment", read_user_environment)

    assert config._read_jst_environment_value(primary, alias) == "user-value"
    assert reads == [primary, alias]
