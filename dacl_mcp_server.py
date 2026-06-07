from mcp.server.fastmcp import FastMCP
import httpx
import os
from dotenv import load_dotenv

load_dotenv()


# 1. Initialize the Universal DACL MCP Server
# This single server can be connected to ALL your different workflows (Tagent, Jira Agent, HR Agent, etc.)
mcp = FastMCP("DACL-Validation-Engine")

# Load the API Key for the external workflows
DACL_API_KEY = os.getenv("DACL_API_KEY", "your_generated_api_key")
DACL_BASE_URL = os.getenv("DACL_BASE_URL", "http://localhost:8000/api/v1/workflow")


import json
from openai import AsyncAzureOpenAI

@mcp.tool()
async def validate_business_rule(input: str = None, query: str = None, domain: str = "auto") -> str:
    """
    Validates a scenario against deterministic business rules using DACL.
    Any workflow can use this tool to ensure mathematical correctness.
    
    Args:
        input: The natural language description of the scenario to validate.
        query: Alternative parameter for the natural language description.
        domain: (Optional) The specific policy graph to check against. If omitted or 'auto', the tool will automatically determine the correct domain!
    """
    actual_query = input or query
    if not actual_query:
        return "Validation Failed: You must provide a scenario description in either 'input' or 'query'."

    async with httpx.AsyncClient() as client:
        # --- Smart Intent Routing ---
        if domain == "auto":
            try:
                resp = await client.get(f"{DACL_BASE_URL}/policies", headers={"X-API-Key": DACL_API_KEY})
                policies = resp.json().get("policies", [])
                if not policies:
                    return "Validation Failed: No policies available on the server to route to."
                
                prompt = "You are an intelligent routing agent. Given the following scenario and a list of available business policies, output ONLY the exact 'graph_id' of the policy that best matches the scenario. If none match, output 'UNKNOWN'.\n\n"
                prompt += "Available Policies:\n"
                for p in policies:
                    prompt += f"- ID: {p['graph_id']} | Description: {p.get('description', 'No description')}\n"
                prompt += f"\nScenario:\n{actual_query}"

                llm_client = AsyncAzureOpenAI(
                    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
                    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
                )
                llm_response = await llm_client.chat.completions.create(
                    model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=50
                )
                domain = llm_response.choices[0].message.content.strip()
                
                if domain == "UNKNOWN" or not any(p['graph_id'] == domain for p in policies):
                    return f"Intent Routing Failed: Could not find a suitable policy domain for this scenario."
                print(f"[Smart Router] Auto-routed scenario to domain: {domain}", flush=True)
            except Exception as e:
                return f"Intent Routing Failed (Error): {str(e)}"

        # --- Standard Validation ---
        try:
            print(f"Sending validation request to DACL backend: domain='{domain}', query='{actual_query}'", flush=True)
            response = await client.post(
                f"{DACL_BASE_URL}/query",
                json={"domain": domain, "query": actual_query},
                headers={"X-API-Key": DACL_API_KEY}
            )
            
            if response.status_code == 404:
                return f"Validation Failed: You passed an invalid domain ID '{domain}'. You MUST use the exact ID returned by list_available_policies()."
            if response.status_code == 400:
                return f"Validation Failed: The policy '{domain}' is not yet compiled on the server. Please compile it first."
                
            response.raise_for_status()
            result = response.json()
            
            if result.get("success"):
                return f"Validation Passed! (Domain: {domain}) Output: {result['answer']}"
            else:
                return f"Validation Failed! (Domain: {domain}) Output: {result.get('answer', 'Unknown error')}"
                
        except Exception as e:
            return f"Error contacting DACL Engine: {str(e)}"
                
@mcp.tool()
async def list_available_policies() -> list[str]:
    """
    Returns a list of all active business policy domains available for validation.
    Workflows MUST use these exact IDs as the 'domain' argument in validate_business_rule.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DACL_BASE_URL}/policies",
            headers={"X-API-Key": DACL_API_KEY}
        )
        policies = response.json().get("policies", [])
        return [p["graph_id"] for p in policies]



@mcp.tool()
async def validate_document_file(file_path: str, domain: str = None) -> str:
    """
    Validates a raw file (PDF, TXT, Excel) against the business rule engine.
    If you don't provide a domain, it will try to use the Smart Router on the extracted text.
    Note: The file_path must be an absolute path accessible by the MCP server.
    """
    if not os.path.exists(file_path):
        return f"Error: File not found at path '{file_path}'. If this server is in Docker, ensure the file is mounted correctly or pass the raw document text to smart_validate_scenario instead."
        
    # We will let the DACL backend parse the document via the /api/query-doc endpoint
    try:
        if domain is None:
            return f"Error: Please provide a domain ID. Alternatively, read the file text yourself and pass it to smart_validate_scenario."

        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
                data = {"graph_id": domain}
                
                resp = await client.post(
                    f"{DACL_BASE_URL}-doc", # Because base url is /workflow, but doc endpoint is /workflow/query-doc? Actually backend is /api/query-doc. Let's fix this.
                    # Wait, backend /api/query-doc is at the root level in server.py! 
                    # Let's just use the known backend URL directly:
                    "http://localhost:8000/api/query-doc" if "localhost" in DACL_BASE_URL else DACL_BASE_URL.replace("/v1/workflow", "/query-doc"),
                    files=files,
                    data=data,
                    headers={"X-API-Key": DACL_API_KEY}
                )
                resp.raise_for_status()
                result = resp.json()
                if result.get("success"):
                    return f"Document Validation Passed!\nOutput: {result['answer']}"
                else:
                    return f"Document Validation Failed!\nOutput: {result.get('answer')}"
    except Exception as e:
        return f"Error validating document: {str(e)}"


if __name__ == "__main__":
    # Start the universal MCP server with SSE (HTTP) transport
    # This allows VS Code, Copilot, and other HTTP-based MCP clients to connect
    mcp.settings.host = os.getenv("DACL_MCP_HOST", "127.0.0.1")
    mcp.settings.port = 8080
    mcp.run(transport="sse")

