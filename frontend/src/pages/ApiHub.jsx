import React, { useState, useEffect } from 'react';
import { Key, Plus, Trash2, Copy, CheckCircle, XCircle, Terminal } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as api from '../api';

export default function ApiHub() {
  const { user } = useAuth();
  const [apiKeys, setApiKeys] = useState([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyRole, setNewKeyRole] = useState('reader');
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [showNewKey, setShowNewKey] = useState(null);

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadKeys = async () => {
    try {
      const keys = await api.fetchApiKeys();
      setApiKeys(keys);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (user.role === 'admin') {
      loadKeys();
    }
  }, [user]);

  const handleCreateKey = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await api.createApiKey(newKeyName, newKeyRole);
      setShowNewKey(res.raw_key);
      setNewKeyName('');
      showToast('API Key generated successfully!', 'success');
      loadKeys();
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRevokeKey = async (id) => {
    if (!window.confirm("Are you sure you want to revoke this API key?")) return;
    try {
      await api.revokeApiKey(id);
      showToast('API Key revoked', 'success');
      loadKeys();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    showToast('Copied to clipboard!', 'success');
  };

  return (
    <div className="animate-fade-in" style={{ position: 'relative' }}>
      {toast && (
        <div className="animate-fade-in" style={{
          position: 'fixed', top: '30px', right: '30px', zIndex: 9999,
          background: toast.type === 'success' ? '#10b981' : '#ef4444',
          color: '#fff', padding: '12px 24px', borderRadius: '8px',
          boxShadow: '0 10px 25px rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', gap: '10px',
          fontWeight: 500
        }}>
          {toast.type === 'success' ? <CheckCircle size={20} /> : <XCircle size={20} />}
          {toast.message}
        </div>
      )}

      <div className="flex-between mb-4">
        <div>
          <h1 style={{ marginBottom: '0.5rem' }}>API Integration Hub</h1>
          <p style={{ margin: 0 }}>Connect your external AI agents and automated workflows to DACL</p>
        </div>
      </div>

      {user.role === 'admin' ? (
        <div className="glass-card mb-4" style={{ padding: '2rem' }}>
          <h2 className="mb-2 flex-between">
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div style={{ padding: '8px', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '8px', color: '#6366f1', display: 'flex' }}>
                <Key size={24} />
              </div>
              API Access Management
            </span>
          </h2>
          <p className="text-muted mb-4">Manage API keys for programmatic access to DACL endpoints.</p>
          
          {showNewKey && (
            <div className="glass-panel mb-4 animate-fade-in" style={{padding: '1.5rem', background: 'rgba(16, 185, 129, 0.05)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '12px'}}>
              <h3 className="text-success flex-center" style={{justifyContent: 'flex-start', gap: '0.75rem', marginBottom: '1rem'}}>
                <CheckCircle size={24} /> New API Key Created
              </h3>
              <p style={{ color: 'var(--text-secondary)' }}>Please copy this key now. For security reasons, it will not be shown again.</p>
              <div className="flex-between" style={{background: 'rgba(0,0,0,0.4)', padding: '1.25rem', borderRadius: '8px', marginTop: '1rem', border: '1px solid rgba(255,255,255,0.05)'}}>
                <code style={{fontSize: '1.2rem', color: '#6ee7b7', letterSpacing: '1px'}}>{showNewKey}</code>
                <button className="btn btn-secondary" onClick={() => copyToClipboard(showNewKey)}>
                  <Copy size={16} /> Copy
                </button>
              </div>
              <button className="btn btn-primary mt-4" onClick={() => setShowNewKey(null)}>I have saved it securely</button>
            </div>
          )}

          <div style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', gap: '2.5rem'}}>
            <div style={{flex: 2, overflowX: 'auto'}}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key Name</th>
                    <th>Permissions</th>
                    <th>Created At</th>
                    <th style={{textAlign: 'right'}}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map(k => (
                    <tr key={k.id}>
                      <td style={{fontWeight: 500, color: '#EAEAEA'}}>{k.name}</td>
                      <td>
                        <span className={`badge ${k.role === 'admin' ? 'badge-primary' : k.role === 'analyst' ? 'badge-warning' : 'badge-success'}`}>
                          {k.role ? k.role.toUpperCase() : 'UNKNOWN'}
                        </span>
                      </td>
                      <td className="text-muted">{new Date(k.created_at).toLocaleString()}</td>
                      <td style={{textAlign: 'right'}}>
                        <button className="btn-icon text-danger" onClick={() => handleRevokeKey(k.id)} title="Revoke Key">
                          <Trash2 size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {apiKeys.length === 0 && (
                    <tr><td colSpan="4" style={{textAlign: 'center', padding: '3rem'}}>No active API keys found. Generate one to get started.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div style={{flex: 1}}>
              <div className="glass-panel" style={{ padding: '2rem', border: '1px solid rgba(99, 102, 241, 0.2)', background: 'rgba(0,0,0,0.3)', boxShadow: '0 10px 30px rgba(0,0,0,0.3)' }}>
                <h3 className="mb-4" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#6366f1' }}>
                  <Plus size={20} /> Generate New Key
                </h3>
                <form onSubmit={handleCreateKey}>
                  <div className="form-group mb-4">
                    <label className="form-label" style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Integration Name</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      value={newKeyName} 
                      onChange={e => setNewKeyName(e.target.value)} 
                      required 
                      placeholder="e.g. Jenkins Pipeline, Zapier" 
                      style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)', height: '46px', fontSize: '1rem' }}
                    />
                  </div>
                  
                  <div className="form-group mb-4">
                    <label className="form-label" style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>Access Role</label>
                    <div style={{ position: 'relative' }}>
                      <select 
                        className="form-select" 
                        value={newKeyRole} 
                        onChange={e => setNewKeyRole(e.target.value)}
                        style={{
                          width: '100%', 
                          appearance: 'none', 
                          cursor: 'pointer',
                          background: 'rgba(0,0,0,0.4)',
                          border: '1px solid rgba(255,255,255,0.1)',
                          fontWeight: 500,
                          fontSize: '1rem',
                          height: '46px',
                          paddingLeft: '1rem'
                        }}
                      >
                        <option value="reader">Reader (Query Engine Only)</option>
                        <option value="analyst">Analyst (Query + Edit Rules)</option>
                        <option value="admin">Admin (Full System Access)</option>
                      </select>
                      <div style={{ position: 'absolute', right: '14px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-secondary)' }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                      </div>
                    </div>
                  </div>
                  
                  <button type="submit" className="btn btn-primary mt-2" style={{width: '100%', height: '46px', fontSize: '1rem', fontWeight: 600}} disabled={loading || !newKeyName}>
                    {loading ? 'Generating...' : 'Create Secret Key'}
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="glass-card mb-4 text-center" style={{padding: '3rem'}}>
          <Key size={48} color="#f59e0b" style={{marginBottom: '1rem'}} />
          <h3>Admin Access Required</h3>
          <p>Only administrators can generate and manage API keys.</p>
        </div>
      )}

      <div className="glass-card">
        <h2 className="mb-3"><Terminal size={24} style={{verticalAlign: 'bottom', marginRight: '0.5rem'}} /> REST API Usage</h2>
        <p>Integrate your AI workflows using the endpoints below. Include your API key in the header: <code>X-API-Key: dacl-...</code></p>

        <div className="mt-4">
          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-success" style={{marginRight: '0.5rem'}}>POST</span> /api/v1/workflow/query</h4>
            <p className="text-muted mt-2">Evaluate a natural language query against a policy graph.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto'}}>
{`curl -X POST "http://localhost:8000/api/v1/workflow/query" \\
  -H "X-API-Key: <your_key>" \\
  -H "Content-Type: application/json" \\
  -d '{
    "domain": "freight_policy_graph",
    "query": "I have a 1.2kg package going 600km."
  }'`}
            </pre>
          </div>

          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-success" style={{marginRight: '0.5rem'}}>POST</span> /api/v1/workflow/query-doc</h4>
            <p className="text-muted mt-2">Evaluate an uploaded document (PDF, TXT, Excel, CSV) against a policy graph.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto'}}>
{`curl -X POST "http://localhost:8000/api/v1/workflow/query-doc" \\
  -H "X-API-Key: <your_key>" \\
  -F "graph_id=freight_policy_graph" \\
  -F "file=@case_doc.pdf"`}
            </pre>
          </div>
          
          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-primary" style={{marginRight: '0.5rem'}}>GET</span> /api/v1/workflow/policies</h4>
            <p className="text-muted mt-2">List all active policy graphs.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto'}}>
{`curl "http://localhost:8000/api/v1/workflow/policies" \\
  -H "X-API-Key: <your_key>"`}
            </pre>
          </div>
          
          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-primary" style={{marginRight: '0.5rem'}}>GET</span> /api/schema/{"{graph_id}"}</h4>
            <p className="text-muted mt-2">Dynamic Schema Discovery. Automatically generated JSON schema based on the compiled graph. Perfect for auto-generating Forms or MCP Tool definitions.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto'}}>
{`curl "http://localhost:8000/api/schema/freight_policy_graph" \\
  -H "X-API-Key: <your_key>"`}
            </pre>
          </div>
        </div>
      </div>

      <div className="glass-card mt-4">
        <h2 className="mb-3"><Terminal size={24} style={{verticalAlign: 'bottom', marginRight: '0.5rem'}} /> Enterprise Integration Snippets</h2>
        <p>Copy these pre-built snippets to instantly connect DACL to your agentic workflows and automation platforms.</p>

        <div className="mt-4">
          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-warning" style={{marginRight: '0.5rem'}}>LangChain</span> MCP Tool Server (Python)</h4>
            <p className="text-muted mt-2">Expose DACL as an MCP tool so your LangGraph agents (like Tagent) can autonomously evaluate rules.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto', fontSize: '0.85rem'}}>
{`import requests
from langchain.tools import tool

@tool
def evaluate_business_rule(query: str, domain: str = "it_ticket_routing") -> dict:
    """Passes natural language to the DACL deterministic rule engine.
    Always use this tool to determine how to route tickets or approvals."""
    
    url = "http://localhost:8000/api/v1/workflow/query"
    headers = {"X-API-Key": "YOUR_API_KEY"}
    
    response = requests.post(url, json={"domain": domain, "query": query}, headers=headers)
    result = response.json()
    
    if result.get("requires_human_review"):
        return {"status": "blocked", "message": "The LLM could not confidently extract facts. Escalate to human."}
        
    return {"status": "success", "decision": result["output"]}
`}
            </pre>
          </div>

          <div className="glass-panel mb-3" style={{padding: '1rem', background: 'rgba(0,0,0,0.2)'}}>
            <h4><span className="badge badge-primary" style={{marginRight: '0.5rem'}}>Zapier / Make.com</span> Catching DACL Webhooks</h4>
            <p className="text-muted mt-2">DACL's Durable Action Engine will automatically <code>POST</code> to this URL when a rule passes, allowing you to trigger Slack messages or Jira tickets without writing code.</p>
            <pre style={{background: 'rgba(0,0,0,0.4)', padding: '1rem', borderRadius: '8px', marginTop: '0.5rem', overflowX: 'auto', fontSize: '0.85rem'}}>
{`# 1. Start your DACL server with the webhook URL from Zapier/Make.com
export WEBHOOK_URL="https://hooks.zapier.com/hooks/catch/12345/abcde"
uv run uvicorn src.dacl_agent.main:app

# 2. When DACL fires a webhook, Zapier will receive this payload:
{
  "idempotency_key": "a1b2c3d4...",
  "decision_id": "9f8e7d6c...",
  "rule_id": "TAGENT_R001",
  "output_field": "auto_action",
  "output_value": "trigger_pagerduty",
  "facts": {
    "environment": "production",
    "impact_level": "critical"
  }
}`}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
