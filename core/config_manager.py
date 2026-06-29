"""Config manager — central coordinator for runtime configuration."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from core.secrets import SecretsStore

if TYPE_CHECKING:
    from core.llm_router import LLMRouter
    from core.stores import SettingsStore

logger = logging.getLogger(__name__)

# Map simple provider names to router internal names
_PROVIDER_NAME_MAP = {
    "groq": "groq_free",
    "gemini": "gemini_flash",
    "openai": "openai_mini",
    "anthropic": "claude_sonnet",
    "ollama": "ollama_local",
    "nim": "nim_llama70b",
}

_PROVIDER_TYPE_MAP = {v: k for k, v in _PROVIDER_NAME_MAP.items()}


class ConfigManager:
    """Manages runtime configuration: secrets (API keys) + settings (toggles, models)."""

    def __init__(self, secrets: SecretsStore, settings: SettingsStore):
        self._secrets = secrets
        self._settings = settings
        self._llm_router: LLMRouter | None = None
        self._callbacks: list = []

    def set_llm_router(self, router: LLMRouter) -> None:
        """Bind the LLM router for dynamic reconfiguration."""
        self._llm_router = router

    def _resolve_name(self, name: str) -> str:
        """Resolve simple provider name to router internal name."""
        return _PROVIDER_NAME_MAP.get(name, name)

    def _inverse_name(self, internal_name: str) -> str:
        """Resolve router internal name to simple provider name."""
        return _PROVIDER_TYPE_MAP.get(internal_name, internal_name)

    def on_change(self, callback) -> None:
        """Register a callback for config changes."""
        self._callbacks.append(callback)

    def _notify(self, key: str, value: Any) -> None:
        for cb in self._callbacks:
            try:
                cb(key, value)
            except Exception as exc:
                logger.warning("Config callback error: %s", exc)

    # ── LLM Provider Keys ──────────────────────────────────────────

    def get_provider_key(self, provider: str) -> str:
        """Get the raw API key for a provider."""
        return self._secrets.get_raw(provider)

    def set_provider_key(self, provider: str, api_key: str) -> None:
        """Set an API key for a provider and update the LLM router."""
        self._secrets.set_key(provider, api_key)
        router_name = self._resolve_name(provider)
        if self._llm_router:
            self._llm_router.update_provider_key(router_name, api_key)
        self._notify(f"provider.{provider}.key", api_key)

    def delete_provider_key(self, provider: str) -> bool:
        """Remove an API key for a provider."""
        result = self._secrets.delete_key(provider)
        router_name = self._resolve_name(provider)
        if result and self._llm_router:
            self._llm_router.update_provider_key(router_name, "")
        if result:
            self._notify(f"provider.{provider}.key", None)
        return result

    def get_provider_status(self, provider: str) -> dict:
        """Get masked key + enabled status for a provider."""
        return self._secrets.list_providers().get(provider, {})

    def list_providers(self) -> dict[str, dict]:
        """List all providers with masked keys and status."""
        return self._secrets.list_providers()

    def set_provider_enabled(self, provider: str, enabled: bool) -> None:
        """Enable or disable a provider."""
        self._secrets.set_enabled(provider, enabled)
        router_name = self._resolve_name(provider)
        if self._llm_router:
            self._llm_router.toggle_provider(router_name, enabled)
        self._notify(f"provider.{provider}.enabled", enabled)

    def get_provider_setting(self, provider: str, key: str, default: Any = None) -> Any:
        """Get a provider setting (url, model, etc.)."""
        return self._secrets.get_setting(provider, key, default)

    def set_provider_setting(self, provider: str, key: str, value: Any) -> None:
        """Set a provider setting."""
        self._secrets.set_setting(provider, key, value)
        router_name = self._resolve_name(provider)
        if self._llm_router:
            self._llm_router.update_provider_setting(router_name, key, value)
        self._notify(f"provider.{provider}.{key}", value)

    # ── Runtime Settings ────────────────────────────────────────────

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get a runtime setting."""
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: str) -> None:
        """Set a runtime setting."""
        self._settings.set(key, value)
        self._notify(f"setting.{key}", value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self._settings.get_bool(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        return self._settings.get_int(key, default)

    def list_settings(self) -> dict[str, str]:
        """List all runtime settings."""
        return self._settings.list()

    # ── Combined Config View ────────────────────────────────────────

    def get_full_config(self) -> dict:
        """Get the full config view for the dashboard (secrets masked)."""
        providers = {}
        for name, info in self._secrets.list_providers().items():
            providers[name] = {
                **info,
                "model": self._secrets.get_setting(name, "model", ""),
                "url": self._secrets.get_setting(name, "url", ""),
                "tier": "",
            }
        # Enrich with router data if available
        if self._llm_router:
            for simple_name, info in providers.items():
                router_name = self._resolve_name(simple_name)
                router_provider = self._llm_router._provider_map.get(router_name)
                if router_provider:
                    info["model"] = info["model"] or router_provider.model
                    info["tier"] = router_provider.tier
                    info["available"] = router_provider.is_available()
        return {
            "providers": providers,
            "settings": self._settings.list(),
        }

    def reload(self) -> None:
        """Reload all config from disk."""
        self._secrets.load()
        if self._llm_router:
            keys = {}
            for simple_name, raw_key in self._secrets.get_all_keys().items():
                router_name = self._resolve_name(simple_name)
                keys[router_name] = raw_key
            self._llm_router.reconfigure(keys)
        logger.info("Config reloaded from disk")
        self._notify("reload", None)
