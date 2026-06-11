import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';

import { AuthProvider, useAuth } from './context/AuthContext';
import Layout from './components/Layout';
import Login from './pages/Login';
import ReaderDashboard from './pages/ReaderDashboard';
import AdminDashboard from './pages/AdminDashboard';
import QueryTester from './pages/QueryTester';
import UsersManager from './pages/UsersManager';
import ApiHub from './pages/ApiHub';
import SimulationDashboard from './pages/SimulationDashboard';
import McpDocs from './pages/McpDocs';

function Dashboard() {
  const { user } = useAuth();
  if (user.role === 'admin') {
    return <AdminDashboard />;
  }
  return <ReaderDashboard />;
}

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Layout><Dashboard /></Layout>} />
          <Route path="/query" element={<Layout><QueryTester /></Layout>} />
          <Route path="/simulate" element={<Layout><SimulationDashboard /></Layout>} />
          <Route path="/users" element={<Layout><UsersManager /></Layout>} />
          <Route path="/api-hub" element={<Layout><ApiHub /></Layout>} />
          <Route path="/mcp-docs" element={<Layout><McpDocs /></Layout>} />
        </Routes>
      </AuthProvider>
    </Router>
  );
}
