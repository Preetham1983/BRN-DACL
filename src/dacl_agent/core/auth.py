"""
DACL User Authentication — JWT-based login system.

How role assignment works:
  1. On first server startup, a default admin account is auto-created.
     Credentials are printed to the console (change them immediately).
  2. The admin logs in via POST /api/auth/login → receives a signed JWT.
  3. Admin creates other users (analysts, readers) via POST /api/auth/users.
  4. Those users log in → get their own JWT with their role embedded.
  5. Every API request includes: Authorization: Bearer <jwt>
  6. The OPA gate reads the role from the token — no guessing.

User store:  SQLite at compiled/users.db
Passwords:   PBKDF2-SHA256 with per-user salt (never stored in plain text)
Tokens:      HS256 JWT, configurable expiry (default 8h)
Secret key:  DACL_JWT_SECRET in .env (auto-generated on first run if missing)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from dacl_agent.core.authz import Role, ROLE_PERMISSIONS

load_dotenv()
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

_DB_PATH  = Path("compiled/users.db")
_TOKEN_TTL = int(os.getenv("DACL_JWT_EXPIRY_HOURS", "8")) * 3600  # seconds

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "dacl-admin-2026"   # shown in startup logs; change immediately


def _get_jwt_secret() -> str:
    """Return JWT signing secret. Auto-generates and persists if DACL_JWT_SECRET not set."""
    secret = os.getenv("DACL_JWT_SECRET", "")
    if secret:
        return secret

    # Auto-generate and persist to .env so the secret survives restarts
    secret = secrets.token_hex(32)
    env_path = Path(".env")
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if "DACL_JWT_SECRET" not in existing:
        with env_path.open("a", encoding="utf-8") as f:
            f.write(f"\nDACL_JWT_SECRET={secret}\n")
        log.info("[AUTH] Auto-generated DACL_JWT_SECRET and appended to .env")
    # Also set in current process
    os.environ["DACL_JWT_SECRET"] = secret
    return secret


# ─────────────────────────────────────────────────────────────────────────────
# Password hashing (PBKDF2-SHA256, no external deps needed)
# ─────────────────────────────────────────────────────────────────────────────

def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Hash password. Returns (hash_b64, salt_b64)."""
    if salt is None:
        salt = os.urandom(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(h).decode(), base64.b64encode(salt).decode()


def _verify_password(password: str, hash_b64: str, salt_b64: str) -> bool:
    """Constant-time password verification."""
    salt         = base64.b64decode(salt_b64)
    expected, _  = _hash_password(password, salt)
    return hmac.compare_digest(expected, hash_b64)


# ─────────────────────────────────────────────────────────────────────────────
# Minimal JWT implementation (HS256, no external lib needed)
# ─────────────────────────────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def _issue_jwt(username: str, role: str) -> str:
    """Issue a signed HS256 JWT token."""
    now     = int(time.time())
    header  = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub":  username,
        "role": role,
        "iat":  now,
        "exp":  now + _TOKEN_TTL,
    }
    h = _b64url_encode(json.dumps(header,  separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}"
    sig = hmac.new(
        _get_jwt_secret().encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def _decode_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises ValueError on any failure."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed JWT")

        h_b64, p_b64, sig_b64 = parts
        signing_input = f"{h_b64}.{p_b64}"

        # Verify signature
        expected_sig = hmac.new(
            _get_jwt_secret().encode(),
            signing_input.encode(),
            hashlib.sha256,
        ).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("Invalid JWT signature")

        payload = json.loads(_b64url_decode(p_b64))

        # Check expiry
        if payload.get("exp", 0) < int(time.time()):
            raise ValueError("JWT has expired")

        return payload

    except (ValueError, KeyError):
        raise
    except Exception as exc:
        raise ValueError(f"JWT decode error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# User store (SQLite)
# ─────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT    NOT NULL UNIQUE,
    role         TEXT    NOT NULL,
    password_hash TEXT   NOT NULL,
    salt         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    last_login   TEXT,
    created_by   TEXT    NOT NULL DEFAULT 'system',
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash     TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    role         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    created_by   TEXT    NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _bootstrap_admin() -> None:
    """Create the default admin user if no users exist yet."""
    with _conn() as c:
        c.executescript(_DDL)
        count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return  # already bootstrapped

    # First run — create default admin
    pwd_hash, salt = _hash_password(DEFAULT_ADMIN_PASSWORD)
    with _conn() as c:
        c.execute(
            """
            INSERT INTO users (username, role, password_hash, salt, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                DEFAULT_ADMIN_USERNAME,
                Role.ADMIN.value,
                pwd_hash,
                salt,
                datetime.now(timezone.utc).isoformat(),
                "system",
            ),
        )

    log.warning(
        "\n"
        "╔══════════════════════════════════════════════════════════╗\n"
        "║           DACL DEFAULT ADMIN ACCOUNT CREATED             ║\n"
        "║  Username : admin                                         ║\n"
        "║  Password : dacl-admin-2026                              ║\n"
        "║  ⚠️  Change this password immediately via:               ║\n"
        "║  POST /api/auth/change-password                          ║\n"
        "╚══════════════════════════════════════════════════════════╝"
    )


@dataclass
class UserRecord:
    id:           int
    username:     str
    role:         str
    created_at:   str
    last_login:   str | None
    created_by:   str
    is_active:    bool


def _get_user(username: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
    return dict(row) if row else None


def _get_all_users() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, username, role, created_at, last_login, created_by, is_active "
            "FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def _create_user(username: str, password: str, role: str, created_by: str) -> UserRecord:
    try:
        Role(role)  # validate role
    except ValueError:
        raise ValueError(f"Invalid role '{role}'. Must be: admin, analyst, reader")

    if _get_user(username):
        raise ValueError(f"User '{username}' already exists")

    pwd_hash, salt = _hash_password(password)
    with _conn() as c:
        c.execute(
            """
            INSERT INTO users (username, role, password_hash, salt, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username, role, pwd_hash, salt,
                datetime.now(timezone.utc).isoformat(),
                created_by,
            ),
        )
    log.info("[AUTH] User created: username=%s role=%s by=%s", username, role, created_by)
    return UserRecord(
        id=0, username=username, role=role,
        created_at=datetime.now(timezone.utc).isoformat(),
        last_login=None, created_by=created_by, is_active=True,
    )


def _update_last_login(username: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE users SET last_login = ? WHERE username = ?",
            (datetime.now(timezone.utc).isoformat(), username),
        )


def _change_password(username: str, new_password: str) -> None:
    pwd_hash, salt = _hash_password(new_password)
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
            (pwd_hash, salt, username),
        )
    log.info("[AUTH] Password changed for user '%s'", username)


def _deactivate_user(username: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET is_active = 0 WHERE username = ?", (username,))
    log.info("[AUTH] User deactivated: %s", username)


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _create_api_key(name: str, role: str, created_by: str) -> tuple[dict, str]:
    try:
        Role(role)
    except ValueError:
        raise ValueError(f"Invalid role '{role}'.")

    raw_key = "dacl-" + secrets.token_urlsafe(32)
    key_hash = _hash_api_key(raw_key)
    
    with _conn() as c:
        cursor = c.execute(
            """
            INSERT INTO api_keys (key_hash, name, role, created_at, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                key_hash, name, role,
                datetime.now(timezone.utc).isoformat(),
                created_by,
            ),
        )
        key_id = cursor.lastrowid
        
        row = c.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        
    log.info("[AUTH] API key created: name=%s role=%s by=%s", name, role, created_by)
    return dict(row), raw_key


def _get_all_api_keys() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, role, created_at, created_by FROM api_keys ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _revoke_api_key(key_id: int) -> bool:
    with _conn() as c:
        cursor = c.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        success = cursor.rowcount > 0
    if success:
        log.info("[AUTH] API key revoked: id=%d", key_id)
    return success


def get_api_key_role(raw_key: str) -> str | None:
    """Check if the provided API key exists in the DB, return its role if valid."""
    key_hash = _hash_api_key(raw_key)
    with _conn() as c:
        row = c.execute("SELECT role FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
    return row["role"] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic request/response models
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    username:     str
    role:         str
    expires_in:   int     # seconds


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role:     str   # "admin" | "analyst" | "reader"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str


class UserInfo(BaseModel):
    id:         int
    username:   str
    role:       str
    created_at: str
    last_login: str | None
    created_by: str
    is_active:  bool
    permissions: list[str]


class CreateApiKeyRequest(BaseModel):
    name: str
    role: str


class ApiKeyInfo(BaseModel):
    id:         int
    name:       str
    role:       str
    created_at: str
    created_by: str
    
class CreateApiKeyResponse(ApiKeyInfo):
    raw_key: str


# ─────────────────────────────────────────────────────────────────────────────
# Helper to resolve current user from JWT token (used by authz.py)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_token(authorization: str | None) -> dict[str, Any] | None:
    """
    Extract and validate a JWT from an Authorization: Bearer <token> header.

    Returns the decoded payload dict, or None if no/invalid token.
    Raises HTTPException(401) if the token is present but invalid/expired.
    """
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None

    token = authorization[7:].strip()
    if not token:
        return None

    try:
        return _decode_jwt(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Router — mounted at /api/auth
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    """
    Exchange username + password for a JWT access token.

    The JWT embeds your role. Include it in all subsequent requests:
      Authorization: Bearer <access_token>
    """
    user = _get_user(req.username)
    if user is None or not _verify_password(req.password, user["password_hash"], user["salt"]):
        # Same error for both "user not found" and "wrong password"
        # (prevents username enumeration)
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    _update_last_login(req.username)
    token = _issue_jwt(req.username, user["role"])

    log.info("[AUTH] Login success: username=%s role=%s", req.username, user["role"])

    return LoginResponse(
        access_token=token,
        username=req.username,
        role=user["role"],
        expires_in=_TOKEN_TTL,
    )


@router.get("/me", response_model=UserInfo)
def get_current_user_info(authorization: str | None = Header(default=None, alias="Authorization")):
    """Return the currently authenticated user's profile and permissions."""
    payload = resolve_token(authorization)
    if payload is None:
        raise HTTPException(401, "Not authenticated")

    user = _get_user(payload["sub"])
    if not user:
        raise HTTPException(401, "User account not found or deactivated.")

    role = Role(user["role"])
    return UserInfo(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        created_at=user["created_at"],
        last_login=user["last_login"],
        created_by=user["created_by"],
        is_active=bool(user["is_active"]),
        permissions=[p.value for p in ROLE_PERMISSIONS[role]],
    )


@router.post("/users", response_model=UserInfo, status_code=201)
def create_user(req: CreateUserRequest, authorization: str | None = Header(default=None, alias="Authorization")):
    """
    Create a new user account. Admin only.

    Roles:
      - admin:   full access (compile, upload, manage rules, rollback, query)
      - analyst: can add/update rules and query (no delete, no rollback)
      - reader:  read-only (list policies, query only)
    """
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can create new accounts.")

    try:
        record = _create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            created_by=payload["sub"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    role = Role(record.role)
    return UserInfo(
        id=record.id,
        username=record.username,
        role=record.role,
        created_at=record.created_at,
        last_login=None,
        created_by=record.created_by,
        is_active=True,
        permissions=[p.value for p in ROLE_PERMISSIONS[role]],
    )


@router.get("/users", response_model=list[UserInfo])
def list_users(authorization: str | None = Header(default=None, alias="Authorization")):
    """List all users. Admin only."""
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can list accounts.")

    users = _get_all_users()
    result = []
    for u in users:
        role = Role(u["role"])
        result.append(UserInfo(
            id=u["id"],
            username=u["username"],
            role=u["role"],
            created_at=u["created_at"],
            last_login=u["last_login"],
            created_by=u["created_by"],
            is_active=bool(u["is_active"]),
            permissions=[p.value for p in ROLE_PERMISSIONS[role]],
        ))
    return result


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, authorization: str | None = Header(default=None, alias="Authorization")):
    """Change your own password. Any authenticated user."""
    payload = resolve_token(authorization)
    if payload is None:
        raise HTTPException(401, "Not authenticated")

    user = _get_user(payload["sub"])
    if not user or not _verify_password(req.current_password, user["password_hash"], user["salt"]):
        raise HTTPException(401, "Current password is incorrect.")

    _change_password(payload["sub"], req.new_password)
    return {"success": True, "message": "Password changed successfully."}


@router.delete("/users/{username}")
def deactivate_user(username: str, authorization: str | None = Header(default=None, alias="Authorization")):
    """Deactivate a user account. Admin only. Cannot deactivate yourself."""
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can deactivate accounts.")

    if payload["sub"] == username:
        raise HTTPException(400, "You cannot deactivate your own account.")

    user = _get_user(username)
    if not user:
        raise HTTPException(404, f"User '{username}' not found.")

    _deactivate_user(username)
    return {"success": True, "message": f"User '{username}' has been deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# API Key Management
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/api-keys", response_model=CreateApiKeyResponse, status_code=201)
def create_api_key(req: CreateApiKeyRequest, authorization: str | None = Header(default=None, alias="Authorization")):
    """Create a new API key for external integrations. Admin only."""
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can create API keys.")

    try:
        record, raw_key = _create_api_key(
            name=req.name,
            role=req.role,
            created_by=payload["sub"],
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return CreateApiKeyResponse(
        id=record["id"],
        name=record["name"],
        role=record["role"],
        created_at=record["created_at"],
        created_by=record["created_by"],
        raw_key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyInfo])
def list_api_keys(authorization: str | None = Header(default=None, alias="Authorization")):
    """List all API keys. Admin only."""
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can list API keys.")

    keys = _get_all_api_keys()
    return [ApiKeyInfo(**k) for k in keys]


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, authorization: str | None = Header(default=None, alias="Authorization")):
    """Revoke an API key. Admin only."""
    payload = resolve_token(authorization)
    if payload is None or payload.get("role") != Role.ADMIN.value:
        raise HTTPException(403, "Only admin users can revoke API keys.")

    success = _revoke_api_key(key_id)
    if not success:
        raise HTTPException(404, f"API key with ID {key_id} not found.")

    return {"success": True, "message": "API key revoked successfully."}
