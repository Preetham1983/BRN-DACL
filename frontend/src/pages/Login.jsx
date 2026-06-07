import React, { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { ShieldCheck, AlertTriangle, ChevronRight } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login, user } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="glass-card login-box animate-fade-in">
        <div className="login-header">
          <div className="login-logo">
            <ShieldCheck size={48} color="#6366f1" style={{margin: '0 auto'}}/>
          </div>
          <h2>Enterprise Login</h2>
          <p>Sign in to manage DACL Rules</p>
        </div>
        
        {error && (
          <div className="glass-panel mb-4" style={{padding: '1rem', background: 'rgba(239, 68, 68, 0.1)', borderLeft: '4px solid #ef4444'}}>
            <div style={{display: 'flex', gap: '0.5rem', color: '#fca5a5'}}>
              <AlertTriangle size={20} />
              <span>{error}</span>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Username</label>
            <input 
              type="text" 
              className="form-input" 
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label className="form-label">Password</label>
            <input 
              type="password" 
              className="form-input" 
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary" style={{width: '100%'}} disabled={loading}>
            {loading ? 'Authenticating...' : 'Sign In'} <ChevronRight size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}
