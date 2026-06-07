import React, { useState, useEffect, useContext } from 'react';
import * as api from '../api';

const AuthContext = React.createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.fetchMe()
      .then(u => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username, password) => {
    const data = await api.login(username, password);
    localStorage.setItem('dacl_token', data.access_token);
    const u = await api.fetchMe();
    setUser(u);
  };

  const logout = () => {
    localStorage.removeItem('dacl_token');
    setUser(null);
  };

  if (loading) return <div className="flex-center" style={{height: '100vh'}}>Loading...</div>;

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
