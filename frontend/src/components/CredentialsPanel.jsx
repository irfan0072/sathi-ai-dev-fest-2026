import { useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { idFromPhone, phone } from '../ids';

const sourceBadge = {
  settings: <span className="badge badge-primary badge-xs">saved</span>,
  env: <span className="badge badge-info badge-xs">set by server</span>,
  missing: <span className="badge badge-ghost badge-xs">empty</span>,
  unreadable: <span className="badge badge-error badge-xs">please enter again</span>,
};

// Which free connection test belongs to each credential card.
const testFor = { twilio: 'twilio', webhooks: 'webhooks', bd_ivr: 'bd_ivr', alpha_sms: 'alpha_sms', gemini: 'gemini', openai: 'openai' };

const randomSecret = () => {
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
};

function PhoneBookEditor({ item, disabled, onSave }) {
  const [rows, setRows] = useState([{ user_id: '', phone: '' }]);
  const valid = rows.every((r) => /^[A-Za-z0-9_]{3,64}$/.test(idFromPhone(r.user_id)) && /^\+[1-9]\d{7,14}$/.test(r.phone));
  const update = (i, field, value) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [field]: value.trim() } : r)));
  return (
    <div className="flex flex-col gap-2">
      {item.entries?.length > 0 && (
        <table className="table table-xs">
          <thead><tr><th>Customer upay number</th><th>Number to call</th></tr></thead>
          <tbody>{item.entries.map((e) => <tr key={e.user_id}><td className="font-mono">{phone(e.user_id)}</td><td className="font-mono">{e.phone}</td></tr>)}</tbody>
        </table>
      )}
      <p className="muted">Confirmation calls go only to these numbers. Saving replaces the whole list, so enter every customer.</p>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap gap-2">
          <input className="input input-bordered input-xs w-40 font-mono" placeholder="01577000001" value={r.user_id} disabled={disabled}
            onChange={(e) => update(i, 'user_id', e.target.value)} aria-label="Customer upay number" />
          <input className="input input-bordered input-xs w-40 font-mono" placeholder="+8801XXXXXXXXX" value={r.phone} disabled={disabled}
            onChange={(e) => update(i, 'phone', e.target.value)} aria-label="Phone" />
          {rows.length > 1 && <button className="btn btn-ghost btn-xs" disabled={disabled} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}>Remove</button>}
        </div>
      ))}
      <div className="flex gap-2">
        <button className="btn btn-ghost btn-xs" disabled={disabled} onClick={() => setRows((rs) => [...rs, { user_id: '', phone: '' }])}>Add row</button>
        <button className="btn btn-primary btn-xs" disabled={disabled || !valid}
          onClick={() => onSave({ [item.name]: Object.fromEntries(rows.map((r) => [idFromPhone(r.user_id), r.phone])) })}>Save phone book</button>
      </div>
    </div>
  );
}

