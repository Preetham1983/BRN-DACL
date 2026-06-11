import asyncio
import os
import sys

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dacl_mcp_server import list_available_policies

async def test():
    print("Testing DACL MCP Server directly...")
    
    # 1. Test listing policies
    print("\n--- Listing Policies ---")
    try:
        policies = await list_available_policies()
        print(f"Policies returned: {policies}")
    except Exception as e:
        print(f"Failed to list policies: {e}")

if __name__ == "__main__":
    # Ensure open mode is set for testing if no DB API key exists
    os.environ["DACL_OPEN_MODE"] = "true"
    asyncio.run(test())
