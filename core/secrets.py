"""Secrets store — manages API keys in config/secrets.yaml."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SECRETS_PATH = Path(__file__).parent.parent / "config" / "secrets.yaml"

# Providers that use API keys
_API_KEY_PROVIDERS = {"groq", "gemini", "openai", "anthropic"}


def _mask_key(key: str) -> str:
    """Mask an API key, showing only last 4 chars."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"****{key[-4:]}"


def _encode_key(key: str) -> str:
    """Lightweight encoding (not encryption) for at-rest obfuscation."""
    if not key:
        return ""
    return base64.b64encode(key.encode()).decode()


def _decode_key(encoded: str) -> str:
    """Decode a base64-encoded key."""
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return encoded


class SecretsStore:
    """Manages API keys and secrets in config/secrets.yaml."""

    def __init__(self, path: str | Path = _SECRETS_PATH):
        self._path = Path(path)
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load secrets from disk."""
        if self._path.exists():
            try:
                self._data = yaml.safe_load(self._path.read_text()) or {}
            except Exception as exc:
                logger.warning("Failed to load secrets: %s", exc)
                self._data = {}
        else:
            self._data = {}
        logger.info("Secrets loaded from %s", self._path)

    def save(self) -> None:
        """Persist secrets to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(yaml.dump(self._data, default_flow_style=False, allow_unicode=True))
        logger.info("Secrets saved to %s", self._path)

    def get_raw(self, provider: str) -> str:
        """Get the raw (decoded) API key for a provider."""
        entry = self._data.get(provider, {})
        encoded = entry.get("api_key", "")
        return _decode_key(encoded)

    def get_masked(self, provider: str) -> str:
        """Get a masked version of the API key."""
        return _mask_key(self.get_raw(provider))

    def set_key(self, provider: str, api_key: str) -> None:
        """Set an API key for a provider (encodes and saves)."""
        if provider not in self._data:
            self._data[provider] = {}
        self._data[provider]["api_key"] = _encode_key(api_key)
        self._data[provider]["enabled"] = bool(api_key)
        self.save()
        logger.info("API key set for %s", provider)

    def delete_key(self, provider: str) -> bool:
        """Remove an API key for a provider."""
        if provider in self._data:
            self._data[provider]["api_key"] = ""
            self._data[provider]["enabled"] = False
            self.save()
            logger.info("API key deleted for %s", provider)
            return True
        return False

    def is_enabled(self, provider: str) -> bool:
        """Check if a provider is enabled."""
        return bool(self._data.get(provider, {}).get("enabled", False))

    def set_enabled(self, provider: str, enabled: bool) -> None:
        """Enable or disable a provider."""
        if provider not in self._data:
            self._data[provider] = {}
        self._data[provider]["enabled"] = enabled
        self.save()

    def list_providers(self) -> dict[str, dict]:
        """List all providers with masked keys and status."""
        result = {}
        for provider, entry in self._data.items():
            raw_key = _decode_key(entry.get("api_key", ""))
            result[provider] = {
                "has_key": bool(raw_key),
                "key_masked": _mask_key(raw_key),
                "enabled": entry.get("enabled", False),
            }
        return result

    def get_all_keys(self) -> dict[str, str]:
        """Get all raw API keys (for internal use only, never exposed via API)."""
        return {p: _decode_key(e.get("api_key", "")) for p, e in self._data.items()}

    def get_setting(self, provider: str, key: str, default: Any = None) -> Any:
        """Get a non-key setting for a provider (e.g., url, model)."""
        return self._data.get(provider, {}).get(key, default)

    def set_setting(self, provider: str, key: str, value: Any) -> None:
        """Set a non-key setting for a provider."""
        if provider not in self._data:
            self._data[provider] = {}
        self._data[provider][key] = value
        self.save()
