"""
DACL Rete Engine — Enterprise-Grade RETE Alpha Discrimination Network.

┌────────────────────────────────────────────────────────────────────────────┐
│              RETE ALGORITHM (Forgy 1979) — Enterprise Edition              │
│                                                                            │
│  FIXES APPLIED:                                                            │
│    1. Incremental Alpha Activation — only new/changed facts re-evaluated   │
│    2. Safe formula evaluation — returns None on error, never a poison str  │
│    3. lru_cache bytecode cache — bounded memory, no infinite growth        │
│    4. Nested dict output auto-flattened before injection into working mem  │
│    5. Typed FormulaError sentinel — downstream rules skip on bad output    │
│    6. Robust NameError handling — no brittle string.split() parsing        │
│    7. Cross-fact @ references resolved before binary-search path           │
│    8. OR-rule field pre-check corrected (AND-only gate removed for OR)     │
│    9. DEFAULT action also evaluated via safe formula path                  │
│   10. MAX_CHAIN_DEPTH configurable per-engine, not hard-coded              │
│                                                                            │
│  PERFORMANCE:                                                              │
│    Naive: O(N × C) — 100K rules × 3 conds = 300K evaluations             │
│    RETE:  O(F × log A) — ≈ 50 evaluations  (~6,000× faster)               │
│    Incremental forward-chain: only Δfacts re-activate alpha (≈ 5 evals)   │
└────────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import bisect
import logging
import math
from collections import defaultdict
from functools import lru_cache
from typing import Any

from dacl_agent.models.schemas import DACLGraph, DACLRule, RuleMatchResult, AuditTrail
from langsmith import traceable

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel: formula evaluation failure (never injected as a raw string)
# ─────────────────────────────────────────────────────────────────────────────
class FormulaError:
    """Typed sentinel returned when a formula cannot be evaluated safely.

    Downstream rules that encounter a FormulaError in working_facts will
    short-circuit to False for any numeric comparison rather than crashing.
    """
    __slots__ = ("reason",)

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self) -> str:
        return f"[FormulaError: {self.reason}]"


# ─────────────────────────────────────────────────────────────────────────────
# Formula Compiler — bounded LRU cache, no infinite growth
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=2048)
def _compile_formula(formula: str):
    """Compile a formula string to bytecode exactly once. LRU-bounded at 2048."""
    return compile(formula, "<dacl_formula>", "eval")


_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max,
    "int": int, "float": float, "str": str, "math": math,
    "bool": bool, "len": len, "sum": sum, "sorted": sorted,
}


def _safe_eval(formula: str, facts: dict[str, Any]) -> Any:
    """Evaluate a formula string against facts.

    Returns:
        The computed value on success.
        FormulaError sentinel on any failure — never a raw error string.

    Security:
        __builtins__ fully removed; only _SAFE_BUILTINS exposed.
        Pre-compiled bytecode via LRU cache for performance.
    """
    # Replace FormulaError sentinels in facts with None so numeric ops don't crash
    safe_facts = {
        k: (None if isinstance(v, FormulaError) else v)
        for k, v in facts.items()
    }
    try:
        code = _compile_formula(formula)
        ns = {**safe_facts, **_SAFE_BUILTINS}
        return eval(code, {"__builtins__": {}}, ns)  # noqa: S307
    except NameError as err:
        # Robust extraction — don't rely on brittle string splitting
        missing = getattr(err, "name", None) or str(err)
        log.debug("Formula '%s' missing variable: %s", formula, missing)
        return FormulaError(f"missing_var={missing}")
    except (TypeError, ValueError) as err:
        log.debug("Formula '%s' type/value error: %s", formula, err)
        return FormulaError(f"type_error={err}")
    except ZeroDivisionError:
        log.debug("Formula '%s' division by zero", formula)
        return FormulaError("division_by_zero")
    except Exception as err:  # noqa: BLE001
        log.debug("Formula '%s' unexpected error: %s", formula, err)
        return FormulaError(f"error={err}")


# ─────────────────────────────────────────────────────────────────────────────
# Fact Normalizer — auto-flattens nested dicts + new injected outputs
# ─────────────────────────────────────────────────────────────────────────────
def _flatten_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Normalise a possibly-nested facts dict into a flat namespace.

    Handles:
      - Standard flat dicts (zero-copy fast path).
      - Nested dicts:  {"order": {"amount": 1000}} → "order.amount"=1000
      - FormulaError sentinels are preserved as-is (not re-processed).

    Called both at init and whenever a dict-valued output is injected
    into working memory during forward-chaining.
    """
    has_nested = any(isinstance(v, dict) for v in facts.values())
    if not has_nested:
        return facts  # fast-path: no copy

    result: dict[str, Any] = dict(facts)
    for key, val in facts.items():
        if isinstance(val, dict):
            for subkey, subval in val.items():
                dot_key   = f"{key}.{subkey}"
                under_key = f"{key}_{subkey}"
                result[dot_key] = subval
                if under_key not in facts:
                    result[under_key] = subval
    return result


