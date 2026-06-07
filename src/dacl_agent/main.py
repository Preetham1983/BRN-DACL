# -*- coding: utf-8 -*-
"""
DACL Agent -- Rich Interactive CLI.

Demonstrates the full DACL workflow:
  1. COMPILE TIME: Business policy -> GPT-4o -> DACL JSON IR -> Rete network
  2. INFERENCE TIME: Query -> Lightweight LLM fact extraction -> Rete engine -> Deterministic result + Audit trail

Run: uv run python src/dacl_agent/main.py
"""
from __future__ import annotations
import sys
import io

# Force UTF-8 for Windows terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich import box

from dacl_agent.services.agent import DACLAgent

console = Console(highlight=True, emoji=False, force_terminal=True)

# ─────────────────────────────────────────────────────────────────────────────
# Example Business Policy - Freight / Transportation Pricing
# (This is the domain shown in the DACL workflow diagram)
# ─────────────────────────────────────────────────────────────────────────────
FREIGHT_POLICY = """
FREIGHT PRICING POLICY v2.3 - Effective 2026-01-01 to 2026-12-31

TIER CLASSIFICATION RULES:
--------------------------
Rule 1 (Tier A - Premium):
  IF weight > 1.0 kg AND distance > 500 km
  THEN tier = "A", apply premium surcharge.
  Formula: base_rate = 5.50 + (fuel_index - 4.00) * 0.30
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
  Formula: base_rate = 2.80, final_amount = base_rate * distance * weight
  Source: Section 3.3 - Economy Freight Schedule

FUEL SURCHARGE ADDITION:
  final_amount = base_rate * distance * weight
  Source: Section 4.1 - Fuel Surcharge Calculation

DEFAULT: If no rule matches, apply economy rate (Section 3.3).
"""

HR_LEAVE_POLICY = """
HR LEAVE APPROVAL POLICY - Version 1.5

LEAVE APPROVAL RULES:
--------------------
Rule 1 (Auto-Approve Short Leave):
  IF leave_days <= 2 AND tenure_years >= 1
  THEN decision = "auto_approved", notify_manager = False
  Source: HR Policy 2.1 - Short Leave Entitlement

Rule 2 (Manager Approval Required):
  IF leave_days > 2 AND leave_days <= 10
  THEN decision = "pending_manager_approval", notify_manager = True
  Source: HR Policy 2.2 - Standard Leave Approval

Rule 3 (HR Director Approval Required):
  IF leave_days > 10
  THEN decision = "pending_hr_director_approval"
  Source: HR Policy 2.3 - Extended Leave Approval

Rule 4 (Probation Block):
  IF tenure_years < 1
  THEN decision = "blocked_probation"
  Source: HR Policy 3.1 - Probation Period Restrictions

DEFAULT: Apply standard leave flow.
"""

POLICIES = {
    "freight": (FREIGHT_POLICY, "freight_pricing"),
    "hr":      (HR_LEAVE_POLICY, "hr_leave_policy"),
}


def print_header():
    console.print(Panel(
        Text.from_markup(
            "[bold cyan]DACL Enhanced Agent[/bold cyan]\n"
            "[dim]Deterministic AI Contract Logic -- Amortized Intelligence[/dim]\n\n"
            "[yellow]Baseline:[/yellow] Every query -> full LLM call -> non-deterministic result\n"
            "[green]DACL:[/green]     Compile ONCE -> Rete engine at inference -> deterministic + auditable\n"
            "[dim]Cost reduction: >90% | Auditability: Full trace | Same inputs = Same output always[/dim]"
        ),
        title="[bold white]*** DACL Agent Demo ***[/bold white]",
        border_style="bright_blue",
        padding=(1, 2),
    ))


def print_phase_header(phase: str, subtitle: str, color: str = "yellow"):
    console.print()
    console.print(Rule(f"[bold {color}]{phase}[/bold {color}] [dim]{subtitle}[/dim]"))


def print_dacl_graph(graph):
    console.print(f"\n[bold green][OK] Compiled DACL Graph:[/bold green] [cyan]{graph.graph_id}[/cyan] "
                  f"[dim]({graph.version})[/dim]")

    t = Table(
        title="DACL Rules -- Rete Network Nodes (Beta Nodes)",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )
    t.add_column("Rule ID", style="cyan", width=24)
    t.add_column("Priority", justify="center", width=10)
    t.add_column("Conditions (Logic)", width=40)
    t.add_column("Action Formula", width=42)
    t.add_column("Audit Clause", style="dim", width=26)

    for rule in sorted(graph.rules, key=lambda r: r.priority, reverse=True):
        logic = rule.condition_logic
        conds = f"\n[{logic}] ".join(
            f"{c.field} {c.operator} {c.value}" for c in rule.conditions
        )
        formula_short = rule.action.formula[:38] + ("..." if len(rule.action.formula) > 38 else "")
        t.add_row(
            rule.rule_id,
            str(rule.priority),
            conds,
            f"{rule.action.output_field} = {formula_short}",
            rule.audit_clause or "--",
        )

    console.print(t)


