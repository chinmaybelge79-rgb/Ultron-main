"""LLM Provider abstraction layer.

Supports multiple LLM backends: local Ollama (zero cloud dependency) and
OpenRouter (cloud models). Provider selection is a **deterministic state
machine** driven by an explicit :class:`~ultron.config.RoutingPolicy`
rather than implicit availability guessing, so every request has exactly
one selected provider and a logged reason for that choice.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from ultron.config import Config, RoutingPolicy
from ultron.utils import LLMError, LLMRetryableError, is_online, retry


class LLMProvider(ABC):
    """Abstract base class for all LLM backends."""

    name: str = ""

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Send a chat request and return the assistant reply text."""

    @property
    def available(self) -> bool:
        """True when this provider is configured and healthy right now."""
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        """Cheap (no I/O) check that this provider is enabled by config.

        Unlike :attr:`available`, this never touches the network, so the
        hot path can decide whether routing is worth attempting without a
        probe on every command.
        """
        return True


class OllamaProvider(LLMProvider):
    """Local LLM provider using Ollama HTTP API (zero-cloud execution).

    Args:
        config: Application configuration.
        logger: Logger for this provider.
    """

    name = "ollama"

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger

    @property
    def configured(self) -> bool:
        """True when local inference is enabled by configuration."""
        return self._config.ollama_enabled

    def health(self) -> dict[str, Any]:
        """Probe the local Ollama server and report the exact status.

        This is the single source of truth used by routing and by
        diagnostics. It never raises; every failure is folded into a
        human-readable ``reason`` so callers can produce actionable
        recovery instructions.

        Returns:
            A dict with ``reachable``, ``models``, ``model``,
            ``model_installed`` and ``reason`` keys.
        """
        result: dict[str, Any] = {
            "reachable": False,
            "models": [],
            "model": self._config.ollama_model,
            "model_installed": False,
            "reason": "",
        }
        if not self._config.ollama_enabled:
            result["reason"] = "Ollama disabled by configuration"
            return result
        try:
            res = requests.get(f"{self._config.ollama_url}/api/tags", timeout=1.5)
        except requests.RequestException as exc:
            result["reason"] = (
                f"Ollama server unreachable at {self._config.ollama_url} ({exc}). "
                "Start it with 'ollama serve'."
            )
            return result
        if res.status_code != 200:
            result["reason"] = f"Ollama server returned HTTP {res.status_code}"
            return result
        try:
            data = res.json()
        except ValueError as exc:
            result["reason"] = f"Malformed /api/tags response: {exc}"
            return result
        result["reachable"] = True
        result["models"] = [str(m.get("name", "")) for m in data.get("models", [])]
        wanted = self._config.ollama_model
        result["model_installed"] = (wanted in result["models"]) or any(
            m.startswith(wanted + ":") for m in result["models"]
        )
        if result["model_installed"]:
            result["reason"] = f"Model '{wanted}' installed"
        else:
            result["reason"] = (
                f"Model '{wanted}' not installed. Run: ollama pull {wanted}"
            )
        return result

    @property
    def available(self) -> bool:
        """True when the server responds and the configured model is present."""
        health = self.health()
        self._log.debug("Ollama health: %s", health["reason"])
        return health["reachable"] and health["model_installed"]

    @retry(
        attempts=2,
        base_delay=0.5,
        backoff=2.0,
        exceptions=(LLMRetryableError,),
        jitter=0.1,
    )
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        model = kwargs.get("model", self._config.ollama_model)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": kwargs.get("think", self._config.ollama_thinking),
            "options": {
                "temperature": kwargs.get("temperature", self._config.llm_temperature),
                "num_predict": kwargs.get("max_tokens", self._config.llm_max_tokens),
            },
        }
        url = f"{self._config.ollama_url}/api/chat"
        self._log.debug("Calling local Ollama (%s)", model)
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=(5.0, 120.0),
            )
        except requests.RequestException as exc:
            raise LLMRetryableError(f"Ollama request failed: {exc}") from exc

        if response.status_code != 200:
            raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")

        try:
            data = response.json()
            return str(data["message"]["content"]).strip()
        except (KeyError, ValueError) as exc:
            raise LLMError(f"Malformed Ollama response: {exc}") from exc


