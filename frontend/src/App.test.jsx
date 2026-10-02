import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import App from './App';
import Header from './components/Header';
import MetricsPage from './components/MetricsPage';
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
    const url = resolveApiBaseUrl({ DEV: false, VITE_API_URL: 'https://api.sathi.internal' });
    expect(url).toBe('https://api.sathi.internal');
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
    expect(html).toContain('illustrative sample, not a result');
    expect(html).not.toContain('🔍 SHAP');
  });

  it('displays illustrative sample, not a result on AgentRiskBoard and removes geographic labels', () => {
    const html = renderToString(<AgentRiskBoard />);
    expect(html).toContain('illustrative sample, not a result');
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
