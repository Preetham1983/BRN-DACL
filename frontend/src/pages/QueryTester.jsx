import React, { useState, useEffect } from 'react';
import { PlayCircle } from 'lucide-react';
import * as api from '../api';

export default function QueryTester() {
  const [policies, setPolicies] = useState([]);
  const [domain, setDomain] = useState('');
  const [mode, setMode] = useState('text'); // 'text' or 'doc'
  const [query, setQuery] = useState('');
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
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
          maxTextSize: 9000000, // Increase max text size to prevent errors on large graphs
          securityLevel: 'loose'
        });
        setMermaidReady(true);
      };
      document.body.appendChild(script);
    } else {
      setMermaidReady(true);
    }
  }, []);

  // Re-render Mermaid graph when result changes
  useEffect(() => {
    if (result && mermaidReady && window.mermaid) {
      setTimeout(() => {
        try {
          const container = document.getElementById('query-mermaid-container');
          if (container) {
            container.removeAttribute('data-processed');
            window.mermaid.init(undefined, container);
          }
        } catch(e) {
          console.error("Mermaid init error:", e);
        }
      }, 100);
    }
  }, [result, mermaidReady]);

  useEffect(() => {
    api.fetchPolicies().then(res => {
      setPolicies(res.policies || []);
      if (res.policies && res.policies.length > 0) {
        setDomain(res.policies[0].graph_id);
      }
    }).catch(console.error);
  }, []);

  const runQuery = async () => {
    setLoading(true); setError(''); setResult(null);
    try {
      let res;
      if (mode === 'text') {
        res = await api.runQuery(domain, query);
      } else {
        if (!file) throw new Error("Please select a document");
        const formData = new FormData();
        formData.append('graph_id', domain);
        formData.append('file', file);
        res = await api.runDocumentQuery(formData);
      }
      setResult(res);
    } catch(e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <h1>Query Tester</h1>
      <p>Test natural language against deterministic rules.</p>
      
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
          <label className="form-label">Input Mode</label>
          <div className="responsive-tabs" style={{display: 'flex', gap: '1rem', background: 'rgba(0,0,0,0.2)', padding: '0.25rem', borderRadius: '8px', width: 'fit-content'}}>
            <button 
              className={`btn ${mode === 'text' ? 'btn-primary' : 'btn-secondary'}`} 
              style={{border: 'none'}} 
              onClick={() => setMode('text')}>
              Natural Language
            </button>
            <button 
              className={`btn ${mode === 'doc' ? 'btn-primary' : 'btn-secondary'}`} 
              style={{border: 'none'}} 
              onClick={() => setMode('doc')}>
              Document Upload
            </button>
          </div>
        </div>

        {mode === 'text' ? (
          <div className="form-group">
            <label className="form-label">Query (Natural Language)</label>
            <textarea className="form-textarea" value={query} onChange={e => setQuery(e.target.value)} placeholder="e.g. I have a 120kg package going 600 miles..."></textarea>
          </div>
        ) : (
          <div className="form-group">
            <label className="form-label">Upload Case Document (PDF, TXT, Excel, CSV)</label>
            <input type="file" className="form-input" onChange={e => setFile(e.target.files[0])} accept=".pdf,.txt,.xlsx,.xls,.csv,.docx" />
            <p className="text-muted mt-2" style={{fontSize: '0.85rem'}}>
              The LLM fact extractor will automatically pull required variables from this document.
            </p>
          </div>
        )}

        <button className="btn btn-primary" onClick={runQuery} disabled={loading || (mode === 'text' ? !query : !file)}>
          {loading ? 'Evaluating...' : 'Run Query'} <PlayCircle size={18} />
        </button>
      </div>

      {error && <div className="glass-panel text-danger" style={{padding: '1rem'}}>{error}</div>}
      
      {result && (
        <div className="glass-card animate-fade-in">
          <h3 className="mb-2">Result: {result.success ? <span className="text-success">Success</span> : <span className="text-danger">Failed</span>}</h3>
          <p style={{fontSize: '1.1rem', fontWeight: 500}}>{result.answer}</p>
          
          <div className="mt-4" style={{display: 'grid', gridTemplateColumns: '1fr', gap: '2rem'}}>
            <div>
              <h4 className="mb-2">Rule Evaluation Path</h4>
              <p className="text-muted mb-3" style={{fontSize: '0.85rem'}}>Visual trace of the Rete engine's execution path for this query.</p>
              
              <div 
                id="query-mermaid-container" 
                className="mermaid"
                style={{
                  background: 'rgba(255,255,255,0.02)',
                  borderRadius: '12px',
                  padding: '1.5rem',
                  textAlign: 'center',
                  minHeight: '250px',
                  border: '1px solid rgba(255,255,255,0.05)',
                  overflowX: 'auto',
                  overflowY: 'hidden'
                }}
              >
                {/* Dynamically build the Mermaid flowchart */}
                {(() => {
                  const audit = result.audit || {};
                  const facts = audit.extracted_facts || {};
                  const rules = audit.rules_evaluated || [];
                  const winner = audit.winning_rule_id;
                  
                  let code = "graph TD\n";
                  
                  // Facts node
                  const factsStr = Object.entries(facts)
                    .filter(([k]) => !k.startsWith('_'))
                    .map(([k, v]) => {
                      let valStr = String(v);
                      // Truncate extremely long values and escape quotes for Mermaid compatibility
                      if (valStr.length > 100) valStr = valStr.substring(0, 100) + '...';
                      valStr = valStr.replace(/"/g, "'").replace(/[\[\]\(\)]/g, ' ');
                      return `${k}: ${valStr}`;
                    })
                    .join('<br/>');
                  code += `  Facts["📋 Extracted Facts<br/>${factsStr}"]\n`;
                  code += `  style Facts fill:#161616,stroke:#444,stroke-width:2px,color:#EAEAEA\n`;
                  
                  let displayRules = rules;
                  let hiddenCount = 0;
                  const MAX_RULES = 15;
                  
                  if (rules.length > MAX_RULES) {
                    const winnerRule = rules.find(r => r.rule_id === winner);
                    const matchedRules = rules.filter(r => r.matched && r.rule_id !== winner);
                    const unmatchedRules = rules.filter(r => !r.matched);
                    
                    displayRules = [];
                    if (winnerRule) displayRules.push(winnerRule);
                    
                    // Add matched rules up to MAX_RULES limit
                    const remainingSlots = MAX_RULES - displayRules.length;
                    displayRules = [...displayRules, ...matchedRules.slice(0, remainingSlots)];
                    
                    // If slots still available, add unmatched rules
                    const remainingSlots2 = MAX_RULES - displayRules.length;
                    if (remainingSlots2 > 0) {
                        displayRules = [...displayRules, ...unmatchedRules.slice(0, remainingSlots2)];
                    }
                    hiddenCount = rules.length - displayRules.length;
                  }
                  
                  displayRules.forEach((r, idx) => {
                    const isWinner = r.rule_id === winner;
                    const isMatched = r.matched;
                    const cleanAction = (r.action_applied || 'None').replace(/"/g, "'");
                    
                    // Create unique nodes
                    code += `  Rule_${idx}{"⚡ Rule: ${r.rule_id}"}\n`;
                    code += `  Action_${idx}["Set ${cleanAction}"]\n`;
                    
                    // Style nodes based on status
                    if (isWinner) {
                      code += `  style Rule_${idx} fill:#2A2A2A,stroke:#FFFFFF,stroke-width:2px,color:#FFFFFF\n`;
                      code += `  style Action_${idx} fill:#222222,stroke:#FFFFFF,stroke-width:2px,color:#FFFFFF\n`;
                    } else if (isMatched) {
                      code += `  style Rule_${idx} fill:#1A1A1A,stroke:#888888,stroke-width:1px,color:#EAEAEA\n`;
                      code += `  style Action_${idx} fill:#151515,stroke:#888888,stroke-width:1px,color:#EAEAEA\n`;
                    } else {
                      code += `  style Rule_${idx} fill:#111111,stroke:#333333,stroke-width:1px,color:#666666\n`;
                      code += `  style Action_${idx} fill:#0A0A0A,stroke:#333333,stroke-width:1px,color:#666666\n`;
                    }
                    
                    // Connections
                    code += `  Facts --> Rule_${idx}\n`;
                    if (isMatched) {
                      code += `  Rule_${idx} --"Match"--> Action_${idx}\n`;
                    } else {
                      code += `  Rule_${idx} -. "No Match" .-> Action_${idx}\n`;
                    }
                  });
                  
                  if (hiddenCount > 0) {
                     code += `  Hidden{"... and ${hiddenCount} more rules"}\n`;
                     code += `  style Hidden fill:#080808,stroke:#333333,stroke-width:1px,color:#666666,stroke-dasharray: 5 5\n`;
                     code += `  Facts -.-> Hidden\n`;
                  }
                  
                  return code;
                })()}
              </div>
            </div>

            <div>
              <details style={{background: 'rgba(0,0,0,0.15)', borderRadius: '8px', padding: '1rem'}}>
                <summary style={{cursor: 'pointer', fontWeight: 500, userSelect: 'none'}}>View Raw JSON Audit Trail</summary>
                <pre style={{marginTop: '1rem', padding: '0.5rem', background: 'rgba(0,0,0,0.3)', borderRadius: '4px', overflowX: 'auto', fontSize: '0.8rem'}}>
                  {JSON.stringify(result.audit, null, 2)}
                </pre>
              </details>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
