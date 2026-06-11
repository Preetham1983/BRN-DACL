import React from 'react';
import { 
  Network, 
  Database, 
  Wrench, 
  MessageSquare, 
  TerminalSquare, 
  CheckCircle2, 
  Server,
  Code2
} from 'lucide-react';

export default function McpDocs() {
  return (
    <div className="animate-fade-in" style={{ paddingBottom: '2rem' }}>
      <div style={{ marginBottom: '2.5rem' }}>
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '2.5rem', marginBottom: '1rem' }}>
          <Network size={36} color="#6366f1" />
          MCP Integration Hub
        </h1>
        <p style={{ fontSize: '1.1rem', maxWidth: '850px', color: 'var(--text-secondary)' }}>
          Connect your external AI workflows (LangGraph, CrewAI, AutoGen) to the DACL Deterministic Engine via the Model Context Protocol (MCP). 
          Bypass LLM hallucinations by routing complex logic and math through strict, auditable enterprise policies.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem', marginBottom: '3rem' }}>
        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
            <div style={{ padding: '0.6rem', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '10px', color: '#6366f1', display: 'flex' }}>
              <Database size={24} />
            </div>
            <h3 style={{ margin: 0, fontSize: '1.3rem' }}>Resources</h3>
          </div>
          <div className="badge badge-primary" style={{ alignSelf: 'flex-start', marginBottom: '1.25rem', fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>dacl://policies/[domain]/schema</div>
          <p style={{ flex: 1, fontSize: '0.95rem', margin: 0 }}>
            <strong style={{ color: '#EAEAEA' }}>The Data Gathering Checklist.</strong> Workflows read this dynamic JSON schema to understand exactly what facts (e.g., age, weight) they must extract from the user before running an evaluation.
          </p>
        </div>

        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
            <div style={{ padding: '0.6rem', background: 'rgba(16, 185, 129, 0.1)', borderRadius: '10px', color: '#10b981', display: 'flex' }}>
              <Wrench size={24} />
            </div>
            <h3 style={{ margin: 0, fontSize: '1.3rem' }}>Validation Tools</h3>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1.25rem' }}>
            <div className="badge badge-success" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>validate_scenario</div>
            <div className="badge badge-success" style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>validate_document_base64</div>
          </div>
          <p style={{ flex: 1, fontSize: '0.95rem', margin: 0 }}>
            <strong style={{ color: '#EAEAEA' }}>The Execution Engine.</strong> Pass collected facts or Base64-encoded files to these tools. Use <code style={{ color: '#10b981' }}>domain="auto"</code> to let our Azure OpenAI smart router automatically pick the correct policy graph!
          </p>
        </div>

        <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
            <div style={{ padding: '0.6rem', background: 'rgba(245, 158, 11, 0.1)', borderRadius: '10px', color: '#f59e0b', display: 'flex' }}>
              <MessageSquare size={24} />
            </div>
            <h3 style={{ margin: 0, fontSize: '1.3rem' }}>Prompts</h3>
          </div>
          <div className="badge badge-warning" style={{ alignSelf: 'flex-start', marginBottom: '1.25rem', fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>explain-policy-decision</div>
          <p style={{ flex: 1, fontSize: '0.95rem', margin: 0 }}>
            <strong style={{ color: '#EAEAEA' }}>The Empathy Layer.</strong> Gives your agent the perfect formatting instructions to translate complex Rete-engine audit trails into simple, human-readable explanations.
          </p>
        </div>
      </div>

      <h2 style={{ fontSize: '1.8rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <Server size={28} color="#EAEAEA" />
        Connection Setup
      </h2>
      
      <div className="glass-panel" style={{ padding: '2.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '1.25rem', marginBottom: '2.5rem', paddingBottom: '2rem', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <CheckCircle2 size={28} color="#10b981" style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <h4 style={{ margin: 0, fontSize: '1.2rem', color: '#EAEAEA', marginBottom: '0.5rem' }}>Active SSE Endpoint</h4>
            <p style={{ margin: 0, fontSize: '1rem', color: 'var(--text-secondary)' }}>
              The DACL MCP server is actively running on your local network. External AI workflows do not need local Python scripts; they connect directly to the Server-Sent Events (SSE) endpoint: <br />
              <code style={{ background: 'rgba(0,0,0,0.3)', padding: '6px 12px', borderRadius: '6px', color: '#6366f1', marginTop: '12px', display: 'inline-block', border: '1px solid rgba(99, 102, 241, 0.2)' }}>http://localhost:8080/sse</code>
            </p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '2rem' }}>
          
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <h4 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', color: '#EAEAEA', fontSize: '1.1rem' }}>
              <TerminalSquare size={20} color="#6366f1" />
              Python (LangChain / Native)
            </h4>
            
            <div className="code-window" style={{ flex: 1, minHeight: '380px' }}>
              <div className="code-window-header">
                <div className="code-window-dots">
                  <div className="code-window-dot red"></div>
                  <div className="code-window-dot yellow"></div>
                  <div className="code-window-dot green"></div>
                </div>
                <div className="code-window-title">main.py</div>
              </div>
              <div className="code-window-body custom-scrollbar">
                <pre><code>{`from mcp import ClientSession
from mcp.client.sse import sse_client
import asyncio

async def run_workflow():
    # Connect via SSE Transport
    async with sse_client("http://localhost:8080/sse") as transport:
        async with ClientSession(transport) as session:
            await session.initialize()
            
            # Smart Routing: Pass facts, let MCP pick the policy
            result = await session.call_tool(
                "validate_scenario",
                arguments={
                    "query": "1.2kg package going 600km.",
                    "domain": "auto"
                }
            )
            print("DACL Engine Output:", result)

asyncio.run(run_workflow())`}</code></pre>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <h4 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', color: '#EAEAEA', fontSize: '1.1rem' }}>
              <Code2 size={20} color="#10b981" />
              Node.js / TypeScript
            </h4>
            
            <div className="code-window" style={{ flex: 1, minHeight: '380px' }}>
              <div className="code-window-header">
                <div className="code-window-dots">
                  <div className="code-window-dot red"></div>
                  <div className="code-window-dot yellow"></div>
                  <div className="code-window-dot green"></div>
                </div>
                <div className="code-window-title">agent.ts</div>
              </div>
              <div className="code-window-body custom-scrollbar">
                <pre><code>{`import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";

async function connectToDacl() {
  const transport = new SSEClientTransport(
    new URL("http://localhost:8080/sse")
  );
  
  const client = new Client(
    { name: "hr-agent", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  await client.connect(transport);
  
  const result = await client.callTool({
    name: "validate_scenario",
    arguments: { 
      query: "User has 3 years tenure, requesting 5 days leave." 
    }
  });
  
  console.log(result);
}

connectToDacl();`}</code></pre>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
