import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import App from './App';
import Header from './components/Header';
import MetricsPage from './components/MetricsPage';
import LiveSimulation from './components/LiveSimulation';
import { UserReasons } from './components/OutreachList';
import { evidenceFixture } from './components/evidenceFixture';
import OutreachList from './components/OutreachList';
import AgentRiskBoard from './components/AgentRiskBoard';
import { API_BASE_URL, resolveApiBaseUrl, setApiBaseUrl } from './api';

describe('App', () => {
  it('renders Sathi console header', () => {
    const html = renderToString(<App />);
    expect(html).toContain('SATHI');
  });

  it('renders the agent terminal section', () => {
    const html = renderToString(<App />);
    expect(html).toContain('Agent Point-of-Sale Terminal');
  });

  it('renders the navigation tabs', () => {
    const html = renderToString(<App />);
    expect(html).toContain('Live Mandate Simulator');
    expect(html).toContain('Review Queue');
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
  it('displays illustrative sample, not a result on OutreachList', () => {
    const html = renderToString(<OutreachList />);
    expect(html).toContain('frozen synthetic snapshot');
    expect(html).toContain('Unavailable');
    expect(html).not.toContain('🔍 SHAP');
  });

  it('displays illustrative sample, not a result on AgentRiskBoard and removes geographic labels', () => {
    const html = renderToString(<AgentRiskBoard />);
    expect(html).toContain('frozen synthetic snapshot');
    expect(html).toContain('Unavailable');
    expect(html).not.toContain('Chittagong');
    expect(html).not.toContain('Rajshahi');
    expect(html).not.toContain('Sylhet');
  });

  it('initial health status is unknown and never initially green', () => {
    const html = renderToString(<Header />);
    expect(html).toContain('Connecting to API...');
    expect(html).not.toContain('Live Backend Connected');
    expect(html).toContain('#94a3b8');
  });
});


describe('Verified role and evidence boundaries', () => {
  it('customer has keypad but no terminal code or issuance/redemption controls', () => {
    const html = renderToString(<LiveSimulation session={{role: 'customer_channel', subject: 'U_fixture'}} flow={{mandateId: 'fixture-id'}} />);
    expect(html).toContain('Confirm amount');
    expect(html).toContain('গ্রাহকের নিশ্চিতকরণ');
    expect(html).not.toContain('Issue terminal code once');
    expect(html).not.toContain('Terminal redemption code');
    expect(html).not.toContain('849201');
  });
  it('agent cannot render customer verification controls', () => {
    const html = renderToString(<LiveSimulation session={{role: 'agent', subject: 'A_fixture', allowed_users: ['U_fixture']}} />);
    expect(html).toContain('Issue terminal code once');
    expect(html).not.toContain('Confirm amount');
    expect(html).not.toContain('Report cash received');
  });
  it('renders exact saved metrics, denominators, target misses and adoption result', () => {
    const html = renderToString(<MetricsPage initialData={evidenceFixture} />).replace(/<!-- -->/g, '');
    expect(html).toContain('0.7312'); expect(html).toContain('0.5123');
    expect(html).toContain('10 / 4'); expect(html).toContain('75.00%');
    expect(html).toContain('Target missed'); expect(html).toContain('Undefined');
    expect(html).toContain('৳10.00 BDT'); expect(html).not.toContain('৳50.00 BDT');
    expect(html).not.toContain('type="range"');
    expect(html).toContain('calibration cohort');
  });
  it('renders untrusted explanation text escaped instead of executing HTML', () => {
    const html = renderToString(<UserReasons data={{user_id: 'fixture', score: .7, top_reasons: [{feature: '<img src=x onerror=alert(1)>', value: 1, attribution: .2}]}} />);
    expect(html).toContain('&lt;img'); expect(html).not.toContain('<img');
    expect(html).toContain('raw log-odds');
  });
  it('keeps the synthetic and assumed financial notice visible when signed out', () => {
    const html = renderToString(<App />);
    expect(html).toContain('SYNTHETIC DEMO'); expect(html).toContain('ASSUMPTIONS');
  });
});
