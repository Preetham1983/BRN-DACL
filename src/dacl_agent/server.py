"""
DACL FastAPI Backend — Multi-Tenant, Multi-Domain, PDF-Upload edition.

Architecture:
  ┌──────────────────────────────────────────────────────────────────────────┐
  │  COMPILE TIME (once per policy)                                          │
  │    POST /api/upload         ← PDF / TXT from ANY company                │
  │    POST /api/compile        ← re/compile built-in or uploaded policy    │
  │                                                                          │
  │  RULE MANAGEMENT (org self-service — no re-upload needed)               │
  │    GET    /api/rules/{graph_id}            ← list all rules             │
  │    POST   /api/rules/{graph_id}            ← add a new rule             │
  │    PUT    /api/rules/{graph_id}/{rule_id}  ← update a specific rule     │
  │    DELETE /api/rules/{graph_id}/{rule_id}  ← delete a rule              │
  │                                                                          │
  │  VERSION MANAGEMENT                                                      │
  │    GET  /api/versions/{graph_id}              ← list all versions       │
  │    GET  /api/versions/{graph_id}/{v1}/diff/{v2} ← diff two versions     │
  │    POST /api/rollback/{graph_id}              ← rollback to version N   │
  │                                                                          │
  │  INFERENCE TIME (every query)                                            │
  │    POST /api/query      ← natural-language text query                   │
  │    POST /api/query-doc  ← PDF / TXT case document                       │
  └──────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dacl_agent.core import auth
from dacl_agent.services.agent import DACLAgent
from dacl_agent.services.actions import global_dispatcher
from dacl_agent.core.authz import (
    Role,
    require_compile,
    require_delete_rule,
    require_add_rule,
    require_read,
    require_rollback,
    require_update_rule,
    require_upload,
    require_query,
)
from dacl_agent.services.compiler import compile_policy
from dacl_agent.services.engine import DACLReteEngine
from dacl_agent.services.extractor import MAX_CHARS_FACTS, extract_text
from dacl_agent.models.schemas import Condition, ActionFormula, DACLGraph, DACLRule, DACLResponse
from dacl_agent.services.versioning import PolicyVersionManager

_versions = PolicyVersionManager("compiled")


# ─────────────────────────────────────────────────────────────────────────────
# LRU Agent Cache — bounded to avoid unbounded memory growth
# ─────────────────────────────────────────────────────────────────────────────
class _LRUAgentCache:
    """Thread-safe LRU cache for DACLAgent instances.

    Evicts the least-recently-used agent when the capacity is exceeded,
    releasing its DACLReteEngine (alpha network) from RAM automatically.
    """

    def __init__(self, capacity: int = 50):
        self._capacity = capacity
        self._cache: OrderedDict[str, DACLAgent] = OrderedDict()
        self._lock  = threading.Lock()

    def get(self, key: str) -> DACLAgent | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)   # mark as recently used
            return self._cache[key]

    def put(self, key: str, agent: DACLAgent) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = agent
            if len(self._cache) > self._capacity:
                evicted_key, _ = self._cache.popitem(last=False)
                print(f"[AGENT-CACHE] Evicted least-used agent: '{evicted_key}'")

    def update_engine(self, key: str, graph: DACLGraph, engine) -> bool:
        with self._lock:
            if key not in self._cache:
                return False
            self._cache[key].graph  = graph
            self._cache[key].engine = engine
            return True

    def __contains__(self, key: str) -> bool:
        return key in self._cache


_agents = _LRUAgentCache(capacity=50)


# ─────────────────────────────────────────────────────────────────────────────
# Hot-Reload File Watcher
# ─────────────────────────────────────────────────────────────────────────────
class GraphHotReloader(threading.Thread):
    """Background daemon that polls compiled/*.json for mtime changes.

    When a graph JSON is modified on disk (e.g. after an external recompile
    or a CI/CD push), the RETE network is rebuilt in-place — no restart needed.
    """

    def __init__(self, compiled_dir: str = "compiled", poll_interval: float = 2.0):
        super().__init__(daemon=True)
        self.compiled_dir  = Path(compiled_dir)
        self.poll_interval = poll_interval
        self._mtimes: dict[str, float] = {}
        self._lock = threading.Lock()

    def run(self) -> None:
        print(f"[HOT-RELOAD] Watcher started — monitoring compiled/*.json "
              f"every {self.poll_interval}s")
        self._seed()
        while True:
            time.sleep(self.poll_interval)
            try:
                self._scan()
            except Exception as exc:
                print(f"[HOT-RELOAD] Scan error: {exc}")

    def _seed(self) -> None:
        if not self.compiled_dir.exists():
            return
        for path in self.compiled_dir.glob("*.json"):
            if not path.stem.endswith("_source"):
                try:
                    self._mtimes[path.stem] = path.stat().st_mtime
                except OSError:
                    pass

    def _scan(self) -> None:
        if not self.compiled_dir.exists():
            return
        for path in self.compiled_dir.glob("*.json"):
            graph_id = path.stem
            if graph_id.endswith("_source"):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            prev = self._mtimes.get(graph_id)
            if prev is None:
                self._mtimes[graph_id] = mtime
            elif mtime != prev:
                self._mtimes[graph_id] = mtime
                self._reload(graph_id, path)

    def _reload(self, graph_id: str, path: Path) -> None:
        try:
            from engine import DACLReteEngine
            raw        = json.loads(path.read_text(encoding="utf-8"))
            new_graph  = DACLGraph.model_validate(raw)
            new_engine = DACLReteEngine(new_graph)
            updated = _agents.update_engine(graph_id, new_graph, new_engine)
            if updated:
                if graph_id in _registry:
                    _registry[graph_id]["rule_count"]  = len(new_graph.rules)
                    _registry[graph_id]["compiled_at"] = new_graph.compiled_at
                print(f"[HOT-RELOAD] '{graph_id}' reloaded — {len(new_graph.rules)} rules")
        except Exception as exc:
            print(f"[HOT-RELOAD] Failed to reload '{graph_id}': {exc}")

    def trigger(self, graph_id: str) -> bool:
        path = self.compiled_dir / f"{graph_id}.json"
        if not path.exists():
            return False
        self._reload(graph_id, path)
        return True


_hot_reloader: GraphHotReloader | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _hot_reloader
    auth._bootstrap_admin()  # Ensure default admin exists
    _hot_reloader = GraphHotReloader("compiled")
    _hot_reloader.start()
    yield
    # Daemon thread exits automatically with the process


app = FastAPI(title="DACL Agent API", version="2.2.0", lifespan=lifespan)
app.include_router(auth.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Built-in Policies
# ─────────────────────────────────────────────────────────────────────────────
FREIGHT_POLICY = """
FREIGHT PRICING POLICY v2.3 - Effective 2026-01-01 to 2026-12-31

TIER CLASSIFICATION RULES:
--------------------------
Rule 1 (Tier A - Premium):
  IF weight > 1.0 kg AND distance > 500 km
  THEN tier = "A", apply premium surcharge.
  Formula: base_rate = 5.50 + (fuel_index - 4.00) * 0.30
  final_amount = base_rate * distance * weight
  Source: Section 3.1 - Premium Freight Schedule

Rule 2 (Tier B - Standard Heavy):
  IF weight > 0.5 kg AND distance > 300 km
  THEN tier = "B", apply standard fuel surcharge.
  Formula: base_rate = 4.10 + (fuel_index - 4.10) * 0.22
  final_amount = base_rate * distance * weight
  Source: Section 3.2 - Standard Freight Schedule

Rule 3 (Tier C - Economy):
  IF weight <= 0.5 kg OR distance <= 300 km
  THEN tier = "C", apply economy rate.
  Formula: base_rate = 2.80
  final_amount = base_rate * distance * weight
  Source: Section 3.3 - Economy Freight Schedule

DEFAULT: If no rule matches, apply economy rate (Section 3.3).
"""

HR_LEAVE_POLICY = """
HR LEAVE APPROVAL POLICY - Version 1.5

LEAVE APPROVAL RULES:
--------------------
Rule 1 (Auto-Approve Short Leave):
  IF leave_days <= 2 AND tenure_years >= 1
  THEN decision = "auto_approved"
  Source: HR Policy 2.1 - Short Leave Entitlement

Rule 2 (Manager Approval Required):
  IF leave_days > 2 AND leave_days <= 10
  THEN decision = "pending_manager_approval"
  Source: HR Policy 2.2 - Standard Leave Approval

Rule 3 (HR Director Approval Required):
  IF leave_days > 10
  THEN decision = "pending_hr_director_approval"
  Source: HR Policy 2.3 - Extended Leave Approval

Rule 4 (Probation Block):
  IF tenure_years < 1
  THEN decision = "blocked_probation"
  Source: HR Policy 3.1 - Probation Period Restrictions

DEFAULT: Apply standard leave flow with manager notification.
"""

INSURANCE_POLICY = """
INSURANCE PREMIUM CALCULATION POLICY - v3.0

PREMIUM TIER RULES:
-------------------
Rule 1 (High Risk - Age > 60):
  IF age > 60 AND bmi > 30
  THEN risk_tier = "high", premium_rate = 0.08
  Formula: annual_premium = coverage_amount * premium_rate
  Source: Underwriting Guide Section 5.1 - High Risk Profile

Rule 2 (Medium Risk - Age 40-60):
  IF age >= 40 AND age <= 60
  THEN risk_tier = "medium", premium_rate = 0.045
  Formula: annual_premium = coverage_amount * premium_rate
  Source: Underwriting Guide Section 5.2 - Medium Risk Profile

Rule 3 (Low Risk - Young Adults):
  IF age < 40 AND bmi <= 25
  THEN risk_tier = "low", premium_rate = 0.02
  Formula: annual_premium = coverage_amount * premium_rate
  Source: Underwriting Guide Section 5.3 - Low Risk Profile

DEFAULT: Apply standard rate of 5%.
"""

# Built-in policy registry (key alias → metadata)
BUILTIN_POLICIES: dict[str, dict] = {
    "freight": {
        "text":     FREIGHT_POLICY,
        "domain":   "freight_pricing",
        "graph_id": "freight_policy_graph",
    },
    "hr": {
        "text":     HR_LEAVE_POLICY,
        "domain":   "hr_leave_policy",
        "graph_id": "hr_policy_graph",
    },
    "insurance": {
        "text":     INSURANCE_POLICY,
        "domain":   "insurance_pricing",
        "graph_id": "insurance_policy_graph",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic Policy Registry  (built-ins + every uploaded policy)
# ─────────────────────────────────────────────────────────────────────────────
# {graph_id → {company, domain, graph_id, description, rule_count, is_builtin}}
_registry: dict[str, dict] = {}


def _init_registry() -> None:
    """Populate registry from built-in policies and any pre-compiled JSON files."""
    for key, meta in BUILTIN_POLICIES.items():
        _registry[meta["graph_id"]] = {
            "key":         key,
            "company":     "default",
            "domain":      meta["domain"],
            "graph_id":    meta["graph_id"],
            "description": f"Built-in {meta['domain']} policy",
            "rule_count":  None,
            "compiled_at": None,
            "is_builtin":  True,
        }

    compiled = Path("compiled")
    if compiled.exists():
        for f in compiled.glob("*.json"):
            if f.stem.endswith("_source"):
                continue
            try:
                data = json.loads(f.read_text())
                gid  = data.get("graph_id", f.stem)
                if gid not in _registry:
                    _registry[gid] = {
                        "key":         gid,
                        "company":     data.get("company", "default"),
                        "domain":      data.get("domain", "unknown"),
                        "graph_id":    gid,
                        "description": data.get("description", ""),
                        "rule_count":  len(data.get("rules", [])),
                        "compiled_at": data.get("compiled_at", ""),
                        "is_builtin":  False,
                    }
            except Exception:
                pass


_init_registry()


def _resolve_graph_id(domain_or_graph_id: str) -> str:
    """Resolve a built-in key alias OR raw graph_id to a canonical graph_id."""
    if domain_or_graph_id in BUILTIN_POLICIES:
        return BUILTIN_POLICIES[domain_or_graph_id]["graph_id"]
    if domain_or_graph_id in _registry:
        return domain_or_graph_id
    raise HTTPException(404, f"Unknown domain/policy: '{domain_or_graph_id}'")


def _get_agent(domain_or_graph_id: str) -> DACLAgent:
    graph_id = _resolve_graph_id(domain_or_graph_id)
    agent = _agents.get(graph_id)
    if agent is None:
        meta  = _registry[graph_id]
        agent = DACLAgent(
            graph_id=graph_id,
            domain=meta["domain"],
            compiled_dir="compiled",
        )
        _agents.put(graph_id, agent)
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# Request Models
# ─────────────────────────────────────────────────────────────────────────────
class CompileRequest(BaseModel):
    domain:          str            # built-in key ("freight") OR graph_id
    force_recompile: bool = False
    strict_verify:   bool = False   # raise error on Z3 conflict (default: warn only)


class QueryRequest(BaseModel):
    domain: str            # built-in key OR graph_id
    query: str


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/policies")
def list_policies(company: str | None = None):
    """List all available policies. Optionally filter by company."""
    policies = list(_registry.values())
    if company:
        policies = [p for p in policies if p.get("company") == company]
    return {"policies": policies}


@app.get("/api/domains")
def list_domains():
    """Backward-compatible endpoint — returns built-in domains only."""
    return {
        "domains": [
            {"key": k, "domain": v["domain"], "graph_id": v["graph_id"]}
            for k, v in BUILTIN_POLICIES.items()
        ]
    }


@app.get("/api/policy/{domain_key}")
def get_policy(domain_key: str):
    if domain_key not in BUILTIN_POLICIES:
        raise HTTPException(404, f"No built-in policy text for: {domain_key}")
    return {
        "domain_key":  domain_key,
        "policy_text": BUILTIN_POLICIES[domain_key]["text"],
    }


@app.post("/api/compile")
def compile_domain(
    req:  CompileRequest,
    role: Role = Depends(require_compile),
):
    """Compile a policy to a DACL graph (requires compile permission)."""
    graph_id = _resolve_graph_id(req.domain)
    meta     = _registry[graph_id]

    if meta["is_builtin"]:
        policy_text: str | None = BUILTIN_POLICIES[meta["key"]]["text"]
    else:
        source_path = Path(f"compiled/{graph_id}_source.txt")
        policy_text = source_path.read_text(encoding="utf-8") if source_path.exists() else None

    agent = _get_agent(req.domain)

    try:
        if policy_text is None:
            agent.load_precompiled()
            graph = agent.graph
            verification = None
        else:
            graph = agent.compile(
                policy_text,
                force=req.force_recompile,
                strict_verify=req.strict_verify,
            )
            verification = agent.verification
    except FileNotFoundError:
        raise HTTPException(400, "Policy not yet compiled — upload it first.")
    except ValueError as exc:          # raised by strict_verify
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, str(exc))

    _registry[graph_id]["rule_count"]  = len(graph.rules)
    _registry[graph_id]["compiled_at"] = graph.compiled_at

    return {
        "success":      True,
        "graph":        graph.model_dump(),
        "from_cache":   not req.force_recompile,
        "verification": verification.to_dict() if verification else None,
    }


@app.get("/api/graph/{domain_key}")
def get_graph(domain_key: str):
    """Return the compiled DACL graph JSON."""
    try:
        graph_id = _resolve_graph_id(domain_key)
    except HTTPException:
        return {"compiled": False}

    graph_path = Path(f"compiled/{graph_id}.json")
    if not graph_path.exists():
        return {"compiled": False}

    data = json.loads(graph_path.read_text())
    stat = graph_path.stat()
    return {
        "compiled":        True,
        "graph":           data,
        "graph_path":      f"compiled/{graph_id}.json",
        "file_size_kb":    round(stat.st_size / 1024, 1),
        "file_size_bytes": stat.st_size,
    }


@app.post("/api/query")
def run_query(
    req:  QueryRequest,
    role: Role = Depends(require_query),
):
    """Natural-language text query (requires query permission)."""
    agent = _get_agent(req.domain)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet. Call /api/compile first.")
    try:
        return agent.query(req.query).model_dump()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/upload")
async def upload_policy(
    company:        str        = Form(...),
    domain:         str        = Form(...),
    description:    str        = Form(""),
    force:          bool       = Form(False),
    strict_verify:  bool       = Form(False),
    changed_by:     str        = Form("admin"),
    change_note:    str        = Form(""),
    file:           UploadFile = File(...),
    role:           Role       = Depends(require_upload),
):
    """Upload a business policy document — requires upload permission."""
    content = await file.read()
    try:
        policy_text = extract_text(content, file.filename or "", file.content_type or "")
    except Exception as exc:
        raise HTTPException(422, f"Could not extract text from file: {exc}")

    if not policy_text.strip():
        raise HTTPException(422, "Extracted text is empty — check your file.")

    company_slug = re.sub(r"[^a-z0-9]+", "_", company.lower()).strip("_")
    domain_slug  = re.sub(r"[^a-z0-9]+", "_", domain.lower()).strip("_")
    graph_id     = f"{company_slug}_{domain_slug}"

    # Check if exists and force is False (don't silently skip)
    existing_version = _versions.current_version(graph_id)
    if existing_version > 0 and not force:
        raise HTTPException(
            409,
            f"Policy '{graph_id}' already has {existing_version} version(s). "
            "Set force=true to compile a new version from this document."
        )

    try:
        graph, verification = compile_policy(policy_text, graph_id, domain, strict_verify=strict_verify)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"LLM compilation failed: {exc}")

    # Patch company + description before saving
    graph_data                = graph.model_dump()
    graph_data["company"]     = company
    graph_data["description"] = description or graph.description
    graph = DACLGraph(**graph_data)

    new_version = _versions.save_new_version(
        graph,
        source_text=policy_text,
        changed_by=changed_by,
        change_note=change_note or "Initial upload" if existing_version == 0 else "Policy update",
    )

    # Build and cache the agent with the new engine
    from engine import DACLReteEngine
    agent        = DACLAgent(graph_id=graph_id, domain=domain, compiled_dir="compiled")
    agent.graph  = graph
    agent.engine = DACLReteEngine(graph)

    _registry[graph_id] = {
        "key":         graph_id,
        "company":     company,
        "domain":      domain,
        "graph_id":    graph_id,
        "description": graph.description,
        "rule_count":  len(graph.rules),
        "compiled_at": graph.compiled_at,
        "is_builtin":  False,
    }
    _agents.put(graph_id, agent)

    return {
        "success":     True,
        "graph_id":    graph_id,
        "version":     new_version,
        "company":     company,
        "domain":      domain,
        "rule_count":  len(graph.rules),
        "verification": verification.to_dict() if verification else None,
        "graph":       graph.model_dump(),
    }


@app.post("/api/query-doc")
async def query_with_document(
    graph_id: str        = Form(...),
    file:     UploadFile = File(...),
    role:     Role       = Depends(require_query),
):
    """Upload a case document. LLM extracts facts → Rete engine decides (requires query permission)."""
    agent = _get_agent(graph_id)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet. Call /api/compile first.")

    content = await file.read()
    try:
        doc_text = extract_text(
            content, file.filename or "", file.content_type or "",
            max_chars=MAX_CHARS_FACTS,
        )
    except Exception as exc:
        raise HTTPException(422, f"Could not extract text from document: {exc}")

    if not doc_text.strip():
        raise HTTPException(422, "Document appears to be empty.")

    try:
        return agent.query(doc_text).model_dump()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Rule Management Endpoints — org self-service, no re-upload needed
# ─────────────────────────────────────────────────────────────────────────────

class RuleUpsertRequest(BaseModel):
    rule: dict[str, Any]          # full DACLRule-compatible dict
    changed_by: str  = "admin"
    change_note: str = ""


class RollbackRequest(BaseModel):
    to_version:  int
    changed_by:  str = "admin"
    change_note: str = ""


def _rebuild_agent_from_graph(graph_id: str, graph: DACLGraph) -> None:
    """Replace the in-memory agent engine with a freshly-built one from `graph`."""
    agent = _agents.get(graph_id)
    if agent is None:
        meta  = _registry.get(graph_id, {})
        agent = DACLAgent(
            graph_id=graph_id,
            domain=meta.get("domain", graph.domain),
            compiled_dir="compiled",
        )
        _agents.put(graph_id, agent)
    agent.graph  = graph
    agent.engine = DACLReteEngine(graph)
    # Update registry stats
    if graph_id in _registry:
        _registry[graph_id]["rule_count"]  = len(graph.rules)
        _registry[graph_id]["compiled_at"] = graph.compiled_at


@app.get("/api/rules/{graph_id}")
def list_rules(
    graph_id: str,
    role:     Role = Depends(require_read),
):
    """List all rules sorted by priority (requires read permission)."""
    graph_id = _resolve_graph_id(graph_id)
    agent    = _get_agent(graph_id)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet.")
    rules = [r.model_dump() for r in agent.graph.rules]
    rules.sort(key=lambda r: r["priority"], reverse=True)
    return {"graph_id": graph_id, "rule_count": len(rules), "rules": rules}


@app.post("/api/rules/{graph_id}")
def add_rule(
    graph_id: str,
    req:      RuleUpsertRequest,
    role:     Role = Depends(require_add_rule),
):
    """Add a new rule (requires add_rule permission)."""
    graph_id = _resolve_graph_id(graph_id)
    agent    = _get_agent(graph_id)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet.")

    try:
        new_rule = DACLRule(**req.rule)
    except Exception as exc:
        raise HTTPException(422, f"Invalid rule format: {exc}")

    # Check rule_id uniqueness
    existing_ids = {r.rule_id for r in agent.graph.rules}
    if new_rule.rule_id in existing_ids:
        raise HTTPException(
            409, f"Rule '{new_rule.rule_id}' already exists. Use PUT to update."
        )

    # Build new graph with added rule
    graph_data = agent.graph.model_dump()
    graph_data["rules"].append(new_rule.model_dump())
    graph_data["compiled_at"] = datetime.now(timezone.utc).isoformat()
    new_graph = DACLGraph(**graph_data)

    version = _versions.save_new_version(
        new_graph,
        changed_by=req.changed_by,
        change_note=req.change_note or f"Added rule '{new_rule.rule_id}'",
    )
    _rebuild_agent_from_graph(graph_id, new_graph)

    return {
        "success":     True,
        "version":     version,
        "rule_id":     new_rule.rule_id,
        "total_rules": len(new_graph.rules),
    }


@app.put("/api/rules/{graph_id}/{rule_id}")
def update_rule(
    graph_id: str,
    rule_id:  str,
    req:      RuleUpsertRequest,
    role:     Role = Depends(require_update_rule),
):
    """Update an existing rule (requires update_rule permission)."""
    graph_id = _resolve_graph_id(graph_id)
    agent    = _get_agent(graph_id)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet.")

    existing_ids = [r.rule_id for r in agent.graph.rules]
    if rule_id not in existing_ids:
        raise HTTPException(404, f"Rule '{rule_id}' not found. Use POST to add it.")

    try:
        updated_rule = DACLRule(**req.rule)
    except Exception as exc:
        raise HTTPException(422, f"Invalid rule format: {exc}")

    graph_data = agent.graph.model_dump()
    graph_data["rules"] = [
        updated_rule.model_dump() if r["rule_id"] == rule_id else r
        for r in graph_data["rules"]
    ]
    graph_data["compiled_at"] = datetime.now(timezone.utc).isoformat()
    new_graph = DACLGraph(**graph_data)

    version = _versions.save_new_version(
        new_graph,
        changed_by=req.changed_by,
        change_note=req.change_note or f"Updated rule '{rule_id}'",
    )
    _rebuild_agent_from_graph(graph_id, new_graph)

    return {
        "success": True,
        "version": version,
        "rule_id": rule_id,
        "total_rules": len(new_graph.rules),
    }


@app.delete("/api/rules/{graph_id}/{rule_id}")
def delete_rule(
    graph_id:    str,
    rule_id:     str,
    changed_by:  str  = "admin",
    change_note: str  = "",
    role:        Role = Depends(require_delete_rule),
):
    """Delete a rule (requires delete_rule permission)."""
    graph_id = _resolve_graph_id(graph_id)
    agent    = _get_agent(graph_id)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet.")

    existing_ids = [r.rule_id for r in agent.graph.rules]
    if rule_id not in existing_ids:
        raise HTTPException(404, f"Rule '{rule_id}' not found.")

    if len(agent.graph.rules) == 1:
        raise HTTPException(
            409, "Cannot delete the last rule. Add a replacement rule first."
        )

    graph_data = agent.graph.model_dump()
    graph_data["rules"] = [
        r for r in graph_data["rules"] if r["rule_id"] != rule_id
    ]
    graph_data["compiled_at"] = datetime.now(timezone.utc).isoformat()
    new_graph = DACLGraph(**graph_data)

    version = _versions.save_new_version(
        new_graph,
        changed_by=changed_by,
        change_note=change_note or f"Deleted rule '{rule_id}'",
    )
    _rebuild_agent_from_graph(graph_id, new_graph)

    return {
        "success":     True,
        "version":     version,
        "deleted":     rule_id,
        "total_rules": len(new_graph.rules),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Version Management Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/versions/{graph_id}")
def list_versions(graph_id: str):
    """List all immutable versions of a policy graph, newest first."""
    try:
        graph_id = _resolve_graph_id(graph_id)
    except HTTPException:
        pass  # allow direct graph_id even if not in registry
    versions = _versions.list_versions(graph_id)
    current  = _versions.current_version(graph_id)
    return {
        "graph_id":        graph_id,
        "current_version": current,
        "total_versions":  len(versions),
        "versions":        versions,
    }


@app.get("/api/versions/{graph_id}/{v_old}/diff/{v_new}")
def diff_versions(graph_id: str, v_old: int, v_new: int):
    """Show what changed between two versions (added/removed/changed rules)."""
    try:
        graph_id = _resolve_graph_id(graph_id)
    except HTTPException:
        pass
    try:
        return _versions.get_diff(graph_id, v_old, v_new)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/rollback/{graph_id}")
def rollback_policy(
    graph_id: str,
    req:      RollbackRequest,
    role:     Role = Depends(require_rollback),
):
    """Roll back a policy graph to a previous version (requires rollback permission)."""
    try:
        graph_id = _resolve_graph_id(graph_id)
    except HTTPException:
        pass
    try:
        restored_graph = _versions.rollback(
            graph_id,
            to_version=req.to_version,
            changed_by=req.changed_by,
            change_note=req.change_note or f"Rollback to v{req.to_version}",
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc))

    _rebuild_agent_from_graph(graph_id, restored_graph)
    new_version = _versions.current_version(graph_id)

    return {
        "success":      True,
        "graph_id":     graph_id,
        "restored_from": req.to_version,
        "new_version":  new_version,
        "rule_count":   len(restored_graph.rules),
    }


@app.get("/api/versions/{graph_id}/{version}/source")
def get_version_source(graph_id: str, version: int):
    """Retrieve the original policy text used to compile a specific version."""
    try:
        graph_id = _resolve_graph_id(graph_id)
    except HTTPException:
        pass
    source = _versions.load_source(graph_id, version)
    if source is None:
        raise HTTPException(
            404,
            f"No source text found for '{graph_id}' v{version}. "
            "(Source is only saved for upload-based compilations, not rule edits.)"
        )
    return {"graph_id": graph_id, "version": version, "source_text": source}


# ─────────────────────────────────────────────────────────────────────────────
# Action Audit Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/actions/{decision_id}")
def get_action_history(
    decision_id: str,
    role:        Role = Depends(require_read),
):
    """Retrieve the side-effect action history for a specific decision_id."""
    history = global_dispatcher.queue.get_history(decision_id)
    return {"decision_id": decision_id, "actions": history}


@app.get("/api/verify/{graph_id}")
def verify_graph(
    graph_id: str,
    role:     Role = Depends(require_read),
):
    """Run Z3 static verification on the active version of a policy graph."""
    from verifier import DACLVerifier
    try:
        resolved = _resolve_graph_id(graph_id)
    except HTTPException:
        resolved = graph_id
    agent = _get_agent(resolved)
    if agent.engine is None:
        try:
            agent.load_precompiled()
        except FileNotFoundError:
            raise HTTPException(400, "Graph not compiled yet.")
    result = DACLVerifier().verify(agent.graph)
    return result.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# External Workflow / AI Agent Endpoints (v1)
# ─────────────────────────────────────────────────────────────────────────────

workflow_router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])

@workflow_router.get("/health")
def workflow_health():
    """Health check for external workflows."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@workflow_router.get("/policies")
def workflow_list_policies(role: Role = Depends(require_read)):
    """List available policies for agent workflows."""
    return list_policies()

@workflow_router.post("/query")
def workflow_query(req: QueryRequest, role: Role = Depends(require_query)):
    """Natural-language text query for external agents."""
    return run_query(req, role)

@workflow_router.post("/query-doc")
async def workflow_query_doc(
    graph_id: str = Form(...),
    file: UploadFile = File(...),
    role: Role = Depends(require_query)
):
    """Document upload query for external agents."""
    return await query_with_document(graph_id=graph_id, file=file, role=role)

@workflow_router.post("/upload")
async def workflow_upload(
    company:        str        = Form(...),
    domain:         str        = Form(...),
    description:    str        = Form(""),
    force:          bool       = Form(False),
    strict_verify:  bool       = Form(False),
    changed_by:     str        = Form("workflow_agent"),
    change_note:    str        = Form("Automated upload"),
    file:           UploadFile = File(...),
    role:           Role       = Depends(require_upload),
):
    """Automated policy upload from external pipelines."""
    return await upload_policy(
        company=company, domain=domain, description=description,
        force=force, strict_verify=strict_verify, changed_by=changed_by,
        change_note=change_note, file=file, role=role
    )

app.include_router(workflow_router)

# ─────────────────────────────────────────────────────────────────────────────
# Serve React SPA build
# ─────────────────────────────────────────────────────────────────────────────
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(str(frontend_dist / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
