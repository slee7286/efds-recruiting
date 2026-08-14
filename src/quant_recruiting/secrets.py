"""OS-backed secret storage extension point.

Secrets are never silently written to the local TOML file. The optional
``keyring`` dependency delegates storage to Windows Credential Manager,
macOS Keychain, or an available Linux Secret Service backend.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, cast

from quant_recruiting.config import Settings, get_settings


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class SecretStoreUnavailable(RuntimeError):
    """Raised when a platform secret store is not installed or available."""


class KeyringSecretStore:
    def __init__(self, service: str = "Recruiting Assistant") -> None:
        try:
            self._keyring = importlib.import_module("keyring")
        except ModuleNotFoundError as exc:
            raise SecretStoreUnavailable(
                "install the keyring extra to use OS-backed secret storage"
            ) from exc
        self.service = service

    def get(self, name: str) -> str | None:
        value: Any = self._keyring.get_password(self.service, name)
        return cast(str | None, value)

    def set(self, name: str, value: str) -> None:
        self._keyring.set_password(self.service, name, value)

    def delete(self, name: str) -> None:
        try:
            self._keyring.delete_password(self.service, name)
        except Exception:
            return


class UnavailableSecretStore:
    def get(self, _name: str) -> str | None:
        return None

    def set(self, _name: str, _value: str) -> None:
        raise SecretStoreUnavailable("no OS-backed secret store is available")

    def delete(self, _name: str) -> None:
        return


def get_secret_store(settings: Settings | None = None) -> SecretStore:
    config = settings or get_settings()
    if config.secret_store in {"auto", "keyring"}:
        try:
            return KeyringSecretStore()
        except SecretStoreUnavailable:
            if config.secret_store == "keyring":
                raise
    return UnavailableSecretStore()
