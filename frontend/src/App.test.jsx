import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import App from './App';
import Header from './components/Header';
import MetricsPage from './components/MetricsPage';
import AgentCashout from './components/AgentCashout';
import CustomerAccount from './components/CustomerAccount';
import { UserReasons } from './components/OutreachList';
import { evidenceFixture } from './components/evidenceFixture';
import OutreachList from './components/OutreachList';
import AgentRiskBoard from './components/AgentRiskBoard';
import { API_BASE_URL, resolveApiBaseUrl, setApiBaseUrl } from './api';

describe('App', () => {
  it('shows the login screen first when signed out', () => {
    const html = renderToString(<App />);
    expect(html).toContain('Sign in');
    // Dashboard / sidebar tabs must NOT leak before authentication.
    expect(html).not.toContain('Agent counter');
    expect(html).not.toContain('Cash-out');
    expect(html).not.toContain('Cases to review');
    expect(html).not.toContain('Dashboard');
  });
});

describe('API URL Resolution & Mock Rejection', () => {
  it('resolves public HTTPS URL in production', () => {
    const url = resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'https://sathi-api.onrender.com' });
    expect(url).toBe('https://sathi-api.onrender.com');
  });

  it('preserves full HTTPS URL in production', () => {
    const url = resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'https://api.example.com/path' });
    expect(url).toBe('https://api.example.com/path');
  });

  it('rejects public host without explicit HTTPS in production', () => {
    expect(resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'sathi-api.onrender.com' })).toBe('');
    expect(resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'http://sathi-api.onrender.com' })).toBe('');
  });

  it('rejects bare private host in production', () => {
    expect(resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'sathi-api' })).toBe('');
    expect(resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'http://sathi-api' })).toBe('');
  });

  it('rejects mock 18001 via VITE_API_URL in production', () => {
    expect(resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'http://127.0.0.1:18001' })).toBe('');
  });

  it('remote production with missing config is unavailable', () => {
    const url = resolveApiBaseUrl({ DEV: false }, 'sathi-console.onrender.com');
    expect(url).toBe('');
  });

  it('targets local container API18000 when VITE_API_URL is unset on localhost', () => {
    const url = resolveApiBaseUrl({ DEV: false }, 'localhost');
    expect(url).toBe('http://127.0.0.1:18000');
  });

  it('targets local container API18000 when VITE_API_URL is unset', () => {
    const url = resolveApiBaseUrl({ DEV: false });
    expect(url).toBe('http://127.0.0.1:18000');
  });

  it('rejects mock override in production', () => {
    const changed = setApiBaseUrl('http://127.0.0.1:18001', { DEV: false });
    expect(changed).toBe(false);
  });

  it('allows mock override in development and restores URL', () => {
    const initialUrl = API_BASE_URL;
    try {
      const changed = setApiBaseUrl('http://127.0.0.1:18001', { DEV: true });
      expect(changed).toBe(true);
    } finally {
      setApiBaseUrl(initialUrl, { DEV: true });
    }
  });
});

describe('MetricsPage Containment', () => {
  it('renders unavailable state without numerical placeholders or compliance claims', () => {
    const html = renderToString(<MetricsPage />);
    expect(html).toContain('Unavailable');
    expect(html).not.toContain('0.8028');
    expect(html).not.toContain('✓ Fairness Compliant');
    expect(html).not.toContain('✓ Robust — no degradation under shift');
  });
});

describe('Screen Labels & Provenance', () => {
  it('scores customers live on OutreachList (no frozen snapshot)', () => {
    const html = renderToString(<OutreachList />);
    expect(html).toContain('Scored live by the trained AI');
    expect(html).toContain('Scoring active customers');
    expect(html).not.toContain('frozen');
    expect(html).not.toContain('🔍 SHAP');
  });

  it('scores agents live on AgentRiskBoard without preloaded geography', () => {
    const html = renderToString(<AgentRiskBoard />);
    expect(html).toContain('scored live by the trained anomaly model');
    expect(html).toContain('Scoring agents on live data');
    expect(html).not.toContain('frozen');
    expect(html).not.toContain('Chittagong');
    expect(html).not.toContain('Rajshahi');
    expect(html).not.toContain('Sylhet');
  });

  it('initial health status is unknown and never initially green', () => {
    const html = renderToString(<Header />);
    expect(html).toContain('Connecting…');
    expect(html).not.toContain('>Online<');
    expect(html).toContain('#94a3b8');
  });
});


