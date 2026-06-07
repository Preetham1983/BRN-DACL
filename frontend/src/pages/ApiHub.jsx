import React, { useState, useEffect } from 'react';
import { Key, Plus, Trash2, Copy, CheckCircle, Terminal } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as api from '../api';

export default function ApiHub() {
  const { user } = useAuth();
  const [apiKeys, setApiKeys] = useState([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyRole, setNewKeyRole] = useState('reader');
  const [loading, setLoading] = useState(false);
  const [showNewKey, setShowNewKey] = useState(null);

  useEffect(() => {
    if (user.role === 'admin') {
      loadKeys();
    }
  }, [user]);

  const loadKeys = async () => {
    try {
      const keys = await api.fetchApiKeys();
      setApiKeys(keys);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateKey = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await api.createApiKey(newKeyName, newKeyRole);
      setShowNewKey(res.raw_key);
      setNewKeyName('');
      loadKeys();
    } catch (e) {
      alert(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRevokeKey = async (id) => {
    if (!window.confirm("Are you sure you want to revoke this API key?")) return;
    try {
      await api.revokeApiKey(id);
      loadKeys();
    } catch (e) {
      alert(e.message);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    alert('Copied to clipboard!');
  };

  return (
    <div className="animate-fade-in">
      <div className="flex-between mb-4">
        <div>
          <h1>API Integration Hub</h1>
          <p>Connect your external AI agents and automated workflows to DACL</p>
        </div>
      </div>

      {user.role === 'admin' ? (
        <div className="glass-card mb-4">
          <h2 className="mb-3 flex-between">
            <span><Key size={24} style={{verticalAlign: 'bottom', marginRight: '0.5rem'}} /> API Keys</span>
          </h2>
          <p className="text-muted">Manage API keys for programmatic access to DACL endpoints.</p>
          
          {showNewKey && (
            <div className="glass-panel mb-4" style={{padding: '1.5rem', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid #10b981'}}>
              <h3 className="text-success flex-center" style={{justifyContent: 'flex-start', gap: '0.5rem'}}>
                <CheckCircle size={20} /> New API Key Created
              </h3>
              <p>Please copy this key now. It will not be shown again.</p>
              <div className="flex-between" style={{background: 'rgba(0,0,0,0.3)', padding: '1rem', borderRadius: '8px', marginTop: '1rem'}}>
                <code style={{fontSize: '1.1rem', color: '#6ee7b7'}}>{showNewKey}</code>
                <button className="btn btn-secondary" onClick={() => copyToClipboard(showNewKey)}>
                  <Copy size={16} /> Copy
                </button>
              </div>
              <button className="btn btn-primary mt-3" onClick={() => setShowNewKey(null)}>I have saved it</button>
            </div>
          )}

          <div style={{display: 'flex', gap: '2rem'}}>
            <div style={{flex: 2}}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map(k => (
                    <tr key={k.id}>
                      <td style={{fontWeight: 600}}>{k.name}</td>
                      <td>
                        <span className={`badge ${k.role === 'admin' ? 'badge-primary' : k.role === 'analyst' ? 'badge-warning' : 'badge-success'}`}>
                          {k.role}
                        </span>
                      </td>
                      <td className="text-muted">{new Date(k.created_at).toLocaleString()}</td>
                      <td>
                        <button className="btn-icon text-danger" onClick={() => handleRevokeKey(k.id)} title="Revoke Key">
                          <Trash2 size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {apiKeys.length === 0 && (
                    <tr><td colSpan="4" style={{textAlign: 'center'}}>No API keys found.</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div style={{flex: 1}} className="glass-panel p-3">
              <h4 className="mb-3">Generate New Key</h4>
              <form onSubmit={handleCreateKey}>
                <div className="form-group">
                  <label className="form-label">Key Name</label>
                  <input type="text" className="form-input" value={newKeyName} onChange={e => setNewKeyName(e.target.value)} required placeholder="e.g. Jira Agent" />
                </div>
                <div className="form-group">
                  <label className="form-label">Role</label>
                  <select className="form-select" value={newKeyRole} onChange={e => setNewKeyRole(e.target.value)}>
                    <option value="reader">Reader (Query Only)</option>
                    <option value="analyst">Analyst (Query + Add Rules)</option>
                    <option value="admin">Admin (Full Access)</option>
                  </select>
                </div>
                <button type="submit" className="btn btn-primary" style={{width: '100%'}} disabled={loading || !newKeyName}>
                  <Plus size={18} /> Generate Key
                </button>
              </form>
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
        </div>
      </div>
    </div>
  );
}
