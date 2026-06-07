import json
import os

def convert_structured_rules_to_dacl(input_txt_path, output_json_path, max_rules=10000):
    print(f"Reading rules from {input_txt_path} ...")
    
    rules = []
    
    with open(input_txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
                
            parts = line.split('|')
            if len(parts) != 4:
                continue
                
            rule_id, domain, cond_str, act_str = parts
            
            # Parse the conditions (e.g., user_role=admin,integration=teams)
            conditions = []
            for cond in cond_str.split(','):
                if '=' in cond:
                    k, v = cond.split('=', 1)
                    conditions.append({
                        "field": k.strip(),
                        "operator": "==",
                        "value": v.strip()
                    })
                    
            # Parse the actions (e.g., allowed=yes,auto_execute=yes)
            # In DACL, we can bundle these into a single JSON string output formula
            action_dict = {}
            for act in act_str.split(','):
                if '=' in act:
                    k, v = act.split('=', 1)
                    action_dict[k.strip()] = v.strip()
                    
            # Build the DACL JSON Rule
            rule = {
                "rule_id": rule_id,
                "description": f"Exhaustive matrix rule for {cond_str}",
                "priority": 100,
                "conditions": conditions,
                "condition_logic": "AND",
                "action": {
                    "output_field": "decision",
                    # Return a JSON string so Tagent can parse all the action parameters
                    "formula": f"'{json.dumps(action_dict)}'", 
                    "description": "Auto-mapped from exhaustive file"
                },
                "audit_clause": f"Batch Import {rule_id}",
                "temporal_from": None,
                "temporal_to": None
            }
            
            rules.append(rule)
            
            if len(rules) >= max_rules:
                print(f"Reached limit of {max_rules} rules. Stopping here for demonstration.")
                break

    # Build the final Graph JSON
    import datetime
    policy = {
        "graph_id": "tagent_exhaustive_policy",
        "version": "v1.0.0",
        "domain": "agents",
        "description": "Exhaustive matrix policy for evaluating Tagent AI agent workflows, including user roles (admin), integrations (Teams, Jira), action_types (read/write), and time contexts (business_hours, after_hours).",
        "rules": rules,
        "optimization_strategy": "rete",
        "compiled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "company": "default"
    }
    
    print(f"Writing {len(rules)} rules to {output_json_path} ...")
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(policy, f, indent=2)
        
    print("Done! The Rete engine will automatically load this compiled file.")

if __name__ == "__main__":
    input_file = "sample_docs/tagent_business_rules_1M.txt"
    output_file = "compiled/tagent_exhaustive_policy.json"
    
    # We will process 10,000 rules instantly (you can change this to 1,000,000 later)
    convert_structured_rules_to_dacl(input_file, output_file, max_rules=10000)
