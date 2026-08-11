"""Tests for LLM providers and ProviderRouter."""

from __future__ import annotations

import logging

import pytest
import requests

from ultron.core.llm import LLMError, OllamaProvider, OpenRouterProvider, ProviderRouter


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def _tags(models=("llama3.1:8b",)):
    return {"models": [{"name": m, "modified_at": "", "size": 1} for m in models]}


def _tags_response(*a, **k):
    return FakeResponse(200, _tags())


def test_ollama_available_true(monkeypatch, config):
    monkeypatch.setattr(
        requests, "get", lambda url, timeout: FakeResponse(200, _tags())
    )
    provider = OllamaProvider(config, logging.getLogger("test"))
    assert provider.available is True


def test_ollama_available_false_when_disabled(config):
    object.__setattr__(config, "ollama_enabled", False)
    provider = OllamaProvider(config, logging.getLogger("test"))
    assert provider.available is False


def test_ollama_available_false_when_model_missing(monkeypatch, config):
    monkeypatch.setattr(
        requests, "get", lambda url, timeout: FakeResponse(200, _tags("nope:latest"))
    )
    provider = OllamaProvider(config, logging.getLogger("test"))
    assert provider.available is False
    health = provider.health()
    assert "ollama pull" in health["reason"]


def test_ollama_available_false_on_connection_error(monkeypatch, config):
    def fake_get(url, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fake_get)
    provider = OllamaProvider(config, logging.getLogger("test"))
    assert provider.available is False
    assert "ollama serve" in provider.health()["reason"]


def test_ollama_chat_success(monkeypatch, config):
    def fake_post(url, json, timeout):
        return FakeResponse(200, {"message": {"content": "Hello from Ollama!"}})

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider(config, logging.getLogger("test"))
    reply = provider.chat([{"role": "user", "content": "hi"}])
    assert reply == "Hello from Ollama!"


def test_ollama_chat_http_error(monkeypatch, config):
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, timeout: FakeResponse(500, text="internal error"),
    )
    provider = OllamaProvider(config, logging.getLogger("test"))
    with pytest.raises(LLMError):
        provider.chat([{"role": "user", "content": "hi"}])


def test_openrouter_available(config):
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    provider = OpenRouterProvider(config, logging.getLogger("test"))
    assert provider.available is True


def test_provider_router_uses_ollama_first(monkeypatch, config):
    monkeypatch.setattr(requests, "get", _tags_response)
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, timeout: FakeResponse(
            200, {"message": {"content": "Ollama response"}}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    reply = router.chat([{"role": "user", "content": "hi"}])
    assert reply == "Ollama response"


def test_provider_router_fallback_to_openrouter(monkeypatch, config):
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)

    # Ollama unavailable
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse(500))
    # OpenRouter succeeds
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, headers, timeout: FakeResponse(
            200, {"choices": [{"message": {"content": "OpenRouter response"}}]}
        ),
    )

    router = ProviderRouter(config, logging.getLogger("test"))
    reply = router.chat([{"role": "user", "content": "hi"}])
    assert reply == "OpenRouter response"


def test_provider_router_fails_when_all_down(monkeypatch, config):
    object.__setattr__(config, "openrouter_api_key", "")
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse(500))
    router = ProviderRouter(config, logging.getLogger("test"))
    with pytest.raises(LLMError, match="No LLM providers"):
        router.chat([{"role": "user", "content": "hi"}])
    assert router.available is False
    assert router.local_available is False


def test_provider_router_local_available(monkeypatch, config):
    monkeypatch.setattr(requests, "get", _tags_response)
    router = ProviderRouter(config, logging.getLogger("test"))
    assert router.local_available is True
    assert router.available is True


def test_provider_router_chat_fallback_after_call_failure(monkeypatch, config):
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)

    def fake_get(url, timeout):
        return FakeResponse(200, _tags())

    def fake_post(url, json, timeout=None, headers=None):
        if "/api/chat" in url:
            return FakeResponse(500, text="model load error")
        return FakeResponse(
            200, {"choices": [{"message": {"content": "OpenRouter response"}}]}
        )

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    router = ProviderRouter(config, logging.getLogger("test"))
    reply = router.chat([{"role": "user", "content": "hi"}])
    assert reply == "OpenRouter response"


