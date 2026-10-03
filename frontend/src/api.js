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

  const currentHost = runtimeHostname ??
    (typeof window !== 'undefined' ? window.location?.hostname : '') ?? '';
  const localHost = (host) => ['', 'localhost', '127.0.0.1', '[::1]', '::1'].includes(host);
  const localRuntime = localHost(currentHost);
  if (!envUrl) return localRuntime ? 'http://127.0.0.1:18000' : '';
  try {
    const url = new URL(envUrl);
    const host = url.hostname;
    if (url.username || url.password || url.search || url.hash || url.port === '18001') return '';
    if (localHost(host)) return localRuntime && ['http:', 'https:'].includes(url.protocol) ? envUrl.replace(/\/$/, '') : '';
    const privateIPv4 = /^(10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host);
    if (privateIPv4 || host.endsWith('.internal') || host.endsWith('.local') || host.includes(':') || !host.includes('.')) return '';
    return url.protocol === 'https:' ? envUrl.replace(/\/$/, '') : '';
  } catch { return ''; }

};

export let API_BASE_URL = resolveApiBaseUrl();

export const setApiBaseUrl = (url, env = import.meta.env) => {
  const dev = isDevelopment(env);
  if (!dev) {
    // Mock / localStorage override only allowed explicitly in development
    return false;
  }
  api.logout();
  API_BASE_URL = url;
  if (typeof window !== 'undefined' && window.localStorage) {
    window.localStorage.setItem('sathi_api_url', url);
  }
  return true;
};

// The session survives a page reload in sessionStorage (cleared when the tab closes and
// never shared with other tabs). It is dropped once the signed token expires.
const SESSION_KEY = 'sathi_session';

export const tokenExpiry = (token) => {
  try {
    const payload = JSON.parse(globalThis.atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return typeof payload.exp === 'number' ? payload.exp * 1000 : 0;
  } catch { return 0; }
};

const storage = () => {
  try { return typeof window !== 'undefined' ? window.sessionStorage : null; } catch { return null; }
};

export const restoreSession = (store = storage(), now = Date.now()) => {
  try {
    const saved = JSON.parse(store?.getItem(SESSION_KEY) || 'null');
    if (!saved?.token || !saved?.session || tokenExpiry(saved.token) <= now + 5000) {
      store?.removeItem(SESSION_KEY);
      return null;
    }
    if (!['agent', 'customer_channel', 'analyst'].includes(saved.session.role)) return null;
    return saved;
  } catch { return null; }
};

const persistSession = (token, value) => {
  try {
    if (token && value) storage()?.setItem(SESSION_KEY, JSON.stringify({ token, session: value }));
    else storage()?.removeItem(SESSION_KEY);
  } catch { /* storage blocked: session stays in memory only */ }
};

const restored = restoreSession();
let accessToken = restored?.token || '';
let session = restored?.session || null;
const sessionListeners = new Set();
const notifySession = () => sessionListeners.forEach((listener) => listener(session));

const request = async (path, { method = 'GET', body, authenticated = true } = {}) => {
  if (!API_BASE_URL) throw new Error('API unavailable: configure the public API URL.');
  if (authenticated && !accessToken) throw new Error('Please sign in to the synthetic demo.');
  const headers = { 'Content-Type': 'application/json' };
  if (authenticated) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && authenticated) api.logout();
    const error = new Error(data?.error?.message ||
      (typeof data?.detail === 'string' ? data.detail : 'Request rejected.'));
    error.status = res.status;
    error.code = data?.error?.code;
    error.key = data?.error?.key;
    throw error;
  }
  return data;
};

