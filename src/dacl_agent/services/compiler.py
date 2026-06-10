"""
DACL Compiler — Phase 1 (Compile Time).

Takes business policy text and uses GPT-4o (once) to produce a validated
DACL executable graph that is saved to disk for reuse.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI

from dacl_agent.models.schemas import DACLGraph
from dacl_agent.services.verifier import DACLVerifier, VerificationResult

load_dotenv()
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Azure OpenAI client (EPAM DIAL) + LangSmith Wrapper
# ─────────────────────────────────────────────────────────────────────────────
from langsmith import wrappers
client = wrappers.wrap_openai(
    AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
)

DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]

# ─────────────────────────────────────────────────────────────────────────────
# System prompt for LLM compiler
# ─────────────────────────────────────────────────────────────────────────────
COMPILER_SYSTEM_PROMPT = """
You are a DACL (Deterministic AI Contract Logic) Compiler.

Your job is to translate business policy text into a structured DACL JSON graph.

Output ONLY valid JSON matching this schema exactly:
{
  "graph_id": "unique_snake_case_id",
  "version": "v1.0.0",
  "domain": "domain_name",
  "description": "...",
  "optimization_strategy": "rete",
  "default_action": {
    "output_field": "tier",
    "formula": "'C'",
    "description": "Default fallback tier"
  },
  "rules": [
    {
      "rule_id": "rule_name",
      "description": "...",
      "priority": 100,
      "condition_logic": "AND",
      "conditions": [
        {"field": "weight", "operator": ">", "value": 0.5},
        {"field": "distance", "operator": ">", "value": 300}
      ],
      "action": {
        "output_field": "result",
        "formula": "...",
        "description": "..."
      },
      "audit_clause": "Policy Section X.Y",
      "temporal_from": null,
      "temporal_to": null
    }
  ]
}

PRIORITY ASSIGNMENT RULES (follow strictly — priorities must be unique integers):
  1. Rules with MORE conditions get HIGHER priority (more specific = higher number).
  2. Rules with equality (==) conditions get +10 over equivalent range conditions.
  3. Among rules with equal condition count, order them as they appear in the policy text.
  4. Every rule must have a UNIQUE priority. No two rules may share the same value.
  5. Start from priority=200 for the most specific rule, decrement by 10 for each less-specific rule.

COMPILATION RULES:
  - Extract ALL distinct business rules from the policy text.
  - Each condition field must be a simple snake_case fact name (e.g. weight, distance, fuel_index).
  - Formula must be a Python-evaluable string using only the fact field names.
    Example: "4.10 + (fuel_index - 4.10) * 0.22"
  - If a rule sets multiple output values (e.g. risk_tier AND premium_rate), create one rule per
    output field, with the second rule having a slightly lower priority and referencing the
    first rule's output in its formula where needed.
  - Output ONLY the raw JSON object, no markdown, no explanation.
