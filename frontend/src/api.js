const API_BASE = '/api';

function getAuthHeaders() {
  const token = localStorage.getItem('dacl_token');
  if (token) {
    return { 'Authorization': `Bearer ${token}` };
  }
  // Fallback for open mode (though the backend handles it)
  return {};
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Login failed');
  return res.json();
}

export async function fetchMe() {
  const res = await fetch(`${API_BASE}/auth/me`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Not authenticated');
  return res.json();
}

export async function fetchPolicies() {
  const res = await fetch(`${API_BASE}/policies`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch policies');
  return res.json();
}

export async function fetchRules(graphId) {
  const res = await fetch(`${API_BASE}/rules/${graphId}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch rules');
  return res.json();
}

export async function fetchVersions(graphId) {
  const res = await fetch(`${API_BASE}/versions/${graphId}`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch versions');
  return res.json();
}

export async function rollbackPolicy(graphId, toVersion, changeNote) {
  const res = await fetch(`${API_BASE}/rollback/${graphId}`, {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ to_version: toVersion, changed_by: 'system', change_note: changeNote })
  });
  if (!res.ok) throw new Error('Failed to rollback');
  return res.json();
}

export async function runQuery(domain, queryText) {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ domain, query: queryText })
  });
  if (!res.ok) throw new Error('Query failed');
  return res.json();
}

export async function uploadPolicy(formData) {
  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData
  });
  if (!res.ok) {
    const data = await res.json();
    if (data.detail && typeof data.detail === 'object') {
      throw new Error(JSON.stringify(data.detail));
    }
    throw new Error(data.detail || 'Upload failed');
  }
  return res.json();
}

export async function fetchUsers() {
  const res = await fetch(`${API_BASE}/auth/users`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch users');
  return res.json();
}

export async function createUser(username, password, role) {
  const res = await fetch(`${API_BASE}/auth/users`, {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, role })
  });
  if (!res.ok) {
    const data = await res.json();
    throw new Error(data.detail || 'Failed to create user');
  }
  return res.json();
}

export async function runDocumentQuery(formData) {
  const res = await fetch(`${API_BASE}/v1/workflow/query-doc`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData
  });
  if (!res.ok) {
    const data = await res.json();
    throw new Error(data.detail || 'Query failed');
  }
  return res.json();
}

export async function fetchApiKeys() {
  const res = await fetch(`${API_BASE}/auth/api-keys`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch API keys');
  return res.json();
}

export async function createApiKey(name, role) {
  const res = await fetch(`${API_BASE}/auth/api-keys`, {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, role })
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to create API key');
  return res.json();
}

export async function revokeApiKey(keyId) {
  const res = await fetch(`${API_BASE}/auth/api-keys/${keyId}`, {
    method: 'DELETE',
    headers: getAuthHeaders()
  });
  if (!res.ok) throw new Error('Failed to revoke API key');
  return res.json();
}
