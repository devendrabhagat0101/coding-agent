"""
Local authentication and session management.

All data lives in ~/.coding-agent/
  auth.json      — registered user (username + hashed password)
  session.json   — active session token + expiry
  permissions.json — directories the user has approved for read/write
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Storage paths ────────────────────────────────────────────────────────────

CONFIG_DIR   = Path.home() / ".coding-agent"
AUTH_FILE    = CONFIG_DIR / "auth.json"
SESSION_FILE = CONFIG_DIR / "session.json"
PERMS_FILE   = CONFIG_DIR / "permissions.json"

SESSION_TTL_HOURS = 24


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


# ── Password hashing (PBKDF2-HMAC-SHA256, no extra deps) ────────────────────

def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex(), salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = _hash_password(password, salt)
    return secrets.compare_digest(candidate, stored_hash)


# ── Auth CRUD ────────────────────────────────────────────────────────────────

def has_account() -> bool:
    return AUTH_FILE.exists()


def register(username: str, password: str) -> None:
    _ensure_dir()
    pw_hash, salt = _hash_password(password)
    AUTH_FILE.write_text(
        json.dumps({"username": username, "hash": pw_hash, "salt": salt}),
        encoding="utf-8",
    )
    AUTH_FILE.chmod(0o600)


def verify_credentials(password: str) -> str | None:
    """Return username if password matches, else None."""
    if not AUTH_FILE.exists():
        return None
    data = json.loads(AUTH_FILE.read_text())
    if _verify_password(password, data["hash"], data["salt"]):
        return data["username"]
    return None


def get_stored_username() -> str | None:
    if not AUTH_FILE.exists():
        return None
    return json.loads(AUTH_FILE.read_text()).get("username")


# ── Session management ───────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_session(username: str) -> str:
    _ensure_dir()
    token = secrets.token_hex(32)
    expires = (_now_utc() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    SESSION_FILE.write_text(
        json.dumps({"username": username, "token": token, "expires": expires}),
        encoding="utf-8",
    )
    SESSION_FILE.chmod(0o600)
    return token


def get_active_session() -> dict | None:
    """Return session dict if valid and unexpired, else None."""
    if not SESSION_FILE.exists():
        return None
    data = json.loads(SESSION_FILE.read_text())
    expires = datetime.fromisoformat(data["expires"])
    if _now_utc() > expires:
        SESSION_FILE.unlink(missing_ok=True)
        return None
    return data


def is_logged_in() -> bool:
    return get_active_session() is not None


def logout() -> None:
    SESSION_FILE.unlink(missing_ok=True)


# ── Directory permissions ────────────────────────────────────────────────────

def _load_perms() -> list[str]:
    if not PERMS_FILE.exists():
        return []
    return json.loads(PERMS_FILE.read_text())


def _save_perms(paths: list[str]) -> None:
    _ensure_dir()
    PERMS_FILE.write_text(json.dumps(paths, indent=2), encoding="utf-8")
    PERMS_FILE.chmod(0o600)


def is_directory_approved(path: Path) -> bool:
    canonical = str(path.resolve())
    return canonical in _load_perms()


def approve_directory(path: Path) -> None:
    canonical = str(path.resolve())
    perms = _load_perms()
    if canonical not in perms:
        perms.append(canonical)
        _save_perms(perms)


def revoke_directory(path: Path) -> None:
    canonical = str(path.resolve())
    perms = [p for p in _load_perms() if p != canonical]
    _save_perms(perms)


def list_approved_directories() -> list[str]:
    return _load_perms()