def test_ollama_chat_sends_think_false(monkeypatch, config):
    captured: dict = {}

    def fake_post(url, json, timeout):
        captured.update(json)
        return FakeResponse(200, {"message": {"content": "ok"}})

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider(config, logging.getLogger("test"))
    provider.chat([{"role": "user", "content": "hi"}])
    assert captured.get("think") is False
    assert "num_predict" in captured["options"]


# ---------------------------------------------------------------------------
# Deterministic routing policies
# ---------------------------------------------------------------------------


def test_policy_local_only_never_uses_openrouter(monkeypatch, config):
    from ultron.config import RoutingPolicy

    object.__setattr__(config, "routing_policy", RoutingPolicy.LOCAL_ONLY)
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)
    # Ollama itself is down -> strictly NO cloud fallback allowed.
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse(500))
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, headers, timeout: FakeResponse(
            200, {"choices": [{"message": {"content": "OpenRouter response"}}]}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    assert router.available is False
    with pytest.raises(LLMError):
        router.chat([{"role": "user", "content": "hi"}])


def test_policy_remote_only_never_uses_ollama(monkeypatch, config):
    from ultron.config import RoutingPolicy

    object.__setattr__(config, "routing_policy", RoutingPolicy.REMOTE_ONLY)
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)
    # Ollama healthy, but REMOTE_ONLY must still pick OpenRouter.
    monkeypatch.setattr(requests, "get", _tags_response)
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, headers, timeout: FakeResponse(
            200, {"choices": [{"message": {"content": "OpenRouter response"}}]}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    reply = router.chat([{"role": "user", "content": "hi"}])
    assert reply == "OpenRouter response"


def test_policy_prefer_remote_uses_openrouter_first(monkeypatch, config):
    from ultron.config import RoutingPolicy

    object.__setattr__(config, "routing_policy", RoutingPolicy.PREFER_REMOTE)
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)
    monkeypatch.setattr(requests, "get", _tags_response)
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, headers, timeout: FakeResponse(
            200, {"choices": [{"message": {"content": "OpenRouter response"}}]}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    assert router.chat([{"role": "user", "content": "hi"}]) == "OpenRouter response"


def test_policy_prefer_local_prefers_ollama(monkeypatch, config):
    from ultron.config import RoutingPolicy

    object.__setattr__(config, "routing_policy", RoutingPolicy.PREFER_LOCAL)
    object.__setattr__(config, "openrouter_api_key", "sk-test")
    monkeypatch.setattr("ultron.core.llm.is_online", lambda *a, **k: True)
    monkeypatch.setattr(requests, "get", _tags_response)
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, timeout: FakeResponse(
            200, {"message": {"content": "Ollama response"}}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    assert router.chat([{"role": "user", "content": "hi"}]) == "Ollama response"


def test_override_provider_forces_ollama(monkeypatch, config):
    monkeypatch.setattr(requests, "get", _tags_response)
    monkeypatch.setattr(
        requests,
        "post",
        lambda url, json, timeout: FakeResponse(
            200, {"message": {"content": "Ollama response"}}
        ),
    )
    router = ProviderRouter(config, logging.getLogger("test"))
    reply = router.chat([{"role": "user", "content": "hi"}], provider="ollama")
    assert reply == "Ollama response"


def test_override_unknown_provider_raises(monkeypatch, config):
    monkeypatch.setattr(requests, "get", _tags_response)
    router = ProviderRouter(config, logging.getLogger("test"))
    with pytest.raises(LLMError, match="unknown provider"):
        router.chat([{"role": "user", "content": "hi"}], provider="brain")


def test_no_provider_error_contains_recovery_hint(monkeypatch, config):
    object.__setattr__(config, "openrouter_api_key", "")
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResponse(500))
    router = ProviderRouter(config, logging.getLogger("test"))
    with pytest.raises(LLMError, match="ollama serve"):
        router.chat([{"role": "user", "content": "hi"}])
