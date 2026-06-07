import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { PlayCircle, CheckCircle, Plus, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import * as api from '../api';

export default function ReaderDashboard() {
  const { user } = useAuth();
  const [showUpload, setShowUpload] = useState(false);

  const handleUploadSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    try {
      await api.uploadPolicy(formData);
      setShowUpload(false);
      alert('Policy uploaded and compiled successfully!');
    } catch(err) {
      alert(err.message);
    }
  };

  return (
    <div className="animate-fade-in">
      {showUpload && (
        <div className="modal-overlay">
          <div className="glass-card modal-content animate-fade-in">
            <div className="modal-header">
              <h2>Upload New Policy</h2>
              <button className="btn-icon" onClick={() => setShowUpload(false)}><X size={20}/></button>
            </div>
            <form onSubmit={handleUploadSubmit}>
              <div className="form-group">
                <label className="form-label">Domain Key (e.g. freight_v2)</label>
                <input type="text" name="domain" className="form-input" required />
              </div>
              <div className="form-group">
                <label className="form-label">Company Name</label>
                <input type="text" name="company" className="form-input" required />
              </div>
              <div className="form-group">
                <label className="form-label">Policy Document (PDF / TXT)</label>
                <input type="file" name="file" className="form-input" required accept=".pdf,.txt" />
              </div>
              <p className="text-muted mb-3" style={{fontSize: '0.85rem'}}>
                Uploading a document will automatically parse it and compile a new DACL graph using the LLM agent.
              </p>
              <div className="flex-between">
                <button type="button" className="btn btn-secondary" onClick={() => setShowUpload(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary">Upload & Compile <PlayCircle size={18}/></button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className="mb-4 flex-between">
        <div>
          <h1>Welcome, {user.username}</h1>
          <p>Your centralized gateway for querying deterministic business rules.</p>
        </div>
        {user.permissions.includes('upload') && (
          <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
            <Plus size={18} /> Upload New Policy
          </button>
        )}
      </div>
      
      <div className="glass-card mb-4" style={{display: 'flex', gap: '2rem'}}>
        <div style={{flex: 1, padding: '1.5rem', background: 'rgba(99, 102, 241, 0.1)', borderRadius: '12px', border: '1px solid rgba(99, 102, 241, 0.2)'}}>
          <h3 style={{color: '#a5b4fc'}}>Secure & Deterministic</h3>
          <p style={{fontSize: '0.9rem', marginBottom: 0}}>
            You are securely connected to the DACL Agent Engine. All queries executed against our business rules are mathematically verified, ensuring 100% deterministic outputs with zero LLM hallucination risk at runtime.
          </p>
        </div>
        <div style={{flex: 1, padding: '1.5rem', background: 'rgba(16, 185, 129, 0.1)', borderRadius: '12px', border: '1px solid rgba(16, 185, 129, 0.2)'}}>
          <h3 style={{color: '#6ee7b7'}}>System Status</h3>
          <div className="flex-center" style={{justifyContent: 'flex-start', gap: '0.5rem', marginTop: '1rem'}}>
            <CheckCircle size={24} color="#10b981" />
            <span style={{fontWeight: 600, color: '#f8f9fa'}}>All Systems Operational</span>
          </div>
        </div>
      </div>

      <div className="glass-card flex-between" style={{padding: '2rem'}}>
        <div>
          <h2>Ready to test some cases?</h2>
          <p>Use the Query Tester to evaluate natural language scenarios against active policies.</p>
        </div>
        <Link to="/query" className="btn btn-primary" style={{padding: '0.8rem 1.5rem', fontSize: '1rem'}}>
          Open Query Tester <PlayCircle size={20} />
        </Link>
      </div>
    </div>
  );
}
