"""
DACL Agent — Orchestrator.

Glues compile-time + inference-time together.
Shows exactly where LLM is used vs where deterministic engine runs.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from langsmith import traceable

from dacl_agent.services.actions import global_dispatcher
from dacl_agent.services.compiler import compile_policy, load_graph, save_graph
from dacl_agent.services.engine import DACLReteEngine
from dacl_agent.services.fact_extractor import extract_facts
from dacl_agent.models.schemas import DACLGraph, DACLResponse
from dacl_agent.services.verifier import VerificationResult

log = logging.getLogger(__name__)


class DACLAgent:
    """The DACL orchestrator.

    Lifecycle:
      1. compile(policy_text)  → calls LLM once, saves graph to disk
      2. query(user_input)     → calls LLM once (fact extract), then pure Rete engine

    After compile(), query() never needs a full LLM reasoning call.
    """

    def __init__(self, graph_id: str, domain: str, compiled_dir: str = "compiled"):
        self.graph_id     = graph_id
        self.domain       = domain
        self.compiled_dir = compiled_dir
        self.graph: DACLGraph | None           = None
        self.engine: DACLReteEngine | None     = None
        self.verification: VerificationResult | None = None

    # ──────────────────────────── COMPILE PHASE ──────────────────────────────

    @traceable(name="DACL Agent Compile", run_type="chain")
    def compile(self, policy_text: str, force: bool = False, strict_verify: bool = False) -> DACLGraph:
        """COMPILE TIME (run once).

        Uses GPT-4o to translate business policy → DACL graph → save to disk.
        Runs Z3 verifier immediately after compilation.
        """
        from pathlib import Path
        graph_path = Path(self.compiled_dir) / f"{self.graph_id}.json"

        if not force and graph_path.exists():
            log.info("[CACHE] Pre-compiled graph found — loading from disk (no LLM needed)")
            self.graph  = load_graph(self.graph_id, self.compiled_dir)
        else:
            self.graph, self.verification = compile_policy(
                policy_text, self.graph_id, self.domain,
                strict_verify=strict_verify,
            )
            save_graph(self.graph, self.compiled_dir)

        self.engine = DACLReteEngine(self.graph)
        return self.graph

    def load_precompiled(self) -> DACLGraph:
        """Load an already-compiled graph from disk without re-running the LLM."""
        self.graph  = load_graph(self.graph_id, self.compiled_dir)
        self.engine = DACLReteEngine(self.graph)
        return self.graph

    # ──────────────────────────── INFERENCE PHASE ────────────────────────────

    @traceable(name="DACL Agent Query", run_type="chain")
    def query(self, user_input: str) -> DACLResponse:
        """INFERENCE TIME (runs many times — cheap, deterministic).

        Step 1: Lightweight LLM call → extract intent + facts
        Step 2: Pure Rete engine     → deterministic result (no LLM)
        Step 3: Build response with full audit trail
        """
        if self.engine is None:
            raise RuntimeError("No compiled graph loaded. Call compile() first.")

        timestamp = datetime.now(timezone.utc).isoformat()

        # ── STEP 1: Collect required field names from the compiled graph ──────
        # Include both condition fields AND formula variables so the LLM
        # extracts everything the engine needs for a complete evaluation.
        _BUILTINS = {
            "math", "min", "max", "abs", "round", "int",
            "float", "str", "True", "False", "None", "sum", "sorted", "bool", "len",
        }
        condition_fields: set[str] = {
            cond.field
            for rule in self.graph.rules
            for cond in rule.conditions
        }
        formula_fields: set[str] = {
            var
            for rule in self.graph.rules
            for var in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", rule.action.formula)
            if var not in _BUILTINS
        }
        required_fields = list(condition_fields | formula_fields)

        log.info("[INFERENCE] Extracting facts for domain='%s' fields=%s",
                 self.domain, required_fields)

        extracted = extract_facts(
            user_input,
            domain_hint=self.domain,
            required_fields=required_fields,
        )
        log.info("[INFERENCE] Intent: %s | Facts: %s", extracted.intent, extracted.facts)

        # ── STEP 2: DACL Rete Engine (deterministic — NO LLM) ────────────────
        audit = self.engine.execute(
            facts=extracted.facts,
            query=user_input,
            intent=extracted.intent,
            timestamp=timestamp,
        )

        # ── STEP 2b: Dispatch durable side-effect actions ────────────────────
        # Idempotency key derived from timestamp+query — replaying the same
        # query never re-triggers already-succeeded actions.
        import hashlib
        decision_id = hashlib.sha256(
            f"{timestamp}:{user_input}".encode()
        ).hexdigest()[:16]

        for rule_result in audit.rules_evaluated:
            if rule_result.matched and rule_result.output_value is not None:
                rule_obj = next(
                    (r for r in self.graph.rules if r.rule_id == rule_result.rule_id),
                    None,
                )
                if rule_obj:
                    global_dispatcher.dispatch(
                        decision_id=decision_id,
                        rule_id=rule_result.rule_id,
                        output_field=rule_obj.action.output_field,
                        output_value=rule_result.output_value,
                        facts=audit.extracted_facts,
                    )


        success      = audit.winning_rule_id is not None
        final_output = audit.final_output

        # Detect FormulaError sentinels serialised as repr strings in output
        # (engine serialises them to repr() before storing in final_output)
        missing_vars: list[str] = [
            str(k)
            for k, v in final_output.items()
            if not str(k).startswith("_") and isinstance(v, str)
            and v.startswith("[FormulaError:")
        ]

        if missing_vars:
            vars_str = ", ".join(set(missing_vars))
            answer   = (
                f"I matched your query against the {self.domain} policy, but "
                f"I'm missing critical information to compute the result: **{vars_str}**. "
                "Could you please provide these details?"
            )
            success = False
            final_output["_missing_variables"] = list(set(missing_vars))

        elif audit.winning_rule_id:
            output_str = ", ".join(
                f"{k} = {v}"
                for k, v in final_output.items()
                if not str(k).startswith("_")
            )
            if audit.chain_depth > 0:
                chain_str = " → ".join(audit.chained_rules)
                answer = f"Forward chain executed [{chain_str}]: {output_str}"
            else:
                answer = f"Match found ({audit.winning_rule_id}): {output_str}"

        elif final_output:
            hint = final_output.get("_system_hint", "")
            # Extract structured missing field list from hint if present
            if hint:
                m = re.search(r"required missing facts: (.*)\. Providing", hint)
                if m:
                    missing_fields = [f.strip() for f in m.group(1).split(",")]
                    final_output["_missing_variables"] = missing_fields

            output_str = ", ".join(
                f"{k} = {v}"
                for k, v in final_output.items()
                if not str(k).startswith("_")
            )
            answer = (
                f"{hint} (Current default: {output_str})" if hint
                else f"Using default policy rates: {output_str}"
            )

        else:
            answer = "No matching rule found, and no default policy is defined for these facts."

        return DACLResponse(
            success=success,
            answer=answer,
            output=final_output,
            audit=audit,
        )