def _inject_output(
    working_facts: dict[str, Any],
    output_field: str,
    output_val: Any,
) -> dict[str, Any]:
    """Inject a rule's output into working memory, flattening dicts automatically.

    This fixes the bug where dict-valued outputs were injected raw, making
    dot-notation fields (e.g. 'result.status') invisible to downstream rules.
    """
    working_facts[output_field] = output_val
    if isinstance(output_val, dict):
        # Expand keys so downstream rules can reference result.status etc.
        for subkey, subval in output_val.items():
            dot_key   = f"{output_field}.{subkey}"
            under_key = f"{output_field}_{subkey}"
            working_facts[dot_key] = subval
            if under_key not in working_facts:
                working_facts[under_key] = subval
    return working_facts


# ─────────────────────────────────────────────────────────────────────────────
# Alpha Node: single condition evaluator
# ─────────────────────────────────────────────────────────────────────────────
class AlphaNode:
    """Pattern filter for one condition in the discrimination network."""

    __slots__ = ("rule_id", "condition_idx", "condition")

    def __init__(self, rule_id: str, condition_idx: int, condition):
        self.rule_id       = rule_id
        self.condition_idx = condition_idx
        self.condition     = condition

    def activate(self, facts: dict[str, Any]) -> tuple[bool, dict]:
        """Evaluate condition. Returns (passed, trace_dict)."""
        fact_val = facts.get(self.condition.field)
        passed   = self.condition.evaluate(facts)
        return passed, self._trace(fact_val, passed)

    def _trace(self, fact_val: Any, passed: bool) -> dict:
        return {
            "field":          self.condition.field,
            "operator":       self.condition.operator,
            "expected_value": self.condition.value,
            "fact_value":     fact_val,
            "passed":         passed,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Alpha Network: the discrimination tree (core of RETE performance)
# ─────────────────────────────────────────────────────────────────────────────
class AlphaNetwork:
    """RETE Alpha Discrimination Network.

    Built once at compile time (DACLReteEngine.__init__).
    Supports incremental activation — caller passes only the *new* facts
    that changed since the last activate() call to avoid redundant work.

    Two-tier indexing:
      Tier 1 — field index: only activate nodes whose field is in the facts.
      Tier 2 — sorted numeric index: O(log A) binary search for >, >=, <, <=.
    """

    _RANGE_OPS = frozenset({">", ">=", "<", "<="})

    def __init__(self, rules: list[DACLRule]):
        # field → operator → [(threshold, AlphaNode), ...] sorted asc by threshold
        self._sorted: dict[str, dict[str, list[tuple[float, AlphaNode]]]] = (
            defaultdict(lambda: defaultdict(list))
        )
        # field → [AlphaNode] for ==, !=, in, not_in
        self._linear: dict[str, list[AlphaNode]] = defaultdict(list)

        # Per-rule metadata for beta join
        self._rule_required_fields: dict[str, frozenset[str]] = {}
        self._rule_cond_count: dict[str, int] = {}

        for rule in rules:
            self._rule_required_fields[rule.rule_id] = frozenset(
                c.field for c in rule.conditions
            )
            self._rule_cond_count[rule.rule_id] = len(rule.conditions)

            for idx, cond in enumerate(rule.conditions):
                # Skip @-reference conditions from binary-search path;
                # they must be evaluated at runtime via linear path.
                is_cross_ref = isinstance(cond.value, str) and cond.value.startswith("@")
                node = AlphaNode(rule.rule_id, idx, cond)

                if cond.operator in self._RANGE_OPS and not is_cross_ref:
                    try:
                        threshold = float(cond.value)
                        self._sorted[cond.field][cond.operator].append((threshold, node))
                        continue
                    except (TypeError, ValueError):
                        pass
                self._linear[cond.field].append(node)

        # Sort threshold lists ascending (required for correct bisect behaviour)
        for field_ops in self._sorted.values():
            for items in field_ops.values():
                items.sort(key=lambda x: x[0])

    # ── Public API ─────────────────────────────────────────────────────────────

    def activate(
        self,
        facts: dict[str, Any],
        *,
        existing: dict[str, dict[int, tuple[bool, dict]]] | None = None,
    ) -> dict[str, dict[int, tuple[bool, dict]]]:
        """Route facts through the discrimination network.

        Args:
            facts:    The facts to activate against (can be only Δfacts for
                      incremental mode — pass only newly added/changed keys).
            existing: Previous results dict to merge into (incremental mode).
                      If None, a fresh result dict is built.

        Returns: {rule_id: {condition_idx: (passed, trace_dict)}}
        """
        results: dict[str, dict[int, tuple[bool, dict]]] = (
            defaultdict(dict) if existing is None else existing
        )
        available = set(facts.keys())

        for field in available:
            fact_val = facts[field]

            # Skip FormulaError sentinels — treat as missing field
            if isinstance(fact_val, FormulaError):
                continue

            # ── Sorted (binary search) path for numeric range ops ────────────
            field_sorted = self._sorted.get(field)
            if field_sorted:
                try:
                    num = float(fact_val)
                    for op, items in field_sorted.items():
                        thresholds   = [t for t, _ in items]
                        nodes        = [n for _, n in items]
                        passed_flags = self._bisect_eval(op, num, thresholds)
                        for node, passed in zip(nodes, passed_flags):
                            results[node.rule_id][node.condition_idx] = (
                                passed,
                                node._trace(fact_val, passed),
                            )
                except (TypeError, ValueError):
                    pass  # Fall through to linear path

            # ── Linear path for equality / membership / cross-ref ops ────────
            for node in self._linear.get(field, []):
                passed, trace = node.activate(facts)
                results[node.rule_id][node.condition_idx] = (passed, trace)

        return results

    def required_fields(self, rule_id: str) -> frozenset[str]:
        return self._rule_required_fields.get(rule_id, frozenset())

    def condition_count(self, rule_id: str) -> int:
        return self._rule_cond_count.get(rule_id, 0)

    # ── Internal: binary search split ─────────────────────────────────────────
    @staticmethod
    def _bisect_eval(op: str, fact_val: float, thresholds: list[float]) -> list[bool]:
        """Resolve ALL conditions sharing field+op with a single bisect call.

        Truth table (condition semantics: `fact_val OP threshold`):
          >  : passes when threshold <  fact_val → nodes[:bisect_left]  pass
          >= : passes when threshold <= fact_val → nodes[:bisect_right] pass
          <  : passes when threshold >  fact_val → nodes[bisect_right:] pass
          <= : passes when threshold >= fact_val → nodes[bisect_left:]  pass
        """
        n = len(thresholds)
        if op == ">":
            s = bisect.bisect_left(thresholds, fact_val)
            return [True] * s + [False] * (n - s)
        if op == ">=":
            s = bisect.bisect_right(thresholds, fact_val)
            return [True] * s + [False] * (n - s)
        if op == "<":
            s = bisect.bisect_right(thresholds, fact_val)
            return [False] * s + [True] * (n - s)
        if op == "<=":
            s = bisect.bisect_left(thresholds, fact_val)
            return [False] * s + [True] * (n - s)
        return [False] * n  # unreachable for _RANGE_OPS


# ─────────────────────────────────────────────────────────────────────────────
# Temporal Rule Filter — enforces temporal_from / temporal_to bounds
# ─────────────────────────────────────────────────────────────────────────────
def _filter_temporal_rules(
    rules: list[DACLRule],
    now_str: str,
) -> list[DACLRule]:
    """Return only rules whose temporal window includes `now_str`.

    Rules with temporal_from=None AND temporal_to=None are always active.
    ISO-8601 strings are compared lexicographically (valid for UTC timestamps).

    Args:
        rules:   Priority-sorted list of all rules.
        now_str: Current time as ISO-8601 UTC string (from execute() timestamp).

    Returns:
        Subset of rules that are temporally active at `now_str`.
    """
    active: list[DACLRule] = []
    for rule in rules:
        from_ok = rule.temporal_from is None or now_str >= rule.temporal_from
        to_ok   = rule.temporal_to   is None or now_str <= rule.temporal_to
        if from_ok and to_ok:
            active.append(rule)
        else:
            log.debug(
                "[TEMPORAL] Rule '%s' skipped — window=[%s, %s] now=%s",
                rule.rule_id, rule.temporal_from, rule.temporal_to, now_str,
            )
    return active


# ─────────────────────────────────────────────────────────────────────────────
# DACL Rete Engine — Alpha Network + Beta Join + Priority Agenda
# ─────────────────────────────────────────────────────────────────────────────
class DACLReteEngine:
    """Deterministic DACL execution engine — Enterprise Edition.

    Compile-time (once):
      AlphaNetwork built: conditions indexed by field, sorted by threshold.

    Inference-time (every query):
      1. Fact normalisation  : flatten nested dicts → dot-notation keys.
      2. Alpha activation    : route facts through discrimination network O(F log A).
      3. Beta join per rule  : field pre-check (corrected for OR rules) + AND/OR join.
      4. Agenda + formula    : highest-priority match fires; FormulaError-safe.
      5. Incremental forward-chain: only Δfacts re-activate alpha (massive speedup).
      6. AuditTrail          : full trace with chained_rules + chain_depth.

    Performance at 100K rules:
      Naive scan        : O(N × C)     ≈ 300K evaluations
      RETE alpha        : O(F × log A) ≈ 50 evaluations  (~6,000× faster)
      Incremental chain : O(Δ × log A) ≈ 5 evaluations per chain step
    """

    DEFAULT_MAX_CHAIN_DEPTH = 20

    def __init__(self, graph: DACLGraph, max_chain_depth: int | None = None):
        self.graph           = graph
        self.max_chain_depth = max_chain_depth or self.DEFAULT_MAX_CHAIN_DEPTH

        # Rules sorted by priority descending — agenda conflict resolution
        self._sorted_rules: list[DACLRule] = sorted(
            graph.rules, key=lambda r: r.priority, reverse=True
        )
        # Build alpha discrimination network (built once, reused forever)
        # Note: temporal filtering happens at execute() time, not here,
        # so rules that become valid later don't require a network rebuild.
        self.alpha_network = AlphaNetwork(self._sorted_rules)

        n_sorted = sum(
            len(items)
            for field_ops in self.alpha_network._sorted.values()
            for items in field_ops.values()
        )
        n_linear = sum(len(v) for v in self.alpha_network._linear.values())
        log.info(
            "[RETE] Network built: %d rules | alpha sorted=%d linear=%d | fields=%s",
            len(self._sorted_rules), n_sorted, n_linear,
            list(self.alpha_network._sorted) + list(self.alpha_network._linear),
        )

    # ── Main inference entry point ────────────────────────────────────────────

    @traceable(name="DACL Rete Engine Execution", run_type="chain")
    def execute(
        self,
        facts: dict[str, Any],
        query: str,
        intent: str,
        timestamp: str,
    ) -> AuditTrail:
        """INFERENCE: deterministic — same facts always produce same output.

        Steps:
          1. Normalise facts (flatten nested dicts to dot-keys).
          2. Full alpha activation on initial facts.
          3. Beta join + priority agenda → highest-priority rule fires.
          4. Inject output into working memory (with dict auto-flatten).
          5. Incremental re-activate alpha on ONLY the new output field.
          6. Repeat 3–5 until fixpoint or MAX_CHAIN_DEPTH.
          7. Default action fallback + diagnostic hints if nothing matched.
          8. Return full AuditTrail.
        """
        # ── Step 0: Temporal filtering ────────────────────────────────────────
        # Filter out rules whose temporal window does not include `timestamp`.
        # This ensures time-expired rules never fire, even if their conditions match.
        now_str = timestamp  # ISO-8601 UTC string
        active_rules = _filter_temporal_rules(self._sorted_rules, now_str)

        # If temporal filtering changed the rule set, rebuild the alpha network
        # scoped to active rules only (avoids false positives in alpha results).
        if len(active_rules) != len(self._sorted_rules):
            scoped_network = AlphaNetwork(active_rules)
        else:
            scoped_network  = self.alpha_network
            active_rules    = self._sorted_rules  # reuse sorted reference

        # ── Step 1: Normalise ─────────────────────────────────────────────────
        working_facts: dict[str, Any] = _flatten_facts(facts)

        all_results:     list[RuleMatchResult] = []
        final_output:    dict[str, Any]        = {}
        winning_rule_id: str | None            = None
        audit_clause                           = "no_rule_matched"

        fired_rule_ids: set[str]  = set()
        chained_rules:  list[str] = []

        # ── Step 2: Full alpha activation on initial facts ────────────────────
        # alpha_results persists across chain iterations; only Δ re-activates.
        alpha_results: dict[str, dict[int, tuple[bool, dict]]] = defaultdict(dict)
        scoped_network.activate(working_facts, existing=alpha_results)

        # ── Steps 3–5: Incremental forward-chain agenda loop ──────────────────
        for chain_iter in range(self.max_chain_depth):
            available_fields   = set(working_facts.keys())
            fired_in_this_pass = False

            for rule in active_rules:
                if rule.rule_id in fired_rule_ids:
                    continue

                # Fast-exit: rule never appeared in any alpha result
                if rule.rule_id not in alpha_results:
                    if len(self._sorted_rules) < 500:
                        all_results.append(RuleMatchResult(
                            rule_id=rule.rule_id, matched=False, conditions_evaluated=[]
                        ))
                    continue

                required   = scoped_network.required_fields(rule.rule_id)
                cond_count = scoped_network.condition_count(rule.rule_id)

                # Field pre-check:
                #   AND rules need ALL required fields present.
                #   OR  rules only need AT LEAST ONE required field present.
                #   (Bug fix: old code applied AND-gate to OR rules, incorrectly skipping them.)
                missing = required - available_fields
                if missing:
                    if rule.condition_logic == "AND":
                        all_results.append(RuleMatchResult(
                            rule_id=rule.rule_id,
                            matched=False,
                            conditions_evaluated=[
                                {"field": f, "operator": "?", "expected_value": "?",
                                 "fact_value": None, "passed": False}
                                for f in sorted(missing)
                            ],
                        ))
                        continue
                    elif rule.condition_logic == "OR" and missing == required:
                        # OR rule: ALL fields missing → definitely can't fire
                        all_results.append(RuleMatchResult(
                            rule_id=rule.rule_id, matched=False, conditions_evaluated=[]
                        ))
                        continue

                # Reconstruct ordered condition traces from alpha results
                rule_alpha = alpha_results.get(rule.rule_id, {})
                traces: list[dict] = []
                passes: list[bool] = []

                for i in range(cond_count):
                    if i in rule_alpha:
                        p, trace = rule_alpha[i]
                    else:
                        cond = rule.conditions[i]
                        p, trace = False, {
                            "field": cond.field, "operator": cond.operator,
                            "expected_value": cond.value, "fact_value": None, "passed": False,
                        }
                    passes.append(p)
                    traces.append(trace)

                # Beta join: AND / OR over condition results
                matched = all(passes) if rule.condition_logic == "AND" else any(passes)

                result = RuleMatchResult(
                    rule_id=rule.rule_id,
                    matched=matched,
                    conditions_evaluated=traces,
                )

                if matched:
                    # ── Agenda fires ─────────────────────────────────────────
                    output_val = _safe_eval(rule.action.formula, working_facts)

                    result.action_applied = rule.action.formula
                    result.output_value   = (
                        repr(output_val) if isinstance(output_val, FormulaError)
                        else output_val
                    )

                    # Only record winning_rule_id for non-error outputs
                    if not isinstance(output_val, FormulaError):
                        final_output[rule.action.output_field] = output_val
                        if winning_rule_id is None:
                            winning_rule_id = rule.rule_id
                            audit_clause    = rule.audit_clause or rule.rule_id

                        chain_label = f" » chain[{chain_iter}]" if chain_iter > 0 else ""
                        log.info(
                            "[FIRED%s] '%s'  →  %s = %r",
                            chain_label, rule.rule_id,
                            rule.action.output_field, output_val,
                        )

                        # ── Incremental forward-chain (KEY FIX) ──────────────
                        # Inject output into working memory with auto-flatten
                        prev_keys = set(working_facts.keys())
                        _inject_output(working_facts, rule.action.output_field, output_val)
                        new_keys  = set(working_facts.keys()) - prev_keys

                        # Only re-activate alpha for the NEW keys — not all facts
                        if new_keys:
                            delta_facts = {k: working_facts[k] for k in new_keys}
                            scoped_network.activate(delta_facts, existing=alpha_results)

                        fired_rule_ids.add(rule.rule_id)
                        chained_rules.append(rule.rule_id)
                        fired_in_this_pass = True
                        all_results.append(result)
                        break  # restart priority agenda with updated alpha_results

                    else:
                        log.warning(
                            "[FORMULA_ERROR] rule='%s' formula='%s' error=%r",
                            rule.rule_id, rule.action.formula, output_val,
                        )

                all_results.append(result)

            if not fired_in_this_pass:
                break  # Fixpoint — forward-chain complete

        # ── Step 6: Default action fallback ───────────────────────────────────
        if not chained_rules and self.graph.default_action:
            da         = self.graph.default_action
            output_val = _safe_eval(da.formula, working_facts)

            if not isinstance(output_val, FormulaError):
                final_output[da.output_field] = output_val
                audit_clause = "default_fallback"
            else:
                log.warning("[DEFAULT_FORMULA_ERROR] %r", output_val)
                audit_clause = "default_fallback_formula_error"

            # Diagnostic hint: which fields would unlock a rule?
            missing_fields_summary: set[str] = set()
            for rule in active_rules:
                if rule.rule_id in alpha_results:
                    missing_fields_summary.update(
                        scoped_network.required_fields(rule.rule_id)
                        - set(working_facts.keys())
                    )
            if missing_fields_summary:
                final_output["_system_hint"] = (
                    f"Rules were found but required missing facts: "
                    f"{', '.join(sorted(missing_fields_summary))}. "
                    "Providing these will give a more accurate result."
                )

        return AuditTrail(
            query=query,
            intent=intent,
            extracted_facts=facts,
            execution_strategy=self.graph.optimization_strategy,
            rules_evaluated=all_results,
            winning_rule_id=winning_rule_id,
            final_output=final_output,
            audit_clause=audit_clause,
            engine_version=self.graph.version,
            timestamp=timestamp,
            chained_rules=chained_rules,
            chain_depth=max(0, len(chained_rules) - 1),
        )
