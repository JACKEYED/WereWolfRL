"""Security-focused tests for API credential resolution."""

from modules.model.llm_model import resolve_api_key


def test_api_key_is_loaded_from_named_environment_variable(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_API_KEY", "test-credential")

    value = resolve_api_key(
        {"api_key_env": "TEST_PROVIDER_API_KEY", "api_key": "ignored-value"}
    )

    assert value == "test-credential"


def test_empty_environment_variable_does_not_fall_back_to_config(monkeypatch):
    monkeypatch.delenv("TEST_PROVIDER_API_KEY", raising=False)

    value = resolve_api_key(
        {"api_key_env": "TEST_PROVIDER_API_KEY", "api_key": "must-not-be-used"}
    )

    assert value == ""


def test_local_provider_can_still_use_non_secret_placeholder():
    assert resolve_api_key({"api_key": "EMPTY"}) == "EMPTY"
