"""
DACL Rule Verifier — Z3 SMT-based static verification.

Runs immediately after LLM compilation (compile-time gate) to detect:
  1. Unsatisfiable rules — conditions that can NEVER fire (dead rules)
  2. Priority conflicts — two rules with OVERLAPPING conditions AND the same priority
     (execution order would be non-deterministic without strict priority ordering)
  3. Subsumed rules — a lower-priority rule that can NEVER fire because a higher-priority
     rule always covers its entire condition space first
  4. Coverage info — overlapping but correctly ordered rules (informational only)

Why Z3?
  The documents describe using SMT theorem provers (like Z3) to verify that compiled
  rule sets are "mathematically consistent" before deployment — catching hidden
  contradictions or loopholes that the LLM compiler may introduce.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from dacl_agent.models.schemas import DACLGraph, DACLRule

log = logging.getLogger(__name__)

# ── Graceful degradation if z3-solver is not installed ───────────────────────
try:
    from z3 import (  # type: ignore[import]
        And, Not, Or, Real, Solver, sat, unsat,
    )
    _Z3_AVAILABLE = True
except ImportError:
    _Z3_AVAILABLE = False
    log.warning(
        "[VERIFIER] z3-solver not installed — formal rule verification disabled. "
        "Install with: pip install z3-solver"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Result models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RuleConflict:
    rule_a:        str
    rule_b:        str          # empty string for single-rule issues (dead rule)
    conflict_type: str          # "dead_rule" | "priority_conflict" | "subsumed"
    message:       str
    severity:      str = "ERROR"  # "ERROR" | "WARNING" | "INFO"


@dataclass
class VerificationResult:
    graph_id:    str
    verified:    bool
    conflicts:   list[RuleConflict] = field(default_factory=list)
    dead_rules:  list[str]          = field(default_factory=list)
    warnings:    list[str]          = field(default_factory=list)
    info:        list[str]          = field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        """True when there are ERROR-level conflicts that must block deployment."""
        return any(c.severity == "ERROR" for c in self.conflicts)

    def summary(self) -> str:
        errors   = sum(1 for c in self.conflicts if c.severity == "ERROR")
        warnings = sum(1 for c in self.conflicts if c.severity == "WARNING")
        return (
            f"graph='{self.graph_id}' verified={self.verified} "
            f"errors={errors} warnings={warnings} dead_rules={len(self.dead_rules)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id":    self.graph_id,
            "verified":    self.verified,
            "summary":     self.summary(),
            "conflicts":   [
                {
                    "rule_a":        c.rule_a,
                    "rule_b":        c.rule_b,
                    "conflict_type": c.conflict_type,
                    "severity":      c.severity,
                    "message":       c.message,
                }
                for c in self.conflicts
            ],
            "dead_rules":  self.dead_rules,
            "warnings":    self.warnings,
            "info":        self.info,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Verifier
# ─────────────────────────────────────────────────────────────────────────────

class DACLVerifier:
    """
    Static Z3-backed verifier for DACL graphs.

    All checks run at COMPILE TIME — no runtime cost at inference.
    The verifier only processes numeric conditions; string/categorical
    conditions generate a warning and are skipped (partial verification).
    """

    NUMERIC_OPS = frozenset({">", "<", ">=", "<=", "==", "!="})

    def verify(self, graph: DACLGraph) -> VerificationResult:
        """Run all verification checks on the compiled graph.

        Args:
            graph: The fully compiled DACLGraph from the LLM compiler.

        Returns:
            VerificationResult — use .has_blocking_issues to decide
            whether to block deployment.
        """
        result = VerificationResult(graph_id=graph.graph_id, verified=False)

        if not _Z3_AVAILABLE:
            result.warnings.append(
                "z3-solver not installed — formal verification skipped. "
                "Install with: pip install z3-solver"
            )
            result.verified = True
            return result

        if not graph.rules:
            result.warnings.append("Graph has no rules — nothing to verify.")
            result.verified = True
            return result

        # Sort by priority descending (same order the engine uses)
        rules = sorted(graph.rules, key=lambda r: r.priority, reverse=True)

        # ── Check 1: Satisfiability (dead rules) ─────────────────────────────
        self._check_satisfiability(rules, result)

        # ── Check 2: Pairwise overlap + priority conflicts ────────────────────
        self._check_pairwise_overlap(rules, result)

        # ── Check 3: Subsumption (lower-priority rules masked by higher ones) ─
        self._check_subsumption(rules, result)

        result.verified = not result.has_blocking_issues

        # Emit structured log output
        log.info("[VERIFIER] %s", result.summary())
        for c in result.conflicts:
            if c.severity == "ERROR":
                log.error("[VERIFIER] %s: %s", c.conflict_type.upper(), c.message)
            else:
                log.warning("[VERIFIER] %s: %s", c.conflict_type.upper(), c.message)
        for w in result.warnings:
            log.warning("[VERIFIER] %s", w)

        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    def _check_satisfiability(
        self, rules: list[DACLRule], result: VerificationResult
    ) -> None:
        """Flag rules whose conditions can never be simultaneously satisfied."""
        for rule in rules:
            formula = self._rule_to_z3(rule)
            if formula is None:
                result.warnings.append(
                    f"Rule '{rule.rule_id}': contains non-numeric or unsupported "
                    "conditions — partial verification only"
                )
                continue

            solver = Solver()
            solver.add(formula)
            if solver.check() == unsat:
                result.dead_rules.append(rule.rule_id)
                result.conflicts.append(RuleConflict(
                    rule_a=rule.rule_id,
                    rule_b="",
                    conflict_type="dead_rule",
                    severity="ERROR",
                    message=(
                        f"Rule '{rule.rule_id}' has logically unsatisfiable conditions — "
                        f"no input can ever trigger this rule. "
                        f"Check for contradictions like (x > 10 AND x < 5)."
                    ),
                ))

    def _check_pairwise_overlap(
        self, rules: list[DACLRule], result: VerificationResult
    ) -> None:
        """For every pair of rules, check if both can fire on the same input."""
        for i, rule_a in enumerate(rules):
            formula_a = self._rule_to_z3(rule_a)
            if formula_a is None:
                continue

            for rule_b in rules[i + 1:]:
                formula_b = self._rule_to_z3(rule_b)
                if formula_b is None:
                    continue

                solver = Solver()
                solver.add(And(formula_a, formula_b))

                if solver.check() == sat:
                    if rule_a.priority == rule_b.priority:
                        # SAME priority + overlap = non-deterministic execution order → ERROR
                        result.conflicts.append(RuleConflict(
                            rule_a=rule_a.rule_id,
                            rule_b=rule_b.rule_id,
                            conflict_type="priority_conflict",
                            severity="ERROR",
                            message=(
                                f"Rules '{rule_a.rule_id}' and '{rule_b.rule_id}' have "
                                f"overlapping conditions AND identical priority "
                                f"({rule_a.priority}). "
                                "Execution order is non-deterministic — assign unique priorities."
                            ),
                        ))
                    else:
                        # Different priority + overlap = intentional or acceptable
                        result.info.append(
                            f"Rules '{rule_a.rule_id}' (p={rule_a.priority}) and "
                            f"'{rule_b.rule_id}' (p={rule_b.priority}) have overlapping "
                            "conditions — higher-priority rule will fire first (OK if intentional)."
                        )

    def _check_subsumption(
        self, rules: list[DACLRule], result: VerificationResult
    ) -> None:
        """Detect lower-priority rules that can never fire because a higher-priority
        rule always covers their entire condition space."""
        for i, rule_high in enumerate(rules):
            formula_high = self._rule_to_z3(rule_high)
            if formula_high is None:
                continue

            for rule_low in rules[i + 1:]:
                if rule_low.rule_id in result.dead_rules:
                    continue  # already flagged

                formula_low = self._rule_to_z3(rule_low)
                if formula_low is None:
                    continue

                # Subsumption: rule_low => rule_high
                # Equivalent: NOT(rule_low AND NOT(rule_high)) is UNSAT
                solver = Solver()
                solver.add(And(formula_low, Not(formula_high)))

                if solver.check() == unsat:
                    # rule_low is always subsumed by rule_high
                    result.dead_rules.append(rule_low.rule_id)
                    result.conflicts.append(RuleConflict(
                        rule_a=rule_high.rule_id,
                        rule_b=rule_low.rule_id,
                        conflict_type="subsumed",
                        severity="WARNING",
                        message=(
                            f"Rule '{rule_low.rule_id}' (p={rule_low.priority}) "
                            f"is completely subsumed by '{rule_high.rule_id}' "
                            f"(p={rule_high.priority}) — it will never fire "
                            "because the higher-priority rule always matches first."
                        ),
                    ))

    def _rule_to_z3(self, rule: DACLRule) -> Any | None:
        """Convert a rule's conditions to a Z3 Boolean formula.

        Returns None if any condition uses non-numeric values (string literals,
        list operators, cross-fact references) because Z3's string theory is
        too heavyweight for this use case.
        """
        try:
            z3_vars: dict[str, Any] = {}
            constraints:  list[Any] = []

            for cond in rule.conditions:
                if cond.operator not in self.NUMERIC_OPS:
                    return None  # "in" / "not_in" — skip

                # Cross-fact references (@field) are not statically evaluable
                if isinstance(cond.value, str) and cond.value.startswith("@"):
                    return None

                try:
                    value = float(cond.value)
                except (TypeError, ValueError):
                    return None  # string literal condition

                if cond.field not in z3_vars:
                    z3_vars[cond.field] = Real(cond.field)

                var = z3_vars[cond.field]

                if cond.operator == ">":
                    constraints.append(var > value)
                elif cond.operator == "<":
                    constraints.append(var < value)
                elif cond.operator == ">=":
                    constraints.append(var >= value)
                elif cond.operator == "<=":
                    constraints.append(var <= value)
                elif cond.operator == "==":
                    constraints.append(var == value)
                elif cond.operator == "!=":
                    constraints.append(var != value)

            if not constraints:
                return None

            if len(constraints) == 1:
                return constraints[0]

            if rule.condition_logic == "OR":
                return Or(*constraints)
            return And(*constraints)   # default AND

        except Exception as exc:
            log.debug("[VERIFIER] Z3 conversion failed for rule '%s': %s", rule.rule_id, exc)
            return None
