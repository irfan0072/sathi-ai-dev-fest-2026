/**
 * Sathi Console API client.
 * Connects directly to FastAPI backend on port 18000 or mock server on port 18001.
 */

export const isDevelopment = (env = import.meta.env) => {
  if (typeof env?.DEV !== 'undefined') {
    return Boolean(env.DEV);
  }
  return false;
};

export const resolveApiBaseUrl = (env = import.meta.env, runtimeHostname = undefined) => {
  const dev = isDevelopment(env);

  // In development only, allow explicit localStorage override
  if (dev && typeof window !== 'undefined' && window.localStorage) {
    const stored = window.localStorage.getItem('sathi_api_url');
    if (stored) return stored;
  }

  const rawEnvUrl = env?.VITE_API_URL;
  const envUrl = typeof rawEnvUrl === 'string' ? rawEnvUrl.trim() : '';

  if (dev) {
    if (envUrl) return envUrl;
    return 'http://127.0.0.1:18000';
  }

  // Production Origin Validation
  if (envUrl) {
    // 1. Reject mock port 18001 in production
    if (envUrl.includes('18001')) {
      return '';
    }

    // Parse host component
    let hostPart = envUrl;
    if (hostPart.startsWith('https://')) {
      hostPart = hostPart.slice(8);
    } else if (hostPart.startsWith('http://')) {
      hostPart = hostPart.slice(7);
    }
    const hostOnly = hostPart.split('/')[0].split(':')[0];

    const isLocalContainerHost = hostOnly === 'localhost' || hostOnly === '127.0.0.1';

    // 2. Reject bare private hosts (no dots and not localhost/127.0.0.1)
    if (!isLocalContainerHost && !hostOnly.includes('.')) {
      return '';
    }

    // 3. For public/remote hosts, require explicit HTTPS
    if (!isLocalContainerHost) {
      if (!envUrl.startsWith('https://')) {
        return '';
      }
      return envUrl;
    }

    return envUrl;
  }

  // Missing VITE_API_URL in production:
  const currentHost =
    runtimeHostname ??
    (typeof window !== 'undefined' && window.location?.hostname ? window.location.hostname : '');

  // Local production container on localhost may use 127.0.0.1:18000
  const isLocalRuntime = !currentHost || currentHost === 'localhost' || currentHost === '127.0.0.1';
  if (isLocalRuntime) {
    return 'http://127.0.0.1:18000';
  }

  // Remote production with missing config must be unavailable, never silently use localhost/mock
  return '';
};

export let API_BASE_URL = resolveApiBaseUrl();

export const setApiBaseUrl = (url, env = import.meta.env) => {
  const dev = isDevelopment(env);
  if (!dev) {
    // Mock / localStorage override only allowed explicitly in development
    return false;
  }
  API_BASE_URL = url;
  if (typeof window !== 'undefined' && window.localStorage) {
    window.localStorage.setItem('sathi_api_url', url);
  }
  return true;
};

const handleResponse = async (res) => {
  if (!res.ok) {
    let errDetail = 'Request failed';
    try {
      const errJson = await res.json();
      errDetail = errJson?.error?.message || errJson?.detail || JSON.stringify(errJson);
    } catch {
      errDetail = res.statusText;
    }
    throw new Error(errDetail);
  }
  return res.json();
};

export const api = {
  // Mandates
  async requestMandate({ userId, agentId, amount }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/mandates/request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Actor': agentId },
      body: JSON.stringify({
        user_id: userId,
        agent_id: agentId,
        amount: Number(amount),
        purpose: 'cash_out',
      }),
    });
    return handleResponse(res);
  },

  async verifyMandate({ mandateId, statedAmount, mode = 'keypad' }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/mandates/${mandateId}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Actor': 'customer_channel' },
      body: JSON.stringify({
        mode,
        stated_amount: Number(statedAmount),
        attempt: 1,
      }),
    });
    return handleResponse(res);
  },

  async redeemMandate({ mandateId, code, actor = 'A_000042' }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/mandates/${mandateId}/redeem`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Actor': actor },
      body: JSON.stringify({ code }),
    });
    return handleResponse(res);
  },

  async confirmCash({ mandateId, cashReceived }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/mandates/${mandateId}/confirm-cash`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Actor': 'customer_channel' },
      body: JSON.stringify({ cash_received: Number(cashReceived) }),
    });
    return handleResponse(res);
  },

  // Intelligence & Analytics
  async getUserAssistedScore(userId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/users/${userId}/assisted-score`);
    return handleResponse(res);
  },

  async getAgentRisk(agentId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/agents/${agentId}/risk`);
    return handleResponse(res);
  },

  async getOutreachList() {
    const res = await fetch(`${API_BASE_URL}/api/v1/outreach`);
    return handleResponse(res);
  },

  async getCases() {
    const res = await fetch(`${API_BASE_URL}/api/v1/cases`);
    return handleResponse(res);
  },

  async decideCase({ caseId, decision, reviewer, note }) {
    const res = await fetch(`${API_BASE_URL}/api/v1/cases/${caseId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reviewer, note }),
    });
    return handleResponse(res);
  },

  async getReceipt(txnId) {
    const res = await fetch(`${API_BASE_URL}/api/v1/receipts/${txnId}`);
    return handleResponse(res);
  },

  async getMetricsSummary() {
    const res = await fetch(`${API_BASE_URL}/api/v1/metrics/summary`);
    return handleResponse(res);
  },

  async checkHealth() {
    if (!API_BASE_URL) return false;
    try {
      const res = await fetch(`${API_BASE_URL}/health`);
      return res.ok;
    } catch {
      return false;
    }
  },
};
