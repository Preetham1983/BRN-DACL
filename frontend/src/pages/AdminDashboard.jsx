import React, { useState, useEffect } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as api from '../api';

export default function AdminDashboard() {
  const { user } = useAuth();
  const [policies, setPolicies] = useState([]);
  const [graphId, setGraphId] = useState('');
  const [rules, setRules] = useState([]);
  const [versions, setVersions] = useState([]);
  const [currentVersion, setCurrentVersion] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [activeTab, setActiveTab] = useState('rules'); 
  const [mermaidReady, setMermaidReady] = useState(false);

  // Load Mermaid dynamically
  useEffect(() => {
    if (!window.mermaidLoaded) {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
      script.async = true;
      script.onload = () => {
        window.mermaidLoaded = true;
        window.mermaid.initialize({ 
          startOnLoad: false, 
          theme: 'dark',
          maxTextSize: 9000000,
          securityLevel: 'loose'
        });
        setMermaidReady(true);
      };
      document.body.appendChild(script);
    } else {
      setMermaidReady(true);
    }
  }, []);

  // Re-render Mermaid graph when rules/tab changes
  useEffect(() => {
    if (activeTab === 'graph' && mermaidReady && window.mermaid) {
      setTimeout(() => {
        try {
          const container = document.getElementById('mermaid-container');
          if (container) {
            container.removeAttribute('data-processed');
            window.mermaid.init(undefined, container);
          }
        } catch(e) {
          console.error("Mermaid init error:", e);
        }
      }, 100);
    }
  }, [rules, activeTab, mermaidReady]);

  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    setLoading(true);
    setErrorMsg('');
    try {
      await api.uploadPolicy(formData);
      alert('Policy uploaded and compiled successfully!');
      loadPolicies();
      setActiveTab('rules');
    } catch(err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPolicies();
  }, []);

  useEffect(() => {
    if (graphId) {
      if (activeTab === 'rules') loadRules();
      if (activeTab === 'versions') loadVersions();
    }
  }, [graphId, activeTab]);

  const loadPolicies = async () => {
    try {
      const res = await api.fetchPolicies();
      setPolicies(res.policies || []);
      if (res.policies && res.policies.length > 0 && !graphId) {
        setGraphId(res.policies[0].graph_id);
      }
    } catch(e) {
      console.error(e);
    }
  };

  const loadRules = async () => {
    setLoading(true);
    setErrorMsg('');
    setRules([]);
    try {
      const res = await api.fetchRules(graphId);
      setRules(res.rules || []);
    } catch(e) {
      if (e.message.includes('Graph not compiled yet')) {
        setErrorMsg('This policy graph has not been compiled yet.');
      } else {
        setErrorMsg(e.message);
      }
      setRules([]);
    } finally {
      setLoading(false);
    }
  };

  const loadVersions = async () => {
    setLoading(true);
    setErrorMsg('');
    setVersions([]);
    try {
      const res = await api.fetchVersions(graphId);
      setVersions(res.versions || []);
      setCurrentVersion(res.current_version);
    } catch(e) {
      setErrorMsg(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async (versionInt) => {
    if (!window.confirm(`Are you sure you want to rollback to v${versionInt}?`)) return;
    try {
      await api.rollbackPolicy(graphId, versionInt, `Rolled back via UI by ${user.username}`);
      alert(`Successfully rolled back to v${versionInt}`);
      loadVersions();
    } catch(e) {
      alert(`Rollback failed: ${e.message}`);
    }
  };

  const handleDeletePolicy = async () => {
    if (!graphId) return;
    if (!window.confirm(`Are you sure you want to permanently delete policy '${graphId}' and all its versions?`)) return;
    setLoading(true);
    try {
      await api.deletePolicy(graphId);
      alert('Policy deleted successfully');
      setGraphId('');
      loadPolicies();
    } catch(e) {
      alert(`Delete failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="flex-between mb-4">
        <div>
          <h1>Policy Manager</h1>
          <p>Manage rules, versions, and deterministic logic</p>
        </div>
      </div>

      <div className="glass-card mb-4">
        <div className="flex-between mb-3">
          <div style={{display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap'}}>
            <select className="form-select" style={{width: 'auto', flex: 1}} value={graphId} onChange={e => setGraphId(e.target.value)}>
              {policies.map(p => (
                <option key={p.graph_id} value={p.graph_id}>{p.domain} ({p.graph_id})</option>
              ))}
            </select>

            <button className="btn btn-danger" onClick={handleDeletePolicy} disabled={!graphId || loading}>
              Delete Policy
            </button>
            
            <div className="responsive-tabs" style={{display: 'flex', background: 'rgba(0,0,0,0.2)', padding: '0.25rem', borderRadius: '8px'}}>
              <button 
                className={`btn ${activeTab === 'rules' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none'}} 
                onClick={() => setActiveTab('rules')}>
                Active Rules
              </button>
              <button 
                className={`btn ${activeTab === 'versions' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none'}} 
                onClick={() => setActiveTab('versions')}>
                Version History
              </button>
              <button 
                className={`btn ${activeTab === 'graph' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none'}} 
                onClick={() => setActiveTab('graph')}>
                Visual Graph
              </button>
              <button 
                className={`btn ${activeTab === 'upload' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none'}} 
                onClick={() => setActiveTab('upload')}>
                Upload Policy
              </button>
            </div>
          </div>
        </div>
        
        {loading ? <p>Loading data...</p> : errorMsg ? (
          <div className="glass-panel" style={{padding: '1.5rem', textAlign: 'center'}}>
            <AlertTriangle size={32} color="#EEDD82" style={{marginBottom: '1rem'}} />
            <h4>{errorMsg}</h4>
          </div>
        ) : activeTab === 'rules' ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Rule ID</th>
                <th>Description</th>
                <th>Priority</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rules.map(r => (
                <tr key={r.rule_id}>
                  <td style={{fontFamily: 'monospace', color: 'var(--accent-primary)'}}>{r.rule_id}</td>
                  <td>{r.description}</td>
                  <td><span className="badge badge-warning">{r.priority}</span></td>
                  <td><span className="badge badge-success">{r.action.output_field} = {r.action.formula}</span></td>
                </tr>
              ))}
              {rules.length === 0 && (
                <tr><td colSpan="4" style={{textAlign: 'center'}}>No rules found. Compile the graph first.</td></tr>
              )}
            </tbody>
          </table>
        ) : activeTab === 'versions' ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>Version</th>
                <th>Hash / ID</th>
                <th>Timestamp</th>
                <th>Changed By</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {versions.map(v => (
                <tr key={v.version_int}>
                  <td>
                    <span className={`badge ${v.version_int === currentVersion ? 'badge-success' : 'badge-primary'}`}>
                      v{v.version_int} {v.version_int === currentVersion && '(Active)'}
                    </span>
                  </td>
                  <td style={{fontFamily: 'monospace', fontSize: '0.85rem'}}>{v.version_id.substring(0, 8)}...</td>
                  <td className="text-muted">{new Date(v.created_at).toLocaleString()}</td>
                  <td>{v.metadata?.changed_by || 'system'}</td>
                  <td>
                    {v.version_int !== currentVersion && (
                      <button className="btn btn-danger" style={{padding: '0.3rem 0.6rem', fontSize: '0.8rem'}} onClick={() => handleRollback(v.version_int)}>
                        Rollback
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {versions.length === 0 && (
                <tr><td colSpan="5" style={{textAlign: 'center'}}>No version history found.</td></tr>
              )}
            </tbody>
          </table>
        ) : activeTab === 'graph' ? (
          <div className="glass-panel animate-fade-in" style={{padding: '2rem'}}>
            <h2 className="mb-3">Policy Logic Graph</h2>
            <p className="text-muted mb-4">A visual DAG (Directed Acyclic Graph) of the policy rules and their priorities.</p>
            
            {rules.length === 0 ? (
              <p style={{textAlign: 'center'}}>No rules to display.</p>
            ) : (
              <div 
                id="mermaid-container" 
                className="mermaid" 
                style={{
                  background: 'rgba(255,255,255,0.05)', 
                  borderRadius: '12px', 
                  padding: '2rem', 
                  textAlign: 'center',
                  minHeight: '400px',
                  overflowX: 'auto',
                  overflowY: 'hidden'
                }}
              >
                {/* We will inject the mermaid string here */}
                {(() => {
                   let code = `graph TD\n  Start((Incoming Facts)) \n`;
                   const sortedRules = [...rules].sort((a,b) => b.priority - a.priority);
                   const MAX_RULES = 15;
                   const displayRules = sortedRules.slice(0, MAX_RULES);
                   const hiddenCount = sortedRules.length - displayRules.length;
                   
                   code += displayRules.map((r, i) => {
                      let conditionsStr = r.conditions.map(c => `${c.field} ${c.operator} ${c.value}`).join(` ${r.condition_logic} `);
                      conditionsStr = conditionsStr.replace(/"/g, "'").replace(/[\[\]\(\)]/g, ' ');
                      if (conditionsStr.length > 100) conditionsStr = conditionsStr.substring(0, 100) + '...';
                      
                      let safeFormula = String(r.action.formula).replace(/"/g, "'").replace(/[\[\]\(\)]/g, ' ');
                      if (safeFormula.length > 100) safeFormula = safeFormula.substring(0, 100) + '...';
                      
                      return `  R${i}{"${r.rule_id}\\n(Priority: ${r.priority})"}\n` +
                             `  C${i}["If ${conditionsStr}"]\n` +
                             `  A${i}["Set ${r.action.output_field} = ${safeFormula}"]\n` +
                             (i === 0 ? `  Start --> R${i}\n` : `  R${i-1} -.Fallback.-> R${i}\n`) +
                             `  R${i} --Match--> C${i}\n` +
                             `  C${i} --> A${i}\n`;
                   }).join('');
                   
                   if (hiddenCount > 0) {
                      const lastIdx = displayRules.length - 1;
                      code += `  Hidden{"... and ${hiddenCount} more rules"}\n`;
                      code += `  style Hidden fill:#080808,stroke:#333333,stroke-width:1px,color:#666666,stroke-dasharray: 5 5\n`;
                      if (lastIdx >= 0) {
                        code += `  R${lastIdx} -.Fallback.-> Hidden\n`;
                      } else {
                        code += `  Start --> Hidden\n`;
                      }
                   }
                   return code;
                })()}
              </div>
            )}
          </div>
        ) : activeTab === 'upload' ? (
          <div className="glass-panel animate-fade-in" style={{padding: '2rem'}}>
            <h2 className="mb-3">Upload New Policy</h2>
            <form onSubmit={handleUploadSubmit}>
              <div className="form-group">
                <label className="form-label">Domain Key (e.g. freight_v2)</label>
                <input type="text" name="domain" className="form-input" required placeholder="Unique identifier for this policy" />
              </div>
              <div className="form-group">
                <label className="form-label">Company Name</label>
                <input type="text" name="company" className="form-input" required placeholder="E.g. Nexus Logistics" />
              </div>
              <div className="form-group">
                <label className="form-label">Policy Document (PDF / TXT / Excel / CSV)</label>
                <input type="file" name="file" className="form-input" required accept=".pdf,.txt,.xlsx,.xls,.csv,.docx" />
              </div>
              <p className="text-muted mb-3" style={{fontSize: '0.85rem'}}>
                Uploading a document will automatically parse it and compile a new DACL graph using the LLM agent. Supported formats: PDF, TXT, XLSX, XLS, CSV, DOCX.
              </p>
              <div className="flex-between mt-4">
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? 'Uploading & Compiling...' : 'Upload & Compile'}
                </button>
              </div>
            </form>
          </div>
        ) : null}
      </div>
    </div>
  );
}
