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
          <Route path="/users" element={<Layout><UsersManager /></Layout>} />
          <Route path="/api-hub" element={<Layout><ApiHub /></Layout>} />
        </Routes>
      </AuthProvider>
    </Router>
  );
}
