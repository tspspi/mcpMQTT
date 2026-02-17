"""Helpers for managing Argon2id-protected API keys."""

from __future__ import annotations

import base64
import hmac
import os
import secrets
from typing import Any, Dict, Optional

from argon2.low_level import Type, hash_secret_raw

from mcpMQTT.config.schema import APIKeyKDFConfig, RemoteServerConfig

# Defaults chosen to balance security with reasonable CPU/memory usage on servers
DEFAULT_ARGON2_SETTINGS: Dict[str, int] = {
    "time_cost": 3,
    "memory_cost": 64 * 1024,
    "parallelism": 1,
    "hash_len": 32,
}

DEFAULT_SALT_BYTES = 16
DEFAULT_API_KEY_BYTES = 32


def generate_random_api_key(byte_length: int = DEFAULT_API_KEY_BYTES) -> str:
    """Return a URL-safe random API key string."""
    return secrets.token_urlsafe(byte_length)


def ensure_kdf_defaults(existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge defaults into an API key KDF dictionary."""
    kdf = dict(existing or {})
    kdf.setdefault("algorithm", "argon2id")
    for key, value in DEFAULT_ARGON2_SETTINGS.items():
        kdf.setdefault(key, value)
    return kdf


def ensure_kdf_salt(kdf: Dict[str, Any], salt_bytes: int = DEFAULT_SALT_BYTES) -> None:
    """Ensure the supplied KDF dict has a salt, inserting one if missing."""
    if not kdf.get("salt"):
        kdf["salt"] = base64.b64encode(os.urandom(salt_bytes)).decode("ascii")


def derive_argon2id_hash(api_key: str, kdf: Dict[str, Any]) -> str:
    """Derive a base64-encoded Argon2id hash for the given API key."""
    salt = base64.b64decode(kdf["salt"])
    derived = hash_secret_raw(
        secret=api_key.encode("utf-8"),
        salt=salt,
        time_cost=int(kdf["time_cost"]),
        memory_cost=int(kdf["memory_cost"]),
        parallelism=int(kdf["parallelism"]),
        hash_len=int(kdf["hash_len"]),
        type=Type.ID,
    )
    return base64.b64encode(derived).decode("ascii")


def _hash_with_config(secret: str, config: APIKeyKDFConfig) -> bytes:
    salt = base64.b64decode(config.salt)
    return hash_secret_raw(
        secret=secret.encode("utf-8"),
        salt=salt,
        time_cost=config.time_cost,
        memory_cost=config.memory_cost,
        parallelism=config.parallelism,
        hash_len=config.hash_len,
        type=Type.ID,
    )


def verify_api_key(token: str, remote_config: RemoteServerConfig) -> bool:
    """Check whether the provided token matches the configured API key."""
    if not token:
        return False

    if remote_config.api_key_kdf:
        expected = base64.b64decode(remote_config.api_key_kdf.hash)
        computed = _hash_with_config(token, remote_config.api_key_kdf)
        return hmac.compare_digest(expected, computed)

    if remote_config.api_key:
        return hmac.compare_digest(remote_config.api_key, token)

    return False
