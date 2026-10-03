import { describe, it, expect, vi, afterEach } from 'vitest';
import { api, resolveApiBaseUrl } from './api';
afterEach(() => { api.logout(); vi.unstubAllGlobals(); });
const loginReply = { access_token: 'synthetic-fixture-token', role: 'agent', subject: 'A_fixture', allowed_users: ['U_fixture'] };
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
describe('Scoped in-memory API client', () => {
  it('does not fetch authenticated routes without a session', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    await expect(api.getCases()).rejects.toThrow('sign in');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('uses bearer auth, preserves Bangla numeric strings, and never sends X-Actor', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(loginReply)).mockResolvedValue(response({ status: 'verified' }));
    vi.stubGlobal('fetch', fetcher);
    await api.login({ principal: 'demo_agent', pin: '1234' });
    await api.verifyMandate({ mandateId: 'id-1', statedAmount: '৩,০০০' });
    const [, options] = fetcher.mock.calls[1];
    expect(options.headers.Authorization).toBe('Bearer synthetic-fixture-token');
    expect(options.headers['X-Actor']).toBeUndefined();
    expect(JSON.parse(options.body)).toEqual({ mode: 'keypad', stated_amount: '৩,০০০' });
    expect(api.getSession().access_token).toBeUndefined();
  });
  it('logout clears authentication and switching roles replaces it', async () => {
    const fetcher = vi.fn().mockResolvedValue(response(loginReply)); vi.stubGlobal('fetch', fetcher);
    await api.login({ principal: 'demo_agent', pin: '1234' }); api.logout();
    await expect(api.getCases()).rejects.toThrow('sign in');
    fetcher.mockResolvedValue(response({ ...loginReply, role: 'customer_channel', access_token: 'customer-token' }));
    await api.login({ principal: 'demo_customer', pin: '5678' });
    expect(api.getSession().role).toBe('customer_channel');
  });
  it('unauthorized response clears the session and notifies UI subscribers', async () => {
    const listener = vi.fn(); const unsubscribe = api.subscribeSession(listener);
    const fetcher = vi.fn().mockResolvedValueOnce(response(loginReply)).mockResolvedValue(response({ error: { message: 'Token expired' } }, 401));
    vi.stubGlobal('fetch', fetcher);
    await api.login({ principal: 'demo_agent', pin: '1234' });
    await expect(api.getCases()).rejects.toThrow('Token expired');
    expect(api.getSession()).toBeNull(); expect(listener).toHaveBeenLastCalledWith(null); unsubscribe();
  });
  it('failed role switch clears the previous bearer', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response(loginReply)).mockResolvedValue(response({ detail: 'Bad PIN' }, 401));
    vi.stubGlobal('fetch', fetcher); await api.login({ principal: 'demo_agent', pin: '1234' });
    await expect(api.login({ principal: 'demo_customer', pin: 'wrong' })).rejects.toThrow('Bad PIN');
    expect(api.getSession()).toBeNull();
  });
  it('does not report health merely from HTTP200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ status: 'degraded' })));
    expect(await api.checkHealth()).toBe(false);
  });
  it('unavailable artifacts propagate errors with no fallback numbers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(loginReply)).mockResolvedValue(response({ detail: 'Artifacts unavailable' }, 503)));
    await api.login({ principal: 'demo_agent', pin: '1234' });
    await expect(api.getMetricsSummary()).rejects.toThrow('Artifacts unavailable');
  });
});


describe('Production browser origins', () => {
  it('rejects credentials, private IPs, private domains and remote localhost', () => {
    for (const url of ['https://user:secret@api.example.com', 'https://10.0.0.1', 'https://192.168.1.1', 'https://api.sathi.internal', 'http://127.0.0.1:18000']) {
      expect(resolveApiBaseUrl({DEV: false, VITE_API_URL: url}, 'console.example.com')).toBe('');
    }
  });
});
