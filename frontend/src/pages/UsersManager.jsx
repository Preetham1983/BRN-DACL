import React, { useState, useEffect } from 'react';
import { Plus, CheckCircle } from 'lucide-react';
import * as api from '../api';

export default function UsersManager() {
  const [users, setUsers] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('reader');
  const [errorMsg, setErrorMsg] = useState('');
  
  const loadUsers = () => api.fetchUsers().then(setUsers).catch(console.error);
  
  useEffect(() => {
    loadUsers();
  }, []);

  const handleAddUser = async (e) => {
    e.preventDefault();
    try {
      setErrorMsg('');
      await api.createUser(username, password, role);
      setShowAdd(false);
      setUsername('');
      setPassword('');
      setRole('reader');
      loadUsers();
    } catch (err) {
      setErrorMsg(err.message);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="flex-between mb-4">
        <div>
          <h1>Manage Users</h1>
          <p>Control access and roles</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(!showAdd)}>
          <Plus size={18} /> {showAdd ? 'Cancel' : 'Add User'}
        </button>
      </div>

      {showAdd && (
        <div className="glass-card mb-4">
          <h4>Create New User</h4>
          {errorMsg && <p className="text-danger mb-3">{errorMsg}</p>}
          <form onSubmit={handleAddUser} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '150px' }}>
              <label className="form-label">Username</label>
              <input className="form-input" required value={username} onChange={e => setUsername(e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: '150px' }}>
              <label className="form-label">Password</label>
              <input type="password" required className="form-input" value={password} onChange={e => setPassword(e.target.value)} />
            </div>
            <div style={{ flex: 1, minWidth: '150px' }}>
              <label className="form-label">Role</label>
              <select className="form-select" value={role} onChange={e => setRole(e.target.value)}>
                <option value="reader">Reader</option>
                <option value="analyst">Analyst</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <button type="submit" className="btn btn-success">Save User</button>
          </form>
        </div>
      )}

      <div className="glass-card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last Login</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id}>
                <td style={{fontWeight: 600}}>{u.username}</td>
                <td>
                  <span className={`badge ${u.role === 'admin' ? 'badge-primary' : u.role === 'analyst' ? 'badge-warning' : 'badge-success'}`}>
                    {u.role}
                  </span>
                </td>
                <td>
                  {u.is_active ? <span className="text-success flex-center gap-sm" style={{justifyContent: 'flex-start'}}><CheckCircle size={14}/> Active</span> : <span className="text-danger">Inactive</span>}
                </td>
                <td className="text-muted">{u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