export const api = {
  getSession: () => session,
  subscribeSession(listener) {
    sessionListeners.add(listener);
    return () => sessionListeners.delete(listener);
  },
  logout() {
    accessToken = '';
    persistSession(null, null);
    session = null;
    notifySession();
  },
  // Test-only helper: inject a session and notify listeners. Production code
  // should never call this directly; it exists for SSR unit tests that need
  // to simulate a signed-in user without a network round-trip.
  __setSessionForTests(value) {
    session = value;
    notifySession();
  },
  async login({ principal, pin }) {
    api.logout();
    const data = await request('/api/v1/auth/demo-login', {
      method: 'POST', body: { principal, pin }, authenticated: false,
    });
    if (!data.access_token || !['agent', 'customer_channel', 'analyst'].includes(data.role)) {
      throw new Error('Invalid demo login response.');
    }
    accessToken = data.access_token;
    session = { role: data.role, subject: data.subject, allowed_users: data.allowed_users || [] };
    persistSession(accessToken, session);
    notifySession();
    return session;
  },
  requestMandate: ({ userId, agentId, amount }) => request('/api/v1/mandates/request', {
    method: 'POST', body: { user_id: userId, agent_id: agentId, amount, purpose: 'cash_out' },
  }),
  verifyMandate: ({ mandateId, statedAmount }) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/verify`, {
    method: 'POST', body: { mode: 'keypad', stated_amount: statedAmount },
  }),
  issueCode: (mandateId) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/issue-code`, { method: 'POST' }),
  redeemMandate: ({ mandateId, code }) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/redeem`, {
    method: 'POST', body: { code },
  }),
  confirmCash: ({ mandateId, cashReceived }) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/confirm-cash`, {
    method: 'POST', body: { cash_received: cashReceived },
  }),
  revokeMandate: (mandateId) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/revoke`, { method: 'POST' }),
  getUserAssistedScore: (id) => request(`/api/v1/users/${encodeURIComponent(id)}/assisted-score`),
  getAgentRisk: (id) => request(`/api/v1/agents/${encodeURIComponent(id)}/risk`),
  getOutreachList: () => request('/api/v1/outreach'),
  getCases: () => request('/api/v1/cases'),
  decideCase: ({ caseId, decision, note }) => request(`/api/v1/cases/${encodeURIComponent(caseId)}/decision`, {
    method: 'POST', body: { decision, note },
  }),
  getReceipt: (id) => request(`/api/v1/receipts/${encodeURIComponent(id)}`),
  getMetricsSummary: () => request('/api/v1/metrics/summary'),
  getVoiceConfig: () => request('/api/v1/voice/config'),
  getSettingsReadiness: () => request('/api/v1/settings/readiness'),
  runSettingsProbe: (only) => request(
    `/api/v1/settings/probe${only ? `?only=${encodeURIComponent(only)}` : ''}`),
  placeCall: (mandateId) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/call`, { method: 'POST' }),
  getCall: (mandateId) => request(`/api/v1/mandates/${encodeURIComponent(mandateId)}/call`),
  getIncomingCalls: () => request('/api/v1/voice/incoming'),
  answerSimulatedCall: ({ callId, digits }) => request(`/api/v1/voice/calls/${encodeURIComponent(callId)}/simulated-answer`, {
    method: 'POST', body: { digits },
  }),
  generateCaseBrief: (caseId) => request(`/api/v1/cases/${encodeURIComponent(caseId)}/brief`, { method: 'POST' }),
  getLiquidityOverview: () => request('/api/v1/liquidity/overview'),
  getAgentLiquidity: (agentId) => request(`/api/v1/liquidity/agents/${encodeURIComponent(agentId)}`),
  getUpliftSummary: () => request('/api/v1/campaigns/uplift'),
  getOpsOverview: () => request('/api/v1/ops/overview'),
  getPrioritizedCases: () => request('/api/v1/ops/cases'),
  getCaseTimeline: (caseId) => request(`/api/v1/cases/${encodeURIComponent(caseId)}/timeline`),
  getWatchlist: () => request('/api/v1/watchlist'),
  addToWatchlist: ({ agentId, reason, caseId }) => request(`/api/v1/watchlist/${encodeURIComponent(agentId)}`, {
    method: 'PUT', body: { reason, case_id: caseId ?? null },
  }),
  removeFromWatchlist: (agentId) => request(`/api/v1/watchlist/${encodeURIComponent(agentId)}`, { method: 'DELETE' }),
  getNotifications: () => request('/api/v1/notifications'),
  getSettings: () => request('/api/v1/settings'),
  saveCredentials: (values) => request('/api/v1/settings/credentials', { method: 'PUT', body: { values } }),
  clearCredential: (name) => request(`/api/v1/settings/credentials/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  testProvider: (provider) => request(`/api/v1/settings/providers/${encodeURIComponent(provider)}/test`, { method: 'POST' }),
  testCall: (to) => request('/api/v1/settings/providers/twilio/test-call', { method: 'POST', body: { to } }),
  testSms: (to) => request('/api/v1/settings/providers/alpha_sms/test-sms', { method: 'POST', body: { to } }),
  updateSettings: (changes) => request('/api/v1/settings', { method: 'PUT', body: { changes } }),
  resetSetting: (key) => request(`/api/v1/settings/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  optimizeCampaign: (budgetBdt) => request('/api/v1/campaigns/optimize', {
    method: 'POST', body: { budget_bdt: budgetBdt },
  }),
  async checkHealth() {
    if (!API_BASE_URL) return false;
    try {
      const res = await fetch(`${API_BASE_URL}/health`);
      return res.ok && (await res.json()).status === 'ok';
    } catch { return false; }
  },
};