class OpenRouterProvider(LLMProvider):
    """Cloud LLM provider using the OpenRouter API."""

    name = "openrouter"

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger

    @property
    def configured(self) -> bool:
        """True when an OpenRouter API key is present."""
        return self._config.llm_configured

    @property
    def available(self) -> bool:
        """Configured and (checked by the router) online."""
        return self._config.llm_configured

    @retry(
        attempts=3,
        base_delay=1.0,
        backoff=2.0,
        exceptions=(LLMRetryableError,),
        jitter=0.25,
    )
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        if not self.available:
            raise LLMError(
                "OpenRouter is not configured. Add OPENROUTER_API_KEY to .env"
            )

        model = kwargs.get("model", self._config.openrouter_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self._config.llm_temperature),
            "max_tokens": self._config.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._config.openrouter_api_key}",
            "Content-Type": "application/json",
            "X-Title": "Ultron",
        }
        self._log.debug("Calling OpenRouter (%s)", model)
        try:
            response = requests.post(
                self._config.openrouter_url,
                json=payload,
                headers=headers,
                timeout=self._config.llm_timeout,
            )
        except requests.RequestException as exc:
            raise LLMRetryableError(f"OpenRouter request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise LLMError(
                f"OpenRouter authentication failed (HTTP {response.status_code})."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMRetryableError(
                f"OpenRouter returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        if response.status_code != 200:
            raise LLMError(
                f"OpenRouter returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Malformed OpenRouter response: {exc}") from exc
        return str(content).strip()


class ProviderRouter:
    """Deterministic LLM routing state machine.

    Selection is driven entirely by :attr:`Config.routing_policy`; there
    is no implicit guessing. Every request logs the selected provider,
    the reason it was chosen, its health status and model before the
    call, plus the measured latency afterwards.

    Fallback is *policy-aware*: ``LOCAL_ONLY`` never silently uses the
    cloud and ``REMOTE_ONLY`` never uses the local model. When every
    permitted provider fails, a single :class:`LLMError` with actionable
    recovery instructions is raised, never a hang.
    """

    def __init__(self, config: Config, logger: logging.Logger) -> None:
        self._config = config
        self._log = logger
        self._providers: dict[str, LLMProvider] = {
            "ollama": OllamaProvider(config, logging.getLogger("ultron.ollama")),
            "openrouter": OpenRouterProvider(
                config, logging.getLogger("ultron.openrouter")
            ),
        }
        self._online_checked_at = 0.0
        self._online = False

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def _policy_order(self) -> list[str]:
        """Providers that this policy *permits*, in preference order."""
        policy = self._config.routing_policy
        if policy is RoutingPolicy.LOCAL_ONLY:
            return ["ollama"]
        if policy is RoutingPolicy.REMOTE_ONLY:
            return ["openrouter"]
        if policy is RoutingPolicy.PREFER_REMOTE:
            return ["openrouter", "ollama"]
        return ["ollama", "openrouter"]  # AUTO and PREFER_LOCAL

    def _internet_available(self) -> bool:
        """Cached (30s TTL) connectivity probe used before remote routing."""
        now = time.monotonic()
        if now - self._online_checked_at > 30.0:
            self._online = is_online(timeout=1.0)
            self._online_checked_at = now
        return self._online

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def resolve(
        self, provider_override: str | None = None, probe: bool = True
    ) -> tuple[LLMProvider | None, str]:
        """Deterministically choose the provider for the next request.

        Args:
            provider_override: Force a provider by name (skips policy).
            probe: When True, require the provider to pass a live health
                probe. When False, only configuration is consulted.

        Returns:
            ``(provider, reason)``. ``provider`` is None when no
            permitted provider is currently usable, and ``reason``
            explains exactly why.
        """
        if provider_override:
            provider = self._providers.get(provider_override)
            if provider is None:
                return None, (
                    f"explicit override: unknown provider {provider_override!r}"
                )
            if not provider.configured:
                return None, (
                    f"explicit override: provider {provider_override!r} "
                    "is not configured"
                )
            if probe and not provider.available:
                return None, (
                    f"explicit override: provider {provider_override!r} "
                    "failed its health probe"
                )
            return provider, f"explicit override ({provider_override})"

        policy = self._config.routing_policy
        reasons: list[str] = []
        for name in self._policy_order():
            provider = self._providers[name]
            if not provider.configured:
                reasons.append(f"{name}: not configured")
                continue
            if name == "openrouter" and not self._internet_available():
                reasons.append(f"{name}: no internet")
                continue
            if probe:
                healthy = provider.available
                reasons.append(f"{name}: healthy={healthy}")
                if healthy:
                    return provider, f"policy={policy.value}, {name} healthy"
            else:
                return provider, f"policy={policy.value}, {name} (no probe)"
        return None, f"policy={policy.value}; " + "; ".join(reasons)

    @property
    def available(self) -> bool:
        """True when some permitted provider is currently usable."""
        return self.resolve()[0] is not None

    @property
    def configured(self) -> bool:
        """True when any provider is enabled by config (no I/O)."""
        return any(provider.configured for provider in self._providers.values())

    @property
    def local_available(self) -> bool:
        """True when the local (Ollama) backend is up with its model."""
        return self._providers["ollama"].available

    @property
    def policy(self) -> RoutingPolicy:
        """The active routing policy."""
        return self._config.routing_policy

    # ------------------------------------------------------------------
    # Chat with deterministic fallback
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Serve one request through the policy-permitted providers.

        Args:
            messages: Chat message list forwarded to the provider.
            **kwargs: Forwarded to the provider. A ``provider`` keyword
                forces routing to that exact provider.

        Returns:
            The assistant reply text.

        Raises:
            LLMError: When no permitted provider succeeds, with recovery
                instructions in the message.
        """
        override = kwargs.pop("provider", None)
        provider, reason = self.resolve(provider_override=override)
        if provider is None:
            raise LLMError(self._describe_no_provider(reason))

        self._log.info(
            "ROUTER select=%s reason=%s model=%s",
            provider.name,
            reason,
            kwargs.get("model", "config-default"),
        )

        permitted = self._policy_order()
        if self._config.routing_policy in (
            RoutingPolicy.LOCAL_ONLY,
            RoutingPolicy.REMOTE_ONLY,
        ):
            permitted = [provider.name]
        if override is not None:
            permitted = [provider.name]

        errors: list[str] = []
        for name in permitted:
            candidate = self._providers[name]
            started = time.monotonic()
            try:
                reply = candidate.chat(messages, **kwargs)
            except Exception as exc:
                latency_ms = (time.monotonic() - started) * 1000
                errors.append(f"{name}: {exc}")
                self._log.warning(
                    "ROUTER fail=%s latency=%.0fms error=%s",
                    name,
                    latency_ms,
                    exc,
                )
                continue
            latency_ms = (time.monotonic() - started) * 1000
            self._log.info("ROUTER ok=%s latency=%.0fms", name, latency_ms)
            return reply
        raise LLMError(self._describe_failure(errors))

    # ------------------------------------------------------------------
    # Actionable failure messages
    # ------------------------------------------------------------------

    def _describe_no_provider(self, reason: str) -> str:
        """Build an actionable message when no provider can be selected."""
        policy = self._config.routing_policy.value
        hint = ""
        if self._config.ollama_enabled:
            health: dict[str, Any] = self._providers["ollama"].health()
            if not health["reachable"]:
                hint = (
                    f"Start Ollama with 'ollama serve' or fix "
                    f"ULTRON_OLLAMA_URL={self._config.ollama_url}."
                )
            elif not health["model_installed"]:
                hint = f"Install the Ollama model: ollama pull {health['model']}"
        elif not self._config.llm_configured:
            hint = (
                "Set OPENROUTER_API_KEY in .env or enable Ollama "
                "(ULTRON_OLLAMA_ENABLED=true)."
            )
        return (
            "No LLM providers are currently available "
            f"(policy={policy}). {reason} {hint}"
        ).strip()

    def _describe_failure(self, errors: list[str]) -> str:
        """Build the final message when permitted providers all failed."""
        policy = self._config.routing_policy.value
        hint = ""
        if self._config.ollama_enabled:
            hint = (
                f"Run 'ollama pull {self._config.ollama_model}' and verify "
                "'ollama serve' is running."
            )
        elif self._config.llm_configured:
            hint = "Check OPENROUTER_API_KEY and your internet connection."
        return (
            "All permitted LLM providers failed (policy={}): {} {}".format(
                policy, "; ".join(errors), hint
            )
        ).strip()