def print_inference_result(response):
    # --- Extracted Facts ---
    facts_table = Table(
        title="[INFERENCE STEP 1] Extracted Facts -- Lightweight LLM call",
        box=box.SIMPLE,
        header_style="bold blue",
    )
    facts_table.add_column("Field", style="cyan")
    facts_table.add_column("Value", style="white")
    for k, v in response.audit.extracted_facts.items():
        facts_table.add_row(k, str(v))
    console.print(facts_table)

    # --- Rete Evaluation ---
    eval_table = Table(
        title="[INFERENCE STEP 2] Rete Network Execution -- ZERO LLM -- Pure Deterministic",
        box=box.ROUNDED,
        header_style="bold yellow",
        show_lines=True,
    )
    eval_table.add_column("Rule", style="cyan", width=24)
    eval_table.add_column("Conditions Evaluated", width=50)
    eval_table.add_column("Matched", justify="center", width=10)
    eval_table.add_column("Output Value", width=28)

    for r in response.audit.rules_evaluated:
        cond_lines = []
        for c in r.conditions_evaluated:
            status = "[green]PASS[/green]" if c["passed"] else "[red]FAIL[/red]"
            cond_lines.append(
                f"  {c['field']} {c['operator']} {c['expected_value']} "
                f"(got: {c['fact_value']}) [{status}]"
            )
        cond_str = "\n".join(cond_lines)
        matched_icon = "[bold green]YES[/bold green]" if r.matched else "[red]NO[/red]"
        out_str = str(r.output_value) if r.output_value is not None else "--"
        eval_table.add_row(
            r.rule_id,
            Text.from_markup(cond_str),
            Text.from_markup(matched_icon),
            out_str,
        )

    console.print(eval_table)

    # --- Final Result Panel ---
    output_lines = "\n".join(
        f"  [cyan]{k}[/cyan] = [bold white]{v}[/bold white]"
        for k, v in response.output.items()
    )
    console.print(Panel(
        Text.from_markup(
            f"[bold green]*** DETERMINISTIC RESULT ***[/bold green]\n\n"
            f"[white]{response.answer}[/white]\n\n"
            f"[dim]Winning Rule :[/dim] [cyan]{response.audit.winning_rule_id or 'default'}[/cyan]\n"
            f"[dim]Audit Clause :[/dim] [yellow]{response.audit.audit_clause}[/yellow]\n"
            f"[dim]Engine Version:[/dim] {response.audit.engine_version}\n"
            f"[dim]Timestamp    :[/dim] {response.audit.timestamp}\n\n"
            f"[bold]Output Fields:[/bold]\n"
            f"{output_lines}"
        ),
        border_style="green",
        title="[bold]Result + Full Audit Trail[/bold]"
    ))


def run_demo(domain_key: str):
    policy_text, domain = POLICIES[domain_key]

    agent = DACLAgent(
        graph_id=f"{domain_key}_policy_graph",
        domain=domain,
        compiled_dir="compiled",
    )

    # --- COMPILE TIME ---
    print_phase_header(
        "PHASE 1: COMPILE TIME",
        "(Executed Once -- LLM translates policy text -> DACL graph -> saved to disk)",
        "yellow"
    )
    console.print(f"\n[dim]Policy preview (first 300 chars):[/dim]")
    console.print(f"[italic]{policy_text[:300].strip()}...[/italic]\n")

    graph = agent.compile(policy_text)
    print_dacl_graph(graph)

    # --- INFERENCE TIME ---
    print_phase_header(
        "PHASE 2: INFERENCE TIME",
        "(Executed many times -- Lightweight LLM fact extract + Pure Rete Engine -- No full LLM reasoning)",
        "cyan"
    )

    example_queries = {
        "freight": [
            "What is the final transportation charge for a 0.8kg package shipped 348km with fuel index 4.15?",
            "Calculate shipping cost: weight=1.2kg, distance=600km, fuel_index=4.5",
            "Shipping quote for a 0.3kg parcel, 150km distance, fuel_index=3.9",
        ],
        "hr": [
            "I need 3 days leave, I've been working here for 2 years",
            "Can I get 15 days off? I joined 6 months ago.",
            "1 day leave request from an employee with 5 years tenure",
        ]
    }

    console.print(f"\n[bold]Example queries for domain '{domain_key}':[/bold]")
    for i, q in enumerate(example_queries[domain_key], 1):
        console.print(f"  [dim]{i}.[/dim] {q}")
    console.print()

    while True:
        try:
            user_input = console.input("[bold cyan]Query (or 'quit'/'switch'): [/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break
        if user_input.lower() in ("switch", "s"):
            return True
        if not user_input:
            continue

        console.print()
        try:
            response = agent.query(user_input)
            print_inference_result(response)
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            import traceback
            traceback.print_exc()

    return False


def main():
    print_header()

    domain_key = "freight"
    console.print("\n[bold]Available domains:[/bold]")
    for k in POLICIES:
        console.print(f"  [cyan]{k}[/cyan]")

    try:
        choice = console.input("\n[bold]Select domain (freight/hr, default=freight): [/bold]").strip().lower()
    except (KeyboardInterrupt, EOFError):
        choice = ""

    if choice in POLICIES:
        domain_key = choice

    while True:
        switch = run_demo(domain_key)
        if not switch:
            break
        domain_key = "hr" if domain_key == "freight" else "freight"
        console.print(f"\n[yellow]Switching to domain: {domain_key}[/yellow]")

    console.print(Panel(
        "[bold green]DACL Agent session complete.[/bold green]\n"
        "[dim]Compiled graphs saved in ./compiled/ -- no recompilation needed on next run.[/dim]",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