describe('Verified role and evidence boundaries', () => {
  it('customer sees balance, history and phone but never the check result', () => {
    const html = renderToString(<CustomerAccount />);
    expect(html).toContain('My account');
    expect(html).toContain('Balance');
    expect(html).toContain('My phone');
    expect(html).not.toContain('Suspicious');
    expect(html).not.toContain('Verified');
  });
  it('agent only records cash-outs and sees neutral confirmation status', () => {
    const html = renderToString(<AgentCashout session={{ role: 'agent', subject: 'A_fixture', allowed_users: ['U_fixture'] }} />);
    expect(html).toContain('Record cash-out');
    expect(html).toContain('U_fixture');
    expect(html).not.toContain('Suspicious');
    expect(html).not.toContain('one-time code');
  });
  it('renders exact saved metrics, denominators, target misses and adoption result', () => {
    const html = renderToString(<MetricsPage initialData={evidenceFixture} />).replace(/<!-- -->/g, '');
    // Default view: summary KPIs + provenance + first tab (Assisted detection)
    expect(html).toContain('0.7312'); expect(html).toContain('0.5123');
    expect(html).toContain('10 / 4');
    expect(html).toContain('assisted classifier');
    expect(html).toContain('rule baseline');
    expect(html).toContain('Verified frozen');
    expect(html).toContain('Missed');
    expect(html).not.toContain('type="range"');
    expect(html).toContain('calibration cohort');
    // Tab labels are reachable
    expect(html).toContain('Agent review');
    expect(html).toContain('Adoption impact');
    expect(html).toContain('Robustness');
    expect(html).toContain('Fairness audit');
  });
  it('renders untrusted explanation text escaped instead of executing HTML', () => {
    const html = renderToString(<UserReasons data={{user_id: 'fixture', score: .7, top_reasons: [{feature: '<img src=x onerror=alert(1)>', value: 1, attribution: .2}]}} />);
    expect(html).toContain('&lt;img'); expect(html).not.toContain('<img');
    expect(html).toContain('raw log-odds');
  });
  it('keeps the synthetic and assumed financial notice hidden until the user signs in', () => {
    // The SYNTHETIC DEMO banner only renders inside the authenticated layout.
    const html = renderToString(<App />);
    expect(html).not.toContain('SYNTHETIC DEMO');
    expect(html).not.toContain('ASSUMPTIONS');
  });
});

