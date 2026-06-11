import React from 'react';
import { Link, useLocation, Navigate } from 'react-router-dom';
import { ShieldCheck, LayoutDashboard, Users, LogOut, PlayCircle, Terminal, Activity, BookOpen } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="sidebar-header">
          <Link to="/" className="sidebar-brand" style={{textDecoration: 'none'}}>
            <ShieldCheck size={28} color="#6366f1" />
            <span>DACL Agent</span>
          </Link>
        </div>
        
        <nav className="sidebar-nav">
          <Link to="/" className={`nav-item ${location.pathname === '/' ? 'active' : ''}`}>
            <LayoutDashboard size={20} />
            Dashboard
          </Link>
          {user.permissions.includes('query') && (
            <>
              <Link to="/query" className={`nav-item ${location.pathname === '/query' ? 'active' : ''}`}>
                <PlayCircle size={20} />
                Query Tester
              </Link>
              <Link to="/simulate" className={`nav-item ${location.pathname === '/simulate' ? 'active' : ''}`}>
                <Activity size={20} />
                Simulation
              </Link>
            </>
          )}
          <Link to="/api-hub" className={`nav-item ${location.pathname === '/api-hub' ? 'active' : ''}`}>
            <Terminal size={20} />
            API Hub
          </Link>
          <Link to="/mcp-docs" className={`nav-item ${location.pathname === '/mcp-docs' ? 'active' : ''}`}>
            <BookOpen size={20} />
            MCP Docs
          </Link>
          {user.role === 'admin' && (
            <Link to="/users" className={`nav-item ${location.pathname === '/users' ? 'active' : ''}`}>
              <Users size={20} />
              Manage Users
            </Link>
          )}
        </nav>

        <div className="sidebar-footer">
          <div className="user-info" style={{ overflow: 'hidden' }}>
            <div className="user-avatar" style={{ flexShrink: 0 }}>{user.username.charAt(0).toUpperCase()}</div>
            <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              <div style={{fontWeight: 600, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}} title={user.username}>{user.username}</div>
              <div style={{fontSize: '0.8rem', color: 'var(--text-secondary)'}} className="badge badge-primary">{user.role}</div>
            </div>
          </div>
          <button className="btn-icon" onClick={logout} title="Logout">
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}
