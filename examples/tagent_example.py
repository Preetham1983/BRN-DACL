import requests

# -----------------------------------------------------------------------------
# THIS IS YOUR TAGENT WORKFLOW (Running on your AI Server)
# -----------------------------------------------------------------------------

# 1. This is the BRN Backend URL you paste into your Tagent workflow:
BRN_URL = "http://localhost:8000/api/v1/workflow/query"
BRN_API_KEY = "your_api_key_here"

def tagent_chatbot(user_message: str):
    print(f"USER: {user_message}")
    
    # Tagent wants to create a Jira ticket, but it must ask BRN first!
    print("TAGENT: Asking BRN for permission...")
    
    # Tagent sends the user's message to BRN
    response = requests.post(
        BRN_URL,
        headers={"X-API-Key": BRN_API_KEY},
        json={
            "domain": "agents", # Your compiled rules from the UI
            "query": user_message
        }
    )
    
    # BRN returns a JSON decision
    brn_decision = response.json()
    
    # How Tagent uses BRN's decision in the workflow:
    if brn_decision.get("requires_human_review"):
        print("TAGENT: Sorry, BRN flagged this. I need human approval before I can do that.\n")
        return
        
    if brn_decision.get("success") and brn_decision.get("output", {}).get("allowed") == "yes":
        print("TAGENT: BRN says YES! Executing my Jira creation code now...\n")
        # -> Tagent runs its normal code here
    else:
        print("TAGENT: BRN says NO! You are not allowed to do this.\n")

# Let's test it!
tagent_chatbot("I am an admin using the jira integration to create a task. I have very_high confidence, enterprise user_tier, and it is currently business_hours.")
