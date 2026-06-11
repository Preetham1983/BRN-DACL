from mcp.server.fastmcp import FastMCP
import httpx
import os
import base64
import json
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncAzureOpenAI

load_dotenv()


# 1. Initialize the Universal DACL MCP Server
# This single server can be connected to ALL your different workflows (Tagent, Jira Agent, HR Agent, etc.)
mcp = FastMCP("DACL-Validation-Engine")

# Load the API Key for the external workflows
DACL_API_KEY = os.getenv("DACL_API_KEY", "your_generated_api_key")
DACL_BASE_URL = os.getenv("DACL_BASE_URL", "http://localhost:8000/api/v1/workflow")


# ─────────────────────────────────────────────────────────────────────────────
# Schema Generator Helper
# ─────────────────────────────────────────────────────────────────────────────
def generate_graph_schema(graph_data: dict) -> dict:
    """
    Generates a JSON schema of variables required by the rules in the graph data.
    Matches the schema extraction logic of the main FastAPI server.
    """
    _BUILTINS = {
        "math", "min", "max", "abs", "round", "int",
        "float", "str", "True", "False", "None", "sum", "sorted", "bool", "len",
    }
    
    properties = {}
    
    for rule in graph_data.get("rules", []):
        # Conditions
        for cond in rule.get("conditions", []):
            field = cond.get("field")
            val = cond.get("value")
            if field and field not in properties:
                # Infer type from value
                field_type = "string"
                if isinstance(val, int):
                    field_type = "integer"
                elif isinstance(val, float):
                    field_type = "number"
                elif isinstance(val, bool):
                    field_type = "boolean"
                
                properties[field] = {
                    "type": field_type,
                    "description": f"Extracted automatically from text."
                }
                
        # Formula Variables from action
        action = rule.get("action", {})
        formula = action.get("formula", "")
        if formula:
            formula_vars = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", str(formula))
            for var in formula_vars:
                if var not in _BUILTINS and var not in properties:
                    properties[var] = {
                        "type": "number",
                        "description": "Required for mathematical formulas."
                    }

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": f"{graph_data.get('graph_id', 'unknown')} Input Schema",
        "type": "object",
        "properties": properties,
        "required": list(properties.keys())
    }
    return schema


