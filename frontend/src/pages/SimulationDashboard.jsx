import React, { useState, useEffect } from 'react';
import { PlayCircle, Upload, AlertCircle } from 'lucide-react';
import * as api from '../api';

export default function SimulationDashboard() {
  const [policies, setPolicies] = useState([]);
  const [domain, setDomain] = useState('');
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.fetchPolicies().then(res => {
      setPolicies(res.policies || []);
      if (res.policies && res.policies.length > 0) {
        setDomain(res.policies[0].graph_id);
      }
    }).catch(console.error);
  }, []);

  const runSimulation = async () => {
    setLoading(true); setError(''); setResult(null);
    try {
      if (!file) throw new Error("Please select a CSV document");
      const formData = new FormData();
      formData.append('graph_id', domain);
      formData.append('file', file);
      const res = await api.simulateQueries(formData);
      setResult(res);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <h1>Batch Simulation</h1>
      <p>Upload a CSV file containing historical queries to see how the current rule graph performs.</p>
      
      <div className="glass-card mb-4">
        <div className="form-group">
          <label className="form-label">Domain</label>
          <select className="form-select" value={domain} onChange={e => setDomain(e.target.value)}>
            {policies.map(p => (
              <option key={p.graph_id} value={p.graph_id}>{p.domain} ({p.graph_id})</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Upload CSV (must have 'query' column)</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
             <input type="file" className="form-input" onChange={e => setFile(e.target.files[0])} accept=".csv" />
          </div>
        </div>

        <button className="btn btn-primary" onClick={runSimulation} disabled={loading || !file}>
          {loading ? 'Simulating...' : 'Run Simulation'} <PlayCircle size={18} />
        </button>
      </div>

      {error && <div className="glass-panel text-danger" style={{padding: '1rem'}}>{error}</div>}
      
      {result && (
        <div className="glass-card animate-fade-in">
          <h3 className="mb-2">Simulation Report</h3>
          <div style={{display: 'flex', gap: '2rem', marginBottom: '2rem'}}>
            <div style={{padding: '1rem', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', flex: 1}}>
              <div style={{fontSize: '2rem', fontWeight: 600, color: '#6366f1'}}>{result.total_queries}</div>
              <div style={{fontSize: '0.9rem', color: 'var(--text-secondary)'}}>Total Queries</div>
            </div>
            <div style={{padding: '1rem', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', flex: 1}}>
              <div style={{fontSize: '2rem', fontWeight: 600, color: '#10b981'}}>{result.successful_queries}</div>
              <div style={{fontSize: '0.9rem', color: 'var(--text-secondary)'}}>Successful</div>
            </div>
            <div style={{padding: '1rem', background: 'rgba(0,0,0,0.2)', borderRadius: '8px', flex: 1}}>
              <div style={{fontSize: '2rem', fontWeight: 600, color: '#ef4444'}}>{result.failed_queries}</div>
              <div style={{fontSize: '0.9rem', color: 'var(--text-secondary)'}}>Failed</div>
            </div>
          </div>
          
          <h4 className="mb-2">Detailed Results</h4>
          <div style={{ overflowX: 'auto' }}>
            <table style={{width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem'}}>
              <thead>
                <tr style={{borderBottom: '1px solid rgba(255,255,255,0.1)'}}>
                  <th style={{padding: '0.75rem 0.5rem'}}>Query</th>
                  <th style={{padding: '0.75rem 0.5rem'}}>Status</th>
                  <th style={{padding: '0.75rem 0.5rem'}}>Human Review</th>
                  <th style={{padding: '0.75rem 0.5rem'}}>Answer</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((r, i) => (
                  <tr key={i} style={{borderBottom: '1px solid rgba(255,255,255,0.05)'}}>
                    <td style={{padding: '0.75rem 0.5rem', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}} title={r.query}>
                      {r.query}
                    </td>
                    <td style={{padding: '0.75rem 0.5rem'}}>
                      {r.success ? <span className="text-success">Pass</span> : <span className="text-danger">Fail</span>}
                    </td>
                    <td style={{padding: '0.75rem 0.5rem'}}>
                      {r.requires_human_review ? <span className="badge" style={{background: '#f59e0b', color: '#000'}}>Yes</span> : <span>No</span>}
                    </td>
                    <td style={{padding: '0.75rem 0.5rem', maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}} title={r.answer || r.error}>
                      {r.success ? r.answer : <span className="text-danger">{r.error}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
