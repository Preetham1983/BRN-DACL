from dacl_agent.services.compiler import compile_policy
from pathlib import Path

txt = Path("temp/tagent_workflow_rules.txt").read_text(encoding="utf-8")
graph, _ = compile_policy(txt, "test_graph", "test")
print(f"Compiled successfully! Rule count: {len(graph.rules)}")