async def _get_policy_schema_by_id(graph_id: str) -> str:
    """
    Internal helper to fetch or generate the schema for a specific graph_id.
    """
    # 1. Attempt to fetch from FastAPI backend
    async with httpx.AsyncClient() as client:
        try:
            url = DACL_BASE_URL.replace("/v1/workflow", f"/schema/{graph_id}")
            resp = await client.get(url, headers={"X-API-Key": DACL_API_KEY}, timeout=2.0)
            if resp.status_code == 200:
                return json.dumps(resp.json(), indent=2)
        except Exception:
            pass
            
    # 2. Fallback to parsing the precompiled JSON file on disk
    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        path = base_dir / "compiled" / f"{graph_id}.json"
        if not path.exists():
            raise ValueError(f"Policy graph '{graph_id}' not found in compiled directory.")
        
        with open(path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
            
        schema = generate_graph_schema(graph_data)
        return json.dumps(schema, indent=2)
    except Exception as e:
        raise ValueError(f"Failed to load or generate schema for '{graph_id}': {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# MCP Resources
# ─────────────────────────────────────────────────────────────────────────────
@mcp.resource("dacl://policies/{graph_id}/schema", name="DACL Policy Schema Template", description="Returns the JSON schema of variables used in the specified policy graph")
async def get_policy_schema_template(graph_id: str) -> str:
    """
    Returns the JSON schema of variables used in the specified policy graph.
    """
    return await _get_policy_schema_by_id(graph_id)


@mcp.resource("dacl://policies/freight_policy_graph/schema", name="Freight Policy Schema", description="Returns the JSON schema of variables used in the freight policy graph")
async def get_freight_policy_schema() -> str:
    """
    Returns the JSON schema of variables used in the freight policy graph.
    """
    return await _get_policy_schema_by_id("freight_policy_graph")


# ─────────────────────────────────────────────────────────────────────────────
# MCP Prompts
# ─────────────────────────────────────────────────────────────────────────────
@mcp.prompt(name="explain-policy-decision")
def explain_policy_decision(winning_rule_id: str, audit_clause: str, facts: str) -> str:
    """
    Explains a policy decision based on the winning rule, the facts of the scenario, and the policy's audit clause.
    """
    return (
        f"Please explain the following policy decision in detail:\n"
        f"Winning Rule: {winning_rule_id}\n"
        f"Audit Clause: {audit_clause}\n"
        f"Input Facts/Scenario: {facts}\n\n"
        f"Provide a clear, natural language explanation of why this rule was matched and what the final decision means."
    )


@mcp.prompt(name="draft-dacl-rules")
def draft_dacl_rules(policy_text: str) -> str:
    """
    Drafts DACL logic/rules from a natural language policy text.
    """
    return (
        f"Given the following business policy document, write the matching DACL logic and rules. "
        f"For each rule, identify:\n"
        f"1. A unique rule ID\n"
        f"2. A priority value\n"
        f"3. The conditions (field, operator, value) and condition logic (AND/OR)\n"
        f"4. The action (output field, formula, description)\n"
        f"5. The audit clause referencing the specific policy section.\n\n"
        f"Policy Text:\n{policy_text}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MCP Tools
# ─────────────────────────────────────────────────────────────────────────────
@mcp.tool()
async def validate_scenario(input: str = None, query: str = None, domain: str = "auto") -> str:
    """
    Validates a natural language scenario description against deterministic business rules using DACL.
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
async def validate_business_rule(input: str = None, query: str = None, domain: str = "auto") -> str:
    """
    Validates a scenario against deterministic business rules using DACL (Legacy alias for validate_scenario).
    
    Args:
        input: The natural language description of the scenario to validate.
        query: Alternative parameter for the natural language description.
        domain: (Optional) The specific policy graph to check against. If omitted or 'auto', the tool will automatically determine the correct domain!
    """
    return await validate_scenario(input=input, query=query, domain=domain)


@mcp.tool()
async def list_available_policies() -> list[str]:
    """
    Returns a list of all active business policy domains available for validation.
    Workflows MUST use these exact IDs as the 'domain' argument in validate_business_rule/validate_scenario.
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
        
    try:
        if domain is None:
            return f"Error: Please provide a domain ID. Alternatively, read the file text yourself and pass it to smart_validate_scenario."

        async with httpx.AsyncClient() as client:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
                data = {"graph_id": domain}
                
                url = "http://localhost:8000/api/query-doc" if "localhost" in DACL_BASE_URL else DACL_BASE_URL.replace("/v1/workflow", "/query-doc")
                resp = await client.post(
                    url,
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


@mcp.tool()
async def validate_document_base64(base64_content: str, filename: str, domain: str) -> str:
    """
    Validates a document (PDF, TXT, Excel) provided as a base64 string against a business rule domain.
    
    Args:
        base64_content: The base64-encoded string of the document file.
        filename: The name of the file (including extension e.g., 'invoice.pdf').
        domain: The specific policy graph/domain ID to validate against.
    """
    try:
        content_bytes = base64.b64decode(base64_content)
    except Exception as e:
        return f"Error: Failed to decode base64 content: {str(e)}"
        
    try:
        async with httpx.AsyncClient() as client:
            files = {"file": (filename, content_bytes, "application/octet-stream")}
            data = {"graph_id": domain}
            
            url = "http://localhost:8000/api/query-doc" if "localhost" in DACL_BASE_URL else DACL_BASE_URL.replace("/v1/workflow", "/query-doc")
            resp = await client.post(
                url,
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
        return f"Error validating base64 document: {str(e)}"


if __name__ == "__main__":
    # Detect transport mode:
    # Default to 'sse' if DACL_MCP_HOST is defined (standard in Docker setup)
    # or if DACL_MCP_TRANSPORT is explicitly set to 'sse'. Otherwise, run using 'stdio'.
    transport = os.getenv("DACL_MCP_TRANSPORT", "").lower()
    
    if not transport:
        if "DACL_MCP_HOST" in os.environ or os.getenv("DACL_MCP_PORT"):
            transport = "sse"
        else:
            transport = "stdio"
            
    if transport == "sse":
        mcp.settings.host = os.getenv("DACL_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.getenv("DACL_MCP_PORT", "8080"))
        print(f"Starting DACL MCP Server using SSE transport on {mcp.settings.host}:{mcp.settings.port}...", flush=True, file=sys.stderr)
        mcp.run(transport="sse")
    else:
        # stdio is default for local CLI and inspector usage
        print("Starting DACL MCP Server using stdio transport...", flush=True, file=sys.stderr)
        mcp.run(transport="stdio")
