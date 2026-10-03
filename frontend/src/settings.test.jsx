import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import SettingsPage from './components/SettingsPage';
import { tabs, canOpen } from './components/NavTabs';

describe('Settings page', () => {
  it('starts loading and never renders secret values', () => {
    const html = renderToString(<SettingsPage />);
    expect(html).toContain('Settings');
    expect(html).toContain('Loading settings');
  });

  it('is super-admin-only in navigation', () => {
    const settings = tabs.find((t) => t.id === 'settings');
    expect(canOpen(settings, { role: 'analyst' })).toBe(false);
    expect(canOpen(settings, { role: 'agent' })).toBe(false);
    expect(canOpen(settings, { role: 'customer_channel' })).toBe(false);
  });

  it('grants the new super_admin and supervisor roles per the role-split', () => {
    // Super admin reaches every analyst page (settings here) and Cases.
    const settings = tabs.find((t) => t.id === 'settings');
    expect(canOpen(settings, { role: 'super_admin' })).toBe(true);
    // Supervisor works the call queue and cases.
    const casework = tabs.filter((t) => t.id === 'casework');
    expect(casework.some((t) => canOpen(t, { role: 'supervisor' }))).toBe(true);
    expect(tabs.filter((t) => t.id === 'callcenter').some((t) => canOpen(t, { role: 'supervisor' }))).toBe(true);
    // Supervisor is locked out of settings.
    expect(canOpen(settings, { role: 'supervisor' })).toBe(false);
  });
});

import { renderToString as render } from 'react-dom/server';
import CredentialsPanel from './components/CredentialsPanel';

const inputTag = (html, name) => html.match(new RegExp(`<input[^>]*aria-label="${name}"[^>]*>`))[0];

const status = {
  encryption_ready: true, editable: true,
  providers: [{ id: 'twilio', label: 'Twilio voice' }, { id: 'phone_book', label: 'Registered phone book' }],
  items: [
    { name: 'TWILIO_ACCOUNT_SID', provider: 'twilio', label: 'Account SID', kind: 'text', source: 'env', hint: 'AC123', help: 'h' },
    { name: 'TWILIO_AUTH_TOKEN', provider: 'twilio', label: 'Auth token', kind: 'secret', source: 'settings', hint: '••••abcd', help: 'h' },
    { name: 'TWILIO_FROM_NUMBER', provider: 'twilio', label: 'Caller number', kind: 'phone', source: 'missing', hint: null, help: 'h' },
    { name: 'SATHI_VOICE_PHONE_BOOK', provider: 'phone_book', label: 'Phone book', kind: 'phonebook', source: 'settings', hint: '1 number', help: 'h', entries: [{ user_id: 'U_1', phone: '+880•••678' }] },
  ],
};

describe('Credentials panel', () => {
  it('shows hints only, masked secret inputs, and editable fields without any unlock step', () => {
    const html = render(<CredentialsPanel status={status} onChanged={() => {}} />);
    expect(html).toContain('••••abcd');
    expect(html).toContain('type="password"');
    expect(html).not.toContain('admin token');
    expect(html).toContain('Place test call');
    expect(html).toContain('+880•••678');
    expect(inputTag(html, 'TWILIO_FROM_NUMBER')).not.toContain('disabled=""');
  });

  it('disables editing on read-only deployments or without the encryption key', () => {
    const readOnly = render(<CredentialsPanel status={{ ...status, editable: false }} onChanged={() => {}} />);
    expect(readOnly).toContain('SATHI_SETTINGS_EDITABLE=false');
    expect(inputTag(readOnly, 'TWILIO_FROM_NUMBER')).toContain('disabled=""');
    const noKey = render(<CredentialsPanel status={{ ...status, encryption_ready: false }} onChanged={() => {}} />);
    expect(noKey).toContain('SATHI_SECRETS_KEY');
  });
});
