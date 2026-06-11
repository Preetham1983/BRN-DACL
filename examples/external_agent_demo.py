import os
import sys
import json
import urllib.request

# This script simulates an external AI agent or workflow (like a LangGraph node or Zapier webhook)
# interacting with the DACL agent to get deterministic business rule decisions.

# 1. Setup your API Key and Endpoint
# You can generate an API key from the DACL API Hub (http://localhost:5173/api-hub)
API_KEY = os.getenv("DACL_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "http://localhost:8000/api/v1/workflow"

def main():
    if API_KEY == "YOUR_API_KEY_HERE":
        print("❌ Please set your API key in the script or via DACL_API_KEY env var.")
        sys.exit(1)

    print("🤖 External Workflow Agent Initializing...")
    print("---------------------------------------")
    
    # 2. Check Available Policies
    print("\n🔍 Step 1: Checking active policies...")
    req = urllib.request.Request(f"{BASE_URL}/policies", headers={"X-API-Key": API_KEY})
    try:
        with urllib.request.urlopen(req) as response:
            policies = json.loads(response.read().decode())['policies']
            print(f"✅ Found {len(policies)} active policies.")
            for p in policies:
                print(f"   - {p['domain']} (ID: {p['graph_id']})")
    except Exception as e:
        print(f"❌ Failed to fetch policies: {e}")
        sys.exit(1)

    # 3. Simulate an Agent querying a policy
    # Imagine a user asked a chatbot: "How much to ship a 10kg box 800km?"
    # The chatbot forwards this to DACL for a deterministic calculation.
    query_text = "I need to ship a package. It weighs 10kg and the distance is 800km. The current fuel index is 4.5."
    domain_id = "freight_policy_graph" # Assuming the built-in freight policy exists

    print(f"\n🧠 Step 2: Querying the '{domain_id}' policy...")
    print(f"   Query: '{query_text}'")
    
    data = json.dumps({
        "domain": domain_id,
        "query": query_text
    }).encode('utf-8')
    
    req = urllib.request.Request(
        f"{BASE_URL}/query", 
        data=data, 
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            
            print("\n✅ Workflow Decision Received!")
            print("---------------------------------------")
            print(f"Status:  {'Success' if result['success'] else 'Failed'}")
            print(f"Answer:  {result['answer']}")
            print(f"Outputs: {json.dumps(result['output'], indent=2)}")
            print("\n📋 Engine Audit Trail:")
            print(f"Rules fired: {', '.join(result['audit']['chained_rules'])}")
            
            # Here, the external agent would use the result['output'] 
            # to reply to the user or trigger a downstream system (like Stripe or Jira).
            
    except urllib.error.HTTPError as e:
        print(f"❌ Query failed with status {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"❌ Query failed: {e}")

if __name__ == "__main__":
    main()