""".strip()


def compile_policy(
    policy_text: str,
    graph_id: str,
    domain: str,
    strict_verify: bool = False,
) -> tuple[DACLGraph, VerificationResult]:
    """COMPILE TIME: Feed business policy text to LLM (once).

    After LLM compilation, runs the Z3 verifier to detect rule conflicts,
    dead rules, and priority collisions before the graph is deployed.

    Args:
        policy_text:   The raw policy document text.
        graph_id:      Unique identifier for the compiled graph.
        domain:        Business domain name.
        strict_verify: If True, raises ValueError on any blocking verification issue.
                       If False (default), logs warnings but still returns the graph.

    Returns:
        Tuple of (DACLGraph, VerificationResult).
    """
    import re
    
    # ── PROGRAMMATIC BYPASS FOR LARGE STRUCTURED FILES ────────────────────────
    # If we detect a large structured file (e.g., > 100 rules), bypass LLM to avoid token limits
    lines = [line.strip() for line in policy_text.splitlines() if line.strip()]
    
    def is_rule_line(l):
        if l.count('|') != 2 or l.startswith('#') or l.startswith('=') or l.startswith('─'):
            return False
        first_part = l.split('|')[0].strip()
        # Must look like an ID, not "Format : RULE_ID"
        return re.match(r'^[A-Za-z0-9_-]+$', first_part) is not None

    structured_lines = [l for l in lines if is_rule_line(l)]
    
    if len(structured_lines) > 20:
        log.info("[COMPILE] Detected massive structured rule file (%d rules). Bypassing LLM...", len(structured_lines))
        rules = []
        base_priority = 20000
        
        for idx, line in enumerate(structured_lines):
            try:
                rule_id, cond_str, act_str = [p.strip() for p in line.split('|')]
                
                # Parse conditions
                conditions = []
                for cond in cond_str.split(','):
                    cond = cond.strip()
                    if not cond: continue
                    # Match field, operator, value
                    m = re.match(r'^([a-zA-Z0-9_]+)\s*(>=|<=|==|!=|>|<|=)\s*(.*)$', cond)
                    if m:
                        field, op, val = m.groups()
                        if op == '=': op = '=='
                        conditions.append({"field": field, "operator": op, "value": val})
                        
                # Parse actions
                action_dict = {}
                for act in act_str.split(','):
                    act = act.strip()
                    if not act: continue
                    m = re.match(r'^([a-zA-Z0-9_]+)\s*=\s*(.*)$', act)
                    if m:
                        action_dict[m.group(1)] = m.group(2)
                        
                rules.append({
                    "rule_id": rule_id,
                    "description": f"Programmatic import rule {rule_id}",
                    "priority": base_priority - idx,
                    "conditions": conditions,
                    "condition_logic": "AND",
                    "action": {
                        "output_field": "decision",
                        "formula": f"'{json.dumps(action_dict)}'",
                        "description": "Auto-mapped from structured file"
                    },
                    "audit_clause": f"Batch Import {rule_id}",
                    "temporal_from": None,
                    "temporal_to": None
                })
            except Exception as e:
                log.warning("Failed to parse rule line: %s (%s)", line, e)
                
        data = {
            "graph_id": graph_id,
            "version": "v1.0.0",
            "domain": domain,
            "description": "Programmatically compiled structured policy",
            "optimization_strategy": "rete",
            "default_action": {
                "output_field": "decision",
                "formula": "'{}'",
                "description": "Default fallback"
            },
            "rules": rules,
            "compiled_at": datetime.now(timezone.utc).isoformat()
        }
    else:
        # ── LLM COMPILATION FOR NATURAL LANGUAGE ───────────────────────────────
        log.info("[COMPILE] Sending policy to GPT-4o for DACL compilation...")
    
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            temperature=0,          # deterministic compilation
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": COMPILER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Compile this business policy into a DACL graph:\n\n{policy_text}",
                },
            ],
        )
    
        raw_json = response.choices[0].message.content
        data     = json.loads(raw_json)
    
        # Inject compile metadata
        data["graph_id"]    = graph_id
        data["domain"]      = domain
        data["compiled_at"] = datetime.now(timezone.utc).isoformat()

    # Validate with Pydantic — catches malformed LLM output immediately
    graph = DACLGraph(**data)

    log.info("[COMPILE] OK \u2014 %d rules compiled into graph '%s'", len(graph.rules), graph_id)
    log.info("[COMPILE] Optimization strategy: %s", graph.optimization_strategy)

    # ── Z3 Static Verification ───────────────────────────────────────────────
    verifier = DACLVerifier()
    verification = verifier.verify(graph)

    if verification.has_blocking_issues:
        issues = [c.message for c in verification.conflicts if c.severity == "ERROR"]
        issues_str = "\n  - ".join(issues)
        log.error(
            "[COMPILE] Z3 verification found %d blocking issue(s) in '%s':\n  - %s",
            len(issues), graph_id, issues_str,
        )
        if strict_verify:
            raise ValueError(
                f"Policy graph '{graph_id}' failed Z3 verification with "
                f"{len(issues)} blocking issue(s):\n  - {issues_str}\n"
                "Fix the policy document and recompile."
            )
        log.warning(
            "[COMPILE] strict_verify=False \u2014 deploying despite verification issues. "
            "Set strict_verify=True to block deployment on conflicts."
        )
    else:
        log.info("[COMPILE] Z3 verification passed: %s", verification.summary())

    return graph, verification


def save_graph(graph: DACLGraph, output_dir: str = "compiled") -> Path:
    """Save compiled DACL graph to disk — never needs LLM again at inference time."""
    out  = Path(output_dir)
    out.mkdir(exist_ok=True)
    path = out / f"{graph.graph_id}.json"
    path.write_text(graph.model_dump_json(indent=2))
    log.info("[COMPILE] Graph saved to: %s", path)
    return path


def load_graph(graph_id: str, output_dir: str = "compiled") -> DACLGraph:
    """Load a pre-compiled DACL graph from disk."""
    path = Path(output_dir) / f"{graph_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No compiled graph found: {path}")
    data = json.loads(path.read_text())
    return DACLGraph(**data)
