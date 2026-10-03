import { describe, it, expect } from 'vitest';
import { restoreSession, tokenExpiry } from './api';
import { providerLabel } from './components/SettingsPage';

const b64 = (o) => globalThis.btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
const jwt = (exp) => `${b64({ alg: 'HS256' })}.${b64({ sub: 'analyst_777', exp })}.sig`;
const store = (value) => {
  const data = { sathi_session: value };
  return { getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; }, removeItem: (k) => { delete data[k]; }, data };
};

describe('Session persistence', () => {
  it('reads the expiry from the signed token', () => {
    expect(tokenExpiry(jwt(2000))).toBe(2_000_000);
    expect(tokenExpiry('garbage')).toBe(0);
  });

  it('restores an unexpired session after reload', () => {
    const s = store(JSON.stringify({ token: jwt(2000), session: { role: 'analyst', subject: 'analyst_777', allowed_users: [] } }));
    expect(restoreSession(s, 1_000_000).session.role).toBe('analyst');
  });

  it('drops expired, tampered or malformed sessions', () => {
    const expired = store(JSON.stringify({ token: jwt(1000), session: { role: 'analyst' } }));
    expect(restoreSession(expired, 1_000_000)).toBeNull();
    expect(expired.data.sathi_session).toBeUndefined();
    const badRole = store(JSON.stringify({ token: jwt(2000), session: { role: 'admin' } }));
    expect(restoreSession(badRole, 1_000_000)).toBeNull();
    expect(restoreSession(store('{not json'), 1_000_000)).toBeNull();
    expect(restoreSession(null, 1_000_000)).toBeNull();
  });
});

describe('Settings readiness labels', () => {
  it('maps provider ids to names and falls back to the id', () => {
    expect(providerLabel('bd_http_ivr')).toBe('Bangladesh phone provider');
    expect(providerLabel('new_vendor')).toBe('new_vendor');
  });
});