function ProviderCard({ provider, items, unlocked, onSaved }) {
  const [values, setValues] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [testTo, setTestTo] = useState('');
  const configured = items.every((i) => i.source !== 'missing' || i.name === 'ALPHA_SMS_SENDER_ID');

  const run = async (fn) => {
    setBusy(true); setError('');
    try { await fn(); } catch (err) { setError(err.key ? `${err.key}: ${err.message}` : err.message); } finally { setBusy(false); }
  };
  const save = (payload) => run(async () => {
    await api.saveCredentials(payload);
    setValues({}); setResult({ ok: true, detail: 'Saved. For safety, it will not be shown again.' });
    onSaved();
  });
  const clear = (name) => run(async () => { await api.clearCredential(name); setResult({ ok: true, detail: 'Removed.' }); onSaved(); });
  const test = () => run(async () => setResult(await api.testProvider(testFor[provider.id])));
  const paid = (fn) => run(async () => setResult(await fn(testTo)));
  const pending = Object.entries(values).filter(([, v]) => v !== '');

  return (
    <section className={`flex h-full flex-col rounded-box border p-4 ${configured ? 'border-success/40' : 'border-base-300'}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h4 className="font-semibold">{provider.label}</h4>
        {configured ? <span className="badge badge-success badge-sm gap-1 whitespace-nowrap"><Icon name="check" className="size-3" />set up</span> : <span className="badge badge-ghost badge-sm whitespace-nowrap">not set up</span>}
      </div>
      <div className="flex flex-col gap-3">
        {items.map((item) => item.kind === 'phonebook' ? (
          <PhoneBookEditor key={item.name} item={item} disabled={!unlocked || busy} onSave={save} />
        ) : (
          <label key={item.name} className="flex flex-col gap-1">
            <span className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">{item.label}</span>
              {sourceBadge[item.source]}
              {item.hint && <code className="text-xs opacity-70">{item.hint}</code>}
            </span>
            <span className="flex flex-wrap items-center gap-2">
              <input className="input input-bordered input-sm min-w-0 grow font-mono"
                type={item.kind === 'secret' ? 'password' : 'text'} autoComplete="off" spellCheck={false}
                placeholder={item.source === 'missing' ? 'Paste it here' : 'Type a new value to replace it'}
                disabled={!unlocked || busy} value={values[item.name] || ''}
                onChange={(e) => setValues((v) => ({ ...v, [item.name]: e.target.value }))} aria-label={item.name} />
              {item.name === 'SATHI_BD_IVR_WEBHOOK_SECRET' && (
                <button type="button" className="btn btn-ghost btn-sm whitespace-nowrap" disabled={!unlocked || busy}
                  onClick={() => setValues((v) => ({ ...v, [item.name]: randomSecret() }))}>Generate</button>
              )}
              {item.source === 'settings' && (
                <button type="button" className="btn btn-ghost btn-sm whitespace-nowrap" disabled={!unlocked || busy} onClick={() => clear(item.name)} title="Delete the saved value">Clear</button>
              )}
            </span>
            <span className="muted">{item.note || item.help}</span>
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {pending.length > 0 && (
          <button className="btn btn-primary btn-sm" disabled={!unlocked || busy} onClick={() => save(Object.fromEntries(pending))}>
            {busy && <span className="loading loading-spinner loading-xs" />}Save
          </button>
        )}
        {testFor[provider.id] && <button className="btn btn-outline btn-sm" disabled={busy} onClick={test}>Test connection</button>}
      </div>
      {(provider.id === 'twilio' || provider.id === 'alpha_sms') && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-base-300 pt-3">
          <input className="input input-bordered input-sm w-44 font-mono" placeholder="+8801XXXXXXXXX" value={testTo}
            onChange={(e) => setTestTo(e.target.value.trim())} disabled={!unlocked} aria-label="Test phone number" />
          <button className="btn btn-sm whitespace-nowrap" disabled={!unlocked || busy || !/^\+[1-9]\d{7,14}$/.test(testTo)}
            onClick={() => paid(provider.id === 'twilio' ? api.testCall : api.testSms)}>
            {provider.id === 'twilio' ? 'Place test call' : 'Send test SMS'}
          </button>
          <span className="muted">Uses real credit · up to 5 per hour</span>
        </div>
      )}
      {result && (
        <div role="status" className={`mt-3 rounded-box p-2 text-xs break-words ${result.ok ? 'bg-success/10' : 'bg-error/10'}`}>
          <strong>{result.ok ? 'Working' : 'Not working'}</strong> · {result.detail}
        </div>
      )}
      {error && <div role="alert" className="mt-3 rounded-box bg-error/10 p-2 text-xs break-words">{error}</div>}
    </section>
  );
}

export default function CredentialsPanel({ status, onChanged }) {
  const editable = status.editable !== false && status.encryption_ready;
  return (
    <section className="panel"><div className="panel-body">
      <h3 className="flex items-center gap-2 font-semibold"><Icon name="lock" className="size-4 text-primary" />Service accounts</h3>
      <p className="muted">Paste the account details from each service. They are stored safely and locked: after saving, only the last 4 characters are shown. Press <em>Test connection</em> to check each one.</p>
      {!status.encryption_ready && (
        <div role="alert" className="alert alert-warning alert-soft mt-2 text-sm"><Icon name="warning" className="shrink-0" /><span>Saving is turned off because the server has no safe-storage key yet. Ask your technical person to set <code>SATHI_SECRETS_KEY</code> on the server.</span></div>
      )}
      {status.editable === false && (
        <div role="alert" className="alert alert-info alert-soft mt-2 text-sm"><Icon name="lock" className="shrink-0" /><span>This page is view only (<code>SATHI_SETTINGS_EDITABLE=false</code>). You can test connections but not change them.</span></div>
      )}
      <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {status.providers.map((p) => (
          <ProviderCard key={p.id} provider={p} items={status.items.filter((i) => i.provider === p.id)}
            unlocked={editable} onSaved={onChanged} />
        ))}
      </div>
      <p className="muted mt-3">After saving and testing, choose the service under <strong>Calls and messages</strong> at the top of this page.</p>
    </div></section>
  );
}
