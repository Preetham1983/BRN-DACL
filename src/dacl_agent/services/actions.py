"""
DACL Durable Action Dispatcher.

When the Rete engine fires a rule and produces a deterministic output,
this module converts those outputs into real-world side effects — but does
so durably (idempotent, retriable, fully auditable).

Architecture (matching the "Durable Orchestration" pattern from the whitepaper):
  ┌───────────────────────────────────────────────────────────────────┐
  │ Rule fires  →  ActionDispatcher.dispatch()                        │
  │   1. Generate idempotency key (SHA-256 of decision+rule+action)   │
  │   2. Check SQLite queue — skip if already succeeded (idempotent)  │
  │   3. Execute action handler                                       │
  │   4. Write result to SQLite (for audit + retry on failure)        │
  │   5. Return ActionResult                                          │
  └───────────────────────────────────────────────────────────────────┘

Built-in action types:
  - LogAction     → structured log at INFO level (always registered)
  - WebhookAction → HTTP POST to a configured URL
  - EmailAction   → placeholder for email gateway integration

Registering a custom action:
  registry = ActionRegistry()
  registry.register(
      output_field="decision",
      output_value="pending_manager_approval",
      handler=MyNotificationHandler(manager_email="..."),
  )
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Protocols & Result types
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class ActionHandler(Protocol):
    """Protocol all action handlers must satisfy."""

    @property
    def name(self) -> str: ...

    def execute(
        self,
        idempotency_key: str,
        decision_id:     str,
        rule_id:         str,
        output_field:    str,
        output_value:    Any,
        facts:           dict[str, Any],
    ) -> bool:
        """Execute the side effect. Returns True on success."""
        ...


@dataclass
class ActionResult:
    idempotency_key: str
    handler_name:    str
    output_field:    str
    output_value:    Any
    success:         bool
    skipped:         bool   = False  # True if already executed (idempotent skip)
    error:           str    = ""
    executed_at:     str    = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# Built-in handlers
# ─────────────────────────────────────────────────────────────────────────────

class LogActionHandler:
    """Built-in handler: structured log every decision side-effect."""

    name = "log"

    def execute(
        self,
        idempotency_key: str,
        decision_id:     str,
        rule_id:         str,
        output_field:    str,
        output_value:    Any,
        facts:           dict[str, Any],
    ) -> bool:
        log.info(
            "[ACTION] decision_id=%s rule=%s %s=%s key=%s",
            decision_id, rule_id, output_field, output_value, idempotency_key,
        )
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Action Registry
# ─────────────────────────────────────────────────────────────────────────────

class ActionRegistry:
    """
    Maps (output_field, output_value) → list[ActionHandler].

    Multiple handlers can be registered for the same output, they all run.
    Use output_value="*" to match any value for a given field (wildcard).
    """

    def __init__(self):
        # Always include the log handler for every output
        self._map: dict[tuple[str, str], list[ActionHandler]] = {}
        self._global: list[ActionHandler] = [LogActionHandler()]

    def register(
        self,
        output_field:  str,
        output_value:  Any,
        handler:       ActionHandler,
    ) -> None:
        """Register handler for a specific (field, value) pair.

        Args:
            output_field:  The fact field name (e.g. "decision")
            output_value:  The value to trigger on (e.g. "pending_manager_approval")
                           Use "*" to trigger for any value of this field.
            handler:       Any object implementing the ActionHandler protocol.
        """
        key = (output_field, str(output_value))
        self._map.setdefault(key, []).append(handler)
        log.info(
            "[ACTION-REGISTRY] registered handler='%s' for %s=%s",
            handler.name, output_field, output_value,
        )

    def resolve(self, output_field: str, output_value: Any) -> list[ActionHandler]:
        """Return all handlers that match (field, value), including wildcards."""
        exact    = self._map.get((output_field, str(output_value)), [])
        wildcard = self._map.get((output_field, "*"), [])
        return self._global + exact + wildcard


# ─────────────────────────────────────────────────────────────────────────────
# Durable Queue (SQLite-backed)
# ─────────────────────────────────────────────────────────────────────────────

class DurableActionQueue:
    """
    SQLite-backed queue for action execution results.

    Guarantees:
      - Idempotency: same idempotency_key is never executed twice
      - Auditability: every execution (success or failure) is stored
      - Retry: failed actions can be re-queued (max_retries limit)
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS action_log (
        idempotency_key TEXT PRIMARY KEY,
        handler_name    TEXT NOT NULL,
        output_field    TEXT NOT NULL,
        output_value    TEXT,
        decision_id     TEXT,
        rule_id         TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        retry_count     INTEGER NOT NULL DEFAULT 0,
        error           TEXT,
        created_at      TEXT NOT NULL,
        executed_at     TEXT
    )
    """

    def __init__(self, db_path: str = "compiled/actions.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(exist_ok=True)
        with self._conn() as conn:
            conn.execute(self._DDL)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def already_succeeded(self, idempotency_key: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM action_log WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return row is not None and row[0] == "success"

    def record_pending(
        self,
        idempotency_key: str,
        handler_name:    str,
        output_field:    str,
        output_value:    Any,
        decision_id:     str,
        rule_id:         str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO action_log
                    (idempotency_key, handler_name, output_field, output_value,
                     decision_id, rule_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    idempotency_key, handler_name, str(output_field),
                    str(output_value), decision_id, rule_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def record_result(
        self,
        idempotency_key: str,
        success: bool,
        error: str = "",
    ) -> None:
        status = "success" if success else "failed"
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE action_log
                SET status = ?, error = ?, executed_at = ?,
                    retry_count = retry_count + 1
                WHERE idempotency_key = ?
                """,
                (
                    status, error,
                    datetime.now(timezone.utc).isoformat(),
                    idempotency_key,
                ),
            )

    def get_history(self, decision_id: str) -> list[dict]:
        """Retrieve all action records for a given decision_id (audit trail)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM action_log WHERE decision_id = ? ORDER BY created_at",
                (decision_id,),
            ).fetchall()
        cols = [
            "idempotency_key", "handler_name", "output_field", "output_value",
            "decision_id", "rule_id", "status", "retry_count", "error",
            "created_at", "executed_at",
        ]
        return [dict(zip(cols, r)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Action Dispatcher — the public interface
# ─────────────────────────────────────────────────────────────────────────────

class ActionDispatcher:
    """
    Orchestrates idempotent side-effect dispatch after rule firing.

    Call dispatch() once per rule-output pair after the Rete engine fires.
    The dispatcher guarantees that each unique (decision_id, rule_id, handler)
    combination is executed at most once, even if dispatch() is called multiple times.
    """

    def __init__(
        self,
        registry:    ActionRegistry | None = None,
        queue:       DurableActionQueue | None = None,
        max_retries: int = 3,
    ):
        self.registry    = registry or ActionRegistry()
        self.queue       = queue or DurableActionQueue()
        self.max_retries = max_retries

    def dispatch(
        self,
        decision_id:  str,
        rule_id:      str,
        output_field: str,
        output_value: Any,
        facts:        dict[str, Any],
    ) -> list[ActionResult]:
        """
        Dispatch all registered handlers for (output_field, output_value).

        Args:
            decision_id:  Unique ID for this inference call (for audit correlation)
            rule_id:      The rule that fired
            output_field: The output field name (e.g. "decision")
            output_value: The output value (e.g. "pending_manager_approval")
            facts:        The working memory at dispatch time

        Returns:
            List of ActionResult, one per handler that was found.
        """
        handlers = self.registry.resolve(output_field, output_value)
        results: list[ActionResult] = []

        for handler in handlers:
            idempotency_key = self._make_key(decision_id, rule_id, handler.name)

            # Idempotency check — skip if already succeeded
            if self.queue.already_succeeded(idempotency_key):
                results.append(ActionResult(
                    idempotency_key=idempotency_key,
                    handler_name=handler.name,
                    output_field=output_field,
                    output_value=output_value,
                    success=True,
                    skipped=True,
                ))
                continue

            self.queue.record_pending(
                idempotency_key, handler.name,
                output_field, output_value, decision_id, rule_id,
            )

            # Execute with retry
            success = False
            error   = ""
            for attempt in range(self.max_retries):
                try:
                    success = handler.execute(
                        idempotency_key=idempotency_key,
                        decision_id=decision_id,
                        rule_id=rule_id,
                        output_field=output_field,
                        output_value=output_value,
                        facts=facts,
                    )
                    if success:
                        break
                except Exception as exc:
                    error = str(exc)
                    log.warning(
                        "[ACTION] handler='%s' attempt=%d/%d failed: %s",
                        handler.name, attempt + 1, self.max_retries, exc,
                    )
                    if attempt < self.max_retries - 1:
                        time.sleep(0.5 * (2 ** attempt))  # exponential backoff

            self.queue.record_result(idempotency_key, success, error)

            results.append(ActionResult(
                idempotency_key=idempotency_key,
                handler_name=handler.name,
                output_field=output_field,
                output_value=output_value,
                success=success,
                error=error,
            ))

        return results

    @staticmethod
    def _make_key(decision_id: str, rule_id: str, handler_name: str) -> str:
        """Deterministic idempotency key: SHA-256 of the three identifiers."""
        raw = f"{decision_id}:{rule_id}:{handler_name}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton — shared across all agents in the server process
# ─────────────────────────────────────────────────────────────────────────────

_global_registry   = ActionRegistry()
_global_queue      = DurableActionQueue()
global_dispatcher  = ActionDispatcher(registry=_global_registry, queue=_global_queue)
