"""
DACL Schemas — Pydantic models for the compile and inference pipeline.
"""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


# ─────────────────────── HELPER: DOT-NOTATION RESOLVER ─────────────────────

def _get_fact_value(facts: dict[str, Any], path: str) -> Any:
    """
    Resolve a (possibly dot-notation) field path from a facts dict.

    Resolution order:
      1. Flat key:      "weight"       → facts["weight"]
      2. Pre-flattened: "order.amount" → facts["order.amount"]  (set by engine._flatten_facts)
      3. Nested:        "order.amount" → facts["order"]["amount"]
    """
    if "." not in path:
        return facts.get(path)
    # Pre-flattened dot-key (fast path after engine._flatten_facts has run)
    direct = facts.get(path)
    if direct is not None:
        return direct
    # Nested dict traversal fallback
    parts = path.split(".", 1)
    root = facts.get(parts[0])
    if not isinstance(root, dict):
        return None
    return _get_fact_value(root, parts[1])


# ─────────────────────────── COMPILE-TIME SCHEMAS ────────────────────────────

def _normalize_bool(val: Any) -> bool | None:
    """Normalize common truthy/falsy representations to standard Python booleans."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        v_clean = val.strip().lower()
        if v_clean in ("y", "yes", "true", "1", "t"):
            return True
        if v_clean in ("n", "no", "false", "0", "f"):
            return False
    return None


class Condition(BaseModel):
    """A single condition in a DACL rule."""
    field: str = Field(..., description="Fact field to evaluate. Supports dot-notation: 'order.amount'")
    operator: Literal[">", "<", ">=", "<=", "==", "!=", "in", "not_in"] = Field(...)
    value: Any = Field(..., description="Value to compare. Prefix with '@' for a cross-fact reference: '@account.credit_limit'")

    def evaluate(self, facts: dict[str, Any]) -> bool:
        """Deterministically evaluate this condition against runtime facts.

        Supports:
          - Dot-notation fields:     field='order.amount'
          - Cross-fact value refs:   value='@account.credit_limit'
        """
        fact_val = _get_fact_value(facts, self.field)
        if fact_val is None:
            return False
        op = self.operator
        # Resolve @-prefixed cross-fact value reference (e.g. "@account.credit_limit")
        v = self.value
        if isinstance(v, str) and v.startswith("@"):
            v = _get_fact_value(facts, v[1:])
            if v is None:
                return False
        if op == ">":   return float(fact_val) > float(v)
        if op == "<":   return float(fact_val) < float(v)
        if op == ">=":  return float(fact_val) >= float(v)
        if op == "<=":  return float(fact_val) <= float(v)
        if op == "==":
            # Robust boolean normalization (handles Y/yes/true/True vs N/no/false/False)
            nb_fact = _normalize_bool(fact_val)
            nb_val = _normalize_bool(v)
            if nb_fact is not None and nb_val is not None:
                return nb_fact == nb_val
            if isinstance(fact_val, str) and isinstance(v, str):
                return fact_val.strip().lower() == v.strip().lower()
            return fact_val == v
        if op == "!=":
            nb_fact = _normalize_bool(fact_val)
            nb_val = _normalize_bool(v)
            if nb_fact is not None and nb_val is not None:
                return nb_fact != nb_val
            if isinstance(fact_val, str) and isinstance(v, str):
                return fact_val.strip().lower() != v.strip().lower()
            return fact_val != v
        if op == "in":  return fact_val in v
        if op == "not_in": return fact_val not in v
        return False


class ActionFormula(BaseModel):
    """A formula/action to execute when a rule fires."""
    output_field: str = Field(..., description="The field to write the result into")
    formula: str = Field(..., description="Python-safe formula string using fact values")
    description: str = Field(default="", description="Human-readable description")


class DACLRule(BaseModel):
    """A single compiled DACL rule node."""
    rule_id: str
    description: str
    priority: int = Field(default=100, description="Higher = evaluated first")
    conditions: list[Condition]
    condition_logic: Literal["AND", "OR"] = Field(default="AND")
    action: ActionFormula
    audit_clause: str = Field(default="", description="The source policy clause")
    temporal_from: str | None = Field(default=None)
    temporal_to: str | None = Field(default=None)


class DACLGraph(BaseModel):
    """The fully compiled DACL executable graph."""
    graph_id: str
    version: str
    domain: str
    description: str
    rules: list[DACLRule]
    default_action: ActionFormula | None = None
    optimization_strategy: Literal["rete", "forward_chain", "decision_tree", "indexed"] = Field(
        default="rete"
    )
    compiled_at: str
    # Multi-tenant: which company/organisation this graph belongs to
    company: str = Field(default="default", description="Company / tenant identifier")


# ─────────────────────────── INFERENCE-TIME SCHEMAS ──────────────────────────

class ExtractedFacts(BaseModel):
    """LLM output: intent + structured facts from natural language query."""
    intent: str = Field(..., description="Detected user intent")
    domain: str = Field(..., description="The business domain (e.g. freight_pricing)")
    facts: dict[str, Any] = Field(..., description="Extracted fact key-value pairs")
    query_summary: str = Field(..., description="One-line summary of what was asked")
    confidence_score: float = Field(default=1.0, description="LLM confidence in extraction (0.0 to 1.0)")
    requires_human_review: bool = Field(default=False, description="Flagged for human review if confidence is low")


class RuleMatchResult(BaseModel):
    """Result of a single rule evaluation."""
    rule_id: str
    matched: bool
    conditions_evaluated: list[dict[str, Any]]  # {field, operator, value, fact_value, passed}
    action_applied: str | None = None
    output_value: Any = None


class AuditTrail(BaseModel):
    """Full auditable trace of DACL engine execution."""
    query: str
    intent: str
    extracted_facts: dict[str, Any]
    execution_strategy: str
    rules_evaluated: list[RuleMatchResult]
    winning_rule_id: str | None
    final_output: dict[str, Any]
    audit_clause: str
    engine_version: str
    timestamp: str
    chained_rules: list[str] = Field(default_factory=list, description="All rule IDs that fired in forward-chain order")
    chain_depth: int = Field(default=0, description="Forward-chain iterations beyond the first (0 = single rule fired)")


class DACLResponse(BaseModel):
    """Final deterministic response from DACL agent."""
    success: bool
    answer: str
    output: dict[str, Any]
    audit: AuditTrail
    requires_human_review: bool = Field(default=False, description="Whether this request needs human intervention")
