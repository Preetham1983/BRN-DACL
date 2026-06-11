import React, { useState, useEffect } from 'react';
import { AlertTriangle, UploadCloud, CheckCircle, XCircle, ChevronDown, Trash2 } from 'lucide-react';
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
  
  // Custom Toast State
  const [toast, setToast] = useState(null); // { message, type: 'success' | 'error' }

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

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
      showToast('Policy uploaded and compiled successfully!', 'success');
      loadPolicies();
      setActiveTab('rules');
    } catch(err) {
      showToast(err.message, 'error');
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
      showToast(`Successfully rolled back to v${versionInt}`, 'success');
      loadVersions();
    } catch(e) {
      showToast(`Rollback failed: ${e.message}`, 'error');
    }
  };

  const handleDeletePolicy = async () => {
    if (!graphId) return;
    if (!window.confirm(`Are you sure you want to permanently delete policy '${graphId}' and all its versions?`)) return;
    setLoading(true);
    try {
      await api.deletePolicy(graphId);
      showToast('Policy deleted successfully', 'success');
      setGraphId('');
      loadPolicies();
    } catch(e) {
      showToast(`Delete failed: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in" style={{ position: 'relative' }}>
      
      {/* Custom Toast Popup */}
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

      {/* Header with Upload Policy on the right */}
      <div className="flex-between mb-4">
        <div>
          <h1 style={{ marginBottom: '0.5rem' }}>Policy Manager</h1>
          <p style={{ margin: 0 }}>Manage rules, versions, and deterministic logic</p>
        </div>
        <button 
          className="btn btn-primary" 
          style={{ padding: '0.75rem 1.5rem', fontWeight: 600, fontSize: '1rem' }}
          onClick={() => setActiveTab('upload')}
        >
          <UploadCloud size={20} />
          Upload New Policy
        </button>
      </div>

      <div className="glass-card mb-4" style={{ padding: '1.5rem 2rem' }}>
        <div className="flex-between mb-4">
          <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
            
            {/* Improved Domain Dropdown UI */}
            <div style={{ position: 'relative', minWidth: '300px', flex: 1 }}>
              <div style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-secondary)' }}>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '1px' }}>Domain:</span>
              </div>
              <select 
                className="form-select" 
                style={{
                  width: '100%', 
                  paddingLeft: '85px', 
                  appearance: 'none', 
                  cursor: 'pointer',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  fontWeight: 500,
                  fontSize: '1rem',
                  height: '46px'
                }} 
                value={graphId} 
                onChange={e => { setGraphId(e.target.value); if (activeTab === 'upload') setActiveTab('rules'); }}
              >
                {policies.map(p => (
                  <option key={p.graph_id} value={p.graph_id}>{p.domain} ({p.graph_id})</option>
                ))}
              </select>
              <div style={{ position: 'absolute', right: '14px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: 'var(--text-secondary)' }}>
                <ChevronDown size={18} />
              </div>
            </div>

            <button 
              className="btn btn-danger" 
              onClick={handleDeletePolicy} 
              disabled={!graphId || loading || activeTab === 'upload'}
              style={{ height: '46px', display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              <Trash2 size={16} /> Delete Domain
            </button>
            
            <div className="responsive-tabs" style={{display: 'flex', background: 'rgba(0,0,0,0.3)', padding: '4px', borderRadius: '8px', height: '46px'}}>
              <button 
                className={`btn ${activeTab === 'rules' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none', borderRadius: '6px', padding: '0 1.5rem'}} 
                onClick={() => setActiveTab('rules')}>
                Active Rules
              </button>
              <button 
                className={`btn ${activeTab === 'versions' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none', borderRadius: '6px', padding: '0 1.5rem'}} 
                onClick={() => setActiveTab('versions')}>
                Version History
              </button>
              <button 
                className={`btn ${activeTab === 'graph' ? 'btn-primary' : 'btn-secondary'}`} 
                style={{border: 'none', borderRadius: '6px', padding: '0 1.5rem'}} 
                onClick={() => setActiveTab('graph')}>
                Visual Graph
              </button>
            </div>
          </div>
        </div>
        
        {loading ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading data...</div>
        ) : activeTab === 'upload' ? (
          <div className="animate-fade-in" style={{padding: '1rem 0'}}>
            <h2 className="mb-4" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '1rem' }}>Upload & Compile Policy</h2>
            <form onSubmit={handleUploadSubmit} style={{ maxWidth: '600px' }}>
              <div className="form-group">
                <label className="form-label">Domain Key (e.g. freight_v2)</label>
                <input type="text" name="domain" className="form-input" required placeholder="Unique identifier for this policy" style={{ background: 'rgba(0,0,0,0.2)' }} />
              </div>
              <div className="form-group">
                <label className="form-label">Company Name</label>
                <input type="text" name="company" className="form-input" required placeholder="E.g. Nexus Logistics" style={{ background: 'rgba(0,0,0,0.2)' }} />
              </div>
              <div className="form-group">
                <label className="form-label">Policy Document</label>
                <input type="file" name="file" className="form-input" required accept=".pdf,.txt,.xlsx,.xls,.csv,.docx" style={{ background: 'rgba(0,0,0,0.2)' }} />
                <p className="text-muted mt-2" style={{fontSize: '0.85rem'}}>
                  Supported formats: PDF, TXT, Excel, CSV, DOCX. The LLM will automatically parse and compile this into a deterministic graph.
                </p>
              </div>
              <div className="flex-between mt-4">
                <button type="submit" className="btn btn-primary" disabled={loading} style={{ padding: '0.75rem 2rem' }}>
                  {loading ? 'Compiling Rules...' : 'Upload & Compile'}
                </button>
              </div>
            </form>
          </div>
        ) : errorMsg ? (
          <div className="glass-panel" style={{padding: '3rem', textAlign: 'center', background: 'rgba(245, 158, 11, 0.05)', border: '1px solid rgba(245, 158, 11, 0.2)'}}>
            <AlertTriangle size={48} color="#f59e0b" style={{marginBottom: '1rem'}} />
            <h3 style={{ color: '#EAEAEA' }}>{errorMsg}</h3>
          </div>
        ) : activeTab === 'rules' ? (
          <div className="animate-fade-in" style={{ overflowX: 'auto' }}>
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
                  <tr><td colSpan="4" style={{textAlign: 'center', padding: '3rem'}}>No rules found. Compile the graph first.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ) : activeTab === 'versions' ? (
          <div className="animate-fade-in" style={{ overflowX: 'auto' }}>
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
                  <tr><td colSpan="5" style={{textAlign: 'center', padding: '3rem'}}>No version history found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        ) : activeTab === 'graph' ? (
          <div className="animate-fade-in" style={{padding: '1rem 0'}}>
            <div className="flex-between mb-4">
              <div>
                <h2 className="mb-1">Policy Logic Graph</h2>
                <p className="text-muted m-0">A visual DAG (Directed Acyclic Graph) of the policy rules and their priorities.</p>
              </div>
            </div>
            
            {rules.length === 0 ? (
              <div style={{ padding: '3rem', textAlign: 'center', border: '1px dashed rgba(255,255,255,0.1)', borderRadius: '12px' }}>No rules to display.</div>
            ) : (
              <div 
                id="mermaid-container" 
                className="mermaid" 
                style={{
                  background: 'rgba(0,0,0,0.3)', 
                  border: '1px solid rgba(255,255,255,0.05)',
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
        ) : null}
      </div>
    </div>
  );
}
