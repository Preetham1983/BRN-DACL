"""
DACL Policy Version Manager.

Provides immutable versioned storage for DACL graphs:

  compiled/
    acme_freight_v1.json       ← first compile
    acme_freight_v2.json       ← after rule update
    acme_freight.json          ← always = current active version (watched by hot-reloader)
    acme_freight_source_v1.txt ← source policy text snapshot for v1
    acme_freight_source_v2.txt ← source policy text snapshot for v2
    acme_freight_meta.json     ← version registry for this graph

Every compile, upload, or rule-edit creates a new immutable version.
Rollback restores any previous version as the active one.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dacl_agent.models.schemas import DACLGraph

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Meta schema stored in  compiled/{graph_id}_meta.json
# ─────────────────────────────────────────────────────────────────────────────


class PolicyVersionManager:
    """Manages immutable versioned DACL graph files for one compiled_dir."""

    def __init__(self, compiled_dir: str = "compiled"):
        self.compiled_dir = Path(compiled_dir)
        self.compiled_dir.mkdir(exist_ok=True)

    # ── Paths ─────────────────────────────────────────────────────────────────

    def _active_path(self, graph_id: str) -> Path:
        """Active (current) graph — watched by hot-reloader."""
        return self.compiled_dir / f"{graph_id}.json"

    def _version_path(self, graph_id: str, version: int) -> Path:
        return self.compiled_dir / f"{graph_id}_v{version}.json"

    def _source_version_path(self, graph_id: str, version: int) -> Path:
        return self.compiled_dir / f"{graph_id}_source_v{version}.txt"

    def _meta_path(self, graph_id: str) -> Path:
        return self.compiled_dir / f"{graph_id}_meta.json"

    # ── Meta helpers ──────────────────────────────────────────────────────────

    def get_meta(self, graph_id: str) -> dict[str, Any]:
        path = self._meta_path(graph_id)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"graph_id": graph_id, "current_version": 0, "versions": []}

    def _save_meta(self, graph_id: str, meta: dict[str, Any]) -> None:
        self._meta_path(graph_id).write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    def current_version(self, graph_id: str) -> int:
        return self.get_meta(graph_id).get("current_version", 0)

    def list_versions(self, graph_id: str) -> list[dict[str, Any]]:
        """Return all version entries, newest first."""
        meta = self.get_meta(graph_id)
        return list(reversed(meta.get("versions", [])))

    # ── Core operations ───────────────────────────────────────────────────────

    def save_new_version(
        self,
        graph: DACLGraph,
        source_text: str | None = None,
        changed_by: str = "system",
        change_note: str = "",
    ) -> int:
        """Persist `graph` as the next immutable version and make it active.

        Returns the new version number.
        """
        graph_id = graph.graph_id
        meta     = self.get_meta(graph_id)
        version  = meta["current_version"] + 1

        # 1. Write immutable version snapshot
        versioned_path = self._version_path(graph_id, version)
        versioned_path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")

        # 2. Write source text snapshot (if provided)
        if source_text:
            self._source_version_path(graph_id, version).write_text(
                source_text, encoding="utf-8"
            )

        # 3. Overwrite active file (hot-reloader will detect mtime change)
        shutil.copy2(versioned_path, self._active_path(graph_id))

        # 4. Update meta
        entry: dict[str, Any] = {
            "version":     version,
            "compiled_at": graph.compiled_at,
            "rule_count":  len(graph.rules),
            "description": graph.description,
            "changed_by":  changed_by,
            "change_note": change_note or f"Version {version}",
            "has_source":  source_text is not None,
        }
        meta["current_version"] = version
        meta["versions"].append(entry)
        self._save_meta(graph_id, meta)

        log.info(
            "[VERSION] '%s' v%d saved — %d rules | changed_by=%s",
            graph_id, version, len(graph.rules), changed_by,
        )
        return version

    def load_version(self, graph_id: str, version: int) -> DACLGraph:
        """Load a specific immutable version from disk."""
        path = self._version_path(graph_id, version)
        if not path.exists():
            raise FileNotFoundError(f"Version {version} not found for '{graph_id}'")
        return DACLGraph(**json.loads(path.read_text(encoding="utf-8")))

    def load_source(self, graph_id: str, version: int) -> str | None:
        """Load the source policy text for a specific version (if available)."""
        path = self._source_version_path(graph_id, version)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def rollback(
        self,
        graph_id: str,
        to_version: int,
        changed_by: str = "system",
        change_note: str = "",
    ) -> DACLGraph:
        """Restore version `to_version` as the new active version.

        Creates a NEW version entry pointing at the same rules as `to_version`.
        The rolled-back version is immutable — we don't delete anything.

        Returns the restored DACLGraph (now active).
        """
        meta = self.get_meta(graph_id)
        valid_versions = [v["version"] for v in meta["versions"]]
        if to_version not in valid_versions:
            raise ValueError(
                f"Version {to_version} does not exist for '{graph_id}'. "
                f"Available: {valid_versions}"
            )

        # Load the target version
        graph = self.load_version(graph_id, to_version)

        # Rebuild the graph with a fresh compiled_at timestamp so the
        # hot-reloader sees a genuine mtime change.
        graph_data               = graph.model_dump()
        graph_data["compiled_at"] = datetime.now(timezone.utc).isoformat()
        graph                    = DACLGraph(**graph_data)

        source_text = self.load_source(graph_id, to_version)
        note        = change_note or f"Rollback to v{to_version}"

        self.save_new_version(
            graph, source_text=source_text,
            changed_by=changed_by, change_note=note,
        )
        return graph

    def get_diff(self, graph_id: str, v_old: int, v_new: int) -> dict[str, Any]:
        """Compute a structural diff between two versions.

        Returns:
          {
            "added":   [rule_id, ...],
            "removed": [rule_id, ...],
            "changed": [{"rule_id": ..., "fields_changed": [...]}],
          }
        """
        old_graph = self.load_version(graph_id, v_old)
        new_graph = self.load_version(graph_id, v_new)

        old_rules = {r.rule_id: r for r in old_graph.rules}
        new_rules = {r.rule_id: r for r in new_graph.rules}

        added   = [rid for rid in new_rules if rid not in old_rules]
        removed = [rid for rid in old_rules if rid not in new_rules]
        changed = []

        for rid in old_rules:
            if rid not in new_rules:
                continue
            old_r = old_rules[rid].model_dump()
            new_r = new_rules[rid].model_dump()
            diff_fields = [k for k in old_r if old_r.get(k) != new_r.get(k)]
            if diff_fields:
                changed.append({"rule_id": rid, "fields_changed": diff_fields})

        return {
            "graph_id":  graph_id,
            "from_version": v_old,
            "to_version":   v_new,
            "added":   added,
            "removed": removed,
            "changed": changed,
            "total_changes": len(added) + len(removed) + len(changed),
        }

    def delete_policy(self, graph_id: str) -> None:
        """Completely remove all files associated with a policy graph_id."""
        paths = [
            self._active_path(graph_id),
            self._meta_path(graph_id)
        ]
        
        # Add all versioned files
        meta = self.get_meta(graph_id)
        for entry in meta.get("versions", []):
            v = entry["version"]
            paths.append(self._version_path(graph_id, v))
            if entry.get("has_source"):
                paths.append(self._source_version_path(graph_id, v))
                
        # Also clean up _source.txt if exists
        paths.append(self.compiled_dir / f"{graph_id}_source.txt")
                
        deleted = 0
        for path in paths:
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except OSError as e:
                    log.warning(f"Failed to delete {path}: {e}")
                    
        log.info(f"[VERSION] Deleted policy '{graph_id}' ({deleted} files removed)")
