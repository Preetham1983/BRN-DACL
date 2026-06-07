"""
DACL OPA-style Authorization Gate.

Implements Policy-as-Code following Open Policy Agent (OPA) principles.
The authorization policies are defined in policies/authz.rego (Rego syntax)
for documentation and future OPA sidecar deployment.
This Python engine evaluates the same policies inline at runtime.

Architecture:
  ┌─────────────────────────────────────────────────────────────────────┐
  │  HTTP Request  →  X-API-Key header                                  │
  │       ↓                                                             │
  │  OPAGate.authorize(api_key, required_permission)                    │
  │       ↓                                                             │
  │  1. Resolve api_key → Role  (from DACL_API_KEYS env var)           │
  │  2. Evaluate policy rules   (ROLE_PERMISSIONS mapping)              │
  │  3. Allow or raise HTTP 403                                         │
  └─────────────────────────────────────────────────────────────────────┘

Roles:
  admin:    all permissions (compile, upload, add/update/delete rules, rollback, query)
  analyst:  can add rules + query (no delete, no rollback)
  reader:   read-only (query only, list policies)

Configuration (.env):
  DACL_API_KEYS=admin:sk-admin-secret,analyst:sk-analyst-key,reader:sk-reader-key
  DACL_OPEN_MODE=false   (set to true to disable auth — dev only)
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import HTTPException, Security, Header
from fastapi.security import APIKeyHeader

load_dotenv()
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Roles & Permissions
# ─────────────────────────────────────────────────────────────────────────────

class Role(str, Enum):
    ADMIN   = "admin"
    ANALYST = "analyst"
    READER  = "reader"


class Permission(str, Enum):
    COMPILE      = "compile"       # POST /api/compile
    UPLOAD       = "upload"        # POST /api/upload
    ADD_RULE     = "add_rule"      # POST /api/rules/{graph_id}
    UPDATE_RULE  = "update_rule"   # PUT  /api/rules/{graph_id}/{rule_id}
    DELETE_RULE  = "delete_rule"   # DELETE /api/rules/{graph_id}/{rule_id}
    ROLLBACK     = "rollback"      # POST /api/rollback/{graph_id}
    QUERY        = "query"         # POST /api/query  /api/query-doc
    READ         = "read"          # GET  /api/rules, /api/versions, /api/policies


# Policy-as-Code: role → permitted actions (mirrors authz.rego)
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),      # all permissions
    Role.ANALYST: frozenset({
        Permission.READ,
        Permission.QUERY,
        Permission.ADD_RULE,
        Permission.UPDATE_RULE,
        Permission.COMPILE,
    }),
    Role.READER: frozenset({
        Permission.READ,
        Permission.QUERY,
    }),
}


# ─────────────────────────────────────────────────────────────────────────────
# API Key store (loaded from env)
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_api_keys() -> dict[str, Role]:
    """Parse DACL_API_KEYS env var into a dict of {key → role}.

    Format: "admin:sk-admin,analyst:sk-analyst,reader:sk-reader"
    Multiple keys per role: "admin:key1,admin:key2,analyst:key3"
    """
    raw = os.getenv("DACL_API_KEYS", "")
    if not raw.strip():
        if not _open_mode():
            log.warning(
                "[AUTHZ] DACL_API_KEYS not set — all auth checks will be skipped. "
                "Set DACL_OPEN_MODE=true to suppress this warning."
            )
        return {}

    key_map: dict[str, Role] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        role_str, api_key = entry.split(":", 1)
        role_str = role_str.strip().lower()
        api_key  = api_key.strip()
        try:
            key_map[api_key] = Role(role_str)
        except ValueError:
            log.warning("[AUTHZ] Unknown role '%s' in DACL_API_KEYS — skipped", role_str)

    log.info("[AUTHZ] Loaded %d API keys", len(key_map))
    return key_map


def _open_mode() -> bool:
    """If true, skip all auth checks (dev/demo mode only)."""
    return os.getenv("DACL_OPEN_MODE", "false").lower() in ("true", "1", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# OPA Gate
# ─────────────────────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class OPAGate:
    """
    Inline OPA-style policy evaluator.

    Evaluates the same policies as policies/authz.rego but in Python,
    so no external OPA sidecar is needed for the current single-node deployment.
    For distributed/enterprise deployment, replace this class with an HTTP call
    to an OPA server: POST http://opa:8181/v1/data/dacl/authz/allow
    """

    def authorize(self, api_key: str | None, authorization: str | None, permission: Permission) -> Role:
        """
        Evaluate the authorization policy.

        Args:
            api_key:       Value from X-API-Key header (may be None)
            authorization: Value from Authorization header (JWT)
            permission:    The required permission for this endpoint

        Returns:
            The caller's Role if authorized.

        Raises:
            HTTPException(401) if no valid credentials provided
            HTTPException(403) if role lacks the required permission
        """
        if _open_mode():
            return Role.ADMIN  # dev mode — grant admin to everyone

        # ── 1. Try JWT Auth first ────────────────────────────────────────────
        if authorization:
            from auth import resolve_token
            try:
                payload = resolve_token(authorization)
                if payload:
                    role_str = payload.get("role")
                    if role_str:
                        role = Role(role_str)
                        if permission not in ROLE_PERMISSIONS[role]:
                            log.warning("[AUTHZ] JWT DENIED role=%s permission=%s", role.value, permission.value)
                            raise HTTPException(
                                status_code=403,
                                detail=(
                                    f"Role '{role.value}' does not have '{permission.value}' permission. "
                                    f"Contact your administrator."
                                ),
                            )
                        log.debug("[AUTHZ] JWT ALLOWED role=%s permission=%s", role.value, permission.value)
                        return role
            except HTTPException:
                raise  # re-raise 401/403 from resolve_token
            except Exception as e:
                raise HTTPException(401, f"Invalid JWT: {e}")

        # ── 2. Fallback to API Key ───────────────────────────────────────────
        if not api_key:
            # Maybe there are no env keys configured and no DB keys, but we just check if api_key is missing
            raise HTTPException(
                status_code=401,
                detail=(
                    "Missing Authorization or X-API-Key header. "
                    "Please log in or provide an API key."
                ),
            )

        # Check DB first
        from auth import get_api_key_role
        try:
            role_str = get_api_key_role(api_key)
            if role_str:
                role = Role(role_str)
            else:
                role = None
        except Exception as exc:
            log.error("Failed to fetch API key from DB: %s", exc)
            role = None

        # Fallback to env var keys
        if role is None:
            key_map = _load_api_keys()
            role = key_map.get(api_key)

        if role is None:
            log.warning("[AUTHZ] Invalid API key attempt: %s...", api_key[:8] if api_key else "None")
            raise HTTPException(
                status_code=401,
                detail="Invalid API key.",
            )

        if permission not in ROLE_PERMISSIONS[role]:
            log.warning(
                "[AUTHZ] DENIED role=%s permission=%s", role.value, permission.value
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Role '{role.value}' does not have '{permission.value}' permission. "
                    f"Contact your administrator."
                ),
            )

        log.debug("[AUTHZ] ALLOWED role=%s permission=%s", role.value, permission.value)
        return role


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI dependency factories — inject into endpoint signatures
# ─────────────────────────────────────────────────────────────────────────────

_gate = OPAGate()


def _make_dep(permission: Permission):
    """Return a FastAPI Depends-compatible function for the given permission."""

    async def _dep(
        api_key: str | None = Security(_api_key_header),
        authorization: str | None = Header(default=None, alias="Authorization")
    ) -> Role:
        return _gate.authorize(api_key, authorization, permission)

    _dep.__name__ = f"require_{permission.value}"
    return _dep


# Pre-built dependency functions — import and use with Depends()
require_read        = _make_dep(Permission.READ)
require_query       = _make_dep(Permission.QUERY)
require_compile     = _make_dep(Permission.COMPILE)
require_upload      = _make_dep(Permission.UPLOAD)
require_add_rule    = _make_dep(Permission.ADD_RULE)
require_update_rule = _make_dep(Permission.UPDATE_RULE)
require_delete_rule = _make_dep(Permission.DELETE_RULE)
require_rollback    = _make_dep(Permission.ROLLBACK)