describe('Role-scoped navigation', () => {
  it('hides analyst-only tabs from a signed-in agent', async () => {
    const { default: App } = await import('./App');
    const { api } = await import('./api');
    const original = api.getSession();
    api.__setSessionForTests({ role: 'agent', subject: 'A_fixture', allowed_users: ['U_fixture'] });
    try {
      const html = renderToString(<App />);
      // Agent should see Liquidity + Simulator + Architecture, but NOT analyst tools.
      expect(html).toContain('Cash planning');
      expect(html).toContain('Cash-out');
      expect(html).toContain('How it works');
      expect(html).not.toContain('Cases to review');
      expect(html).not.toContain('Customers who need help');
      expect(html).not.toContain('Agent check');
      expect(html).not.toContain('Invite planner');
      expect(html).not.toContain('AI test results');
      expect(html).not.toContain('Dashboard');
    } finally {
      api.__setSessionForTests(original);
    }
  });

  it('hides analyst-only tabs from a signed-in customer_channel', async () => {
    const { default: App } = await import('./App');
    const { api } = await import('./api');
    const original = api.getSession();
    api.__setSessionForTests({ role: 'customer_channel', subject: 'U_fixture', allowed_users: [] });
    try {
      const html = renderToString(<App />);
      // Customer sees only their own account + How it works.
      expect(html).toContain('My account');
      expect(html).not.toContain('Transactions');
      expect(html).toContain('How it works');
      expect(html).not.toContain('Cases to review');
      expect(html).not.toContain('Cash planning');
      expect(html).not.toContain('Customers who need help');
      expect(html).not.toContain('Agent check');
      expect(html).not.toContain('Invite planner');
      expect(html).not.toContain('AI test results');
      expect(html).not.toContain('Dashboard');
    } finally {
      api.__setSessionForTests(original);
    }
  });

  it('lands an analyst on the Command Center and shows every tab', async () => {
    const { default: App } = await import('./App');
    const { api } = await import('./api');
    const original = api.getSession();
    api.__setSessionForTests({ role: 'analyst', subject: 'demo_analyst', allowed_users: [] });
    try {
      const html = renderToString(<App />);
      // SSR cannot run useEffect, so the active tab stays at the default
      // 'simulation'. We assert on the rendered sidebar/header instead,
      // which are purely derived from session + tabs list.
      expect(html).toContain('Fraud analyst');
      expect(html).toContain('demo_analyst');
      expect(html).toContain('Fraud dashboard');
      expect(html).toContain('Cases to review');
      expect(html).toContain('Cash planning');
      expect(html).toContain('Invite planner');
      expect(html).toContain('Agent review ranking');
      expect(html).toContain('Customers who need help');
      expect(html).toContain('AI test results');
      expect(html).toContain('How it works');
    } finally {
      api.__setSessionForTests(original);
    }
  });

  it('agents and customers never see analyst-only tabs in the sidebar', async () => {
    const { api } = await import('./api');
    const original = api.getSession();
    try {
      api.__setSessionForTests({ role: 'agent', subject: 'A_fixture', allowed_users: ['U_fixture'] });
      const agentHtml = renderToString(<App />);
      api.__setSessionForTests({ role: 'customer_channel', subject: 'U_fixture', allowed_users: [] });
      const customerHtml = renderToString(<App />);
      // Sidebar groups for Operations/Ecosystem/Evidence/About are derived from
      // the visible tabs list — make sure analyst sections aren't even labeled.
      for (const label of ['Dashboard', 'Cases to review', 'Invite planner', 'Agent check', 'Customers who need help', 'AI test results']) {
        expect(agentHtml).not.toContain(label);
        expect(customerHtml).not.toContain(label);
      }
    } finally {
      api.__setSessionForTests(original);
    }
  });
});

describe('Super admin and supervisor navigation', () => {
  it('gives the super admin the control center, directories and call management', async () => {
    const { default: App } = await import('./App');
    const { api } = await import('./api');
    const original = api.getSession();
    api.__setSessionForTests({ role: 'super_admin', subject: 'admin_777', allowed_users: [] });
    try {
      const html = renderToString(<App />);
      for (const label of ['Control center', 'Call management', 'All transactions', 'Customers',
        'Agents', 'Supervisors', 'Audit log', 'Settings', 'Fraud dashboard']) {
        expect(html).toContain(label);
      }
    } finally {
      api.__setSessionForTests(original);
    }
  });

  it('keeps the supervisor to their work queues', async () => {
    const { default: App } = await import('./App');
    const { api } = await import('./api');
    const original = api.getSession();
    api.__setSessionForTests({ role: 'supervisor', subject: 'sup_nadia', allowed_users: [] });
    try {
      const html = renderToString(<App />);
      for (const label of ['My desk', 'Call queue', 'Scam watch']) expect(html).toContain(label);
      for (const label of ['Control center', 'All transactions', 'Settings', 'Audit log', 'Fraud dashboard']) {
        expect(html).not.toContain(label);
      }
    } finally {
      api.__setSessionForTests(original);
    }
  });
});

describe('Sathi Sahayak assistant', () => {
  it('renders a trilingual chat with safe defaults', async () => {
    const { default: AssistantChat, CallLanguage } = await import('./components/AssistantChat');
    const html = renderToString(<AssistantChat />);
    expect(html).toContain('Sathi Sahayak');
    expect(html).toContain('never asks for your PIN');
    expect(html).toContain('আমার ব্যালেন্স কত?');
    expect(renderToString(<CallLanguage />)).toContain('Banglish');
  });
});
