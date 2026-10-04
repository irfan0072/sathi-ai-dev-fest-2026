import { useState } from 'react';
import { api } from '../../api';
import { Alert, Badge, Empty, Kpi, PageHead, Panel, bdt, timeAgo, usePoll } from './kit';

const regions = ['dhaka', 'chittagong', 'rajshahi', 'khulna', 'barishal', 'sylhet', 'rangpur', 'mymensingh'];
const blank = { kind: 'customer', phone: '', display_name: '', pin: '', region: 'dhaka', opening_balance: '10000' };

export default function TestAccounts() {
  const [data, error, reload] = usePoll(() => api.getAccounts(), 10000);
  const [form, setForm] = useState(blank);
  const [flash, setFlash] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const create = async (e) => {
    e.preventDefault(); setBusy(true); setFlash('');
    try {
      const item = await api.createAccount({
        ...form, opening_balance: form.kind === 'customer' ? Number(form.opening_balance || 0) : 0,
      });
      setFlash(`Created ${item.kind} ${item.msisdn}. Sign in as ${item.kind === 'customer' ? 'Customer' : 'Agent'} with this number and PIN.${item.kind === 'customer' ? ' Agents must sign in again to see this customer.' : ''}`);
      setForm({ ...blank, kind: form.kind });
      reload();
    } catch (err) { setFlash(err.message); } finally { setBusy(false); }
  };
  const act = async (fn, done) => {
    setFlash('');
    try { await fn(); if (done) setFlash(done); reload(); } catch (err) { setFlash(err.message); }
  };
  const resetPin = (a) => {
    const pin = window.prompt(`New PIN for ${a.display_name} (4-8 digits)`);
    if (pin) act(() => api.updateAccount(a.account_id, { pin }), `PIN reset for ${a.msisdn}.`);
  };
  const addMoney = (a) => {
    const amount = Number(window.prompt(`Add money to ${a.display_name} (Taka)`, '5000'));
    if (amount > 0) act(() => api.addAccountMoney(a.account_id, amount), `Added ${bdt(amount)} to ${a.msisdn}.`);
  };

  const items = data?.items || [];
  const customers = items.filter((a) => a.kind === 'customer');
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Test accounts" lead="Create real customers and agents with your own phone numbers. They sign in with that number and a PIN. Confirmation calls and SMS for a test customer go to their number when a real call service is set up in Settings." />
      <Alert kind="info">{flash}</Alert>
      <Alert>{error}</Alert>
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi icon="users" label="Test customers" value={customers.length} note={`${customers.filter((a) => a.active).length} active`} />
        <Kpi icon="store" label="Test agents" value={items.length - customers.length} note="Each serves every active test customer" />
        <Kpi icon="phone" label="Calls go to" value="Their own number" note="Seeded wallets are never dialled" />
      </div>

      <Panel title="Add a test account">
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <select className="select select-bordered select-sm focus-ring" value={form.kind} onChange={set('kind')} aria-label="Account type">
            <option value="customer">Customer</option><option value="agent">Agent</option>
          </select>
          <input required className="input input-bordered input-sm font-mono focus-ring" inputMode="tel" placeholder="01XXXXXXXXX" value={form.phone} onChange={set('phone')} aria-label="Phone number" />
          <input required className="input input-bordered input-sm focus-ring" placeholder="Full name" value={form.display_name} onChange={set('display_name')} aria-label="Full name" />
          <input required className="input input-bordered input-sm font-mono focus-ring" placeholder="PIN (4-8 digits)" inputMode="numeric" value={form.pin}
            onChange={(e) => setForm({ ...form, pin: e.target.value.replace(/\D/g, '').slice(0, 8) })} aria-label="PIN" />
          <select className="select select-bordered select-sm capitalize focus-ring" value={form.region} onChange={set('region')} aria-label="Region">
            {regions.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          {form.kind === 'customer' ? (
            <label className="input input-bordered input-sm focus-ring">
              <span className="opacity-60">৳</span>
              <input className="grow" inputMode="decimal" placeholder="Opening balance" value={form.opening_balance}
                onChange={(e) => setForm({ ...form, opening_balance: e.target.value.replace(/[^0-9.]/g, '') })} aria-label="Opening balance" />
            </label>
          ) : <span className="muted self-center text-xs">Agents have no balance.</span>}
          <button className="btn btn-primary btn-sm focus-ring lg:col-start-6" disabled={busy}>
            {busy && <span className="loading loading-spinner loading-xs" />}Create
          </button>
        </form>
      </Panel>

      <Panel bodyClass="p-0">
        {items.length === 0 ? <Empty icon="users" title="No test accounts yet" body="Add one above with your own phone number." /> : (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Name</th><th>Phone</th><th>Type</th><th>Region</th><th>Balance</th><th>Last sign-in</th><th /></tr></thead>
              <tbody>
                {items.map((a) => (
                  <tr key={a.account_id} className={a.active ? '' : 'opacity-50'}>
                    <td className="font-medium">{a.display_name}</td>
                    <td className="font-mono text-xs">{a.msisdn}</td>
                    <td><Badge tone={a.kind === 'agent' ? 'badge-secondary' : 'badge-primary'}>{a.kind === 'agent' ? 'Agent' : 'Customer'}</Badge></td>
                    <td className="capitalize">{a.region}</td>
                    <td>{a.kind === 'customer' ? bdt(a.balance ?? 0) : '—'}</td>
                    <td className="muted text-xs">{a.last_login_at ? timeAgo(a.last_login_at) : 'never'}</td>
                    <td className="flex flex-wrap gap-1">
                      {a.kind === 'customer' && <button className="btn btn-xs btn-ghost border-base-300" onClick={() => addMoney(a)}>Add money</button>}
                      <button className="btn btn-xs btn-ghost border-base-300" onClick={() => resetPin(a)}>Reset PIN</button>
                      <button className={`btn btn-xs ${a.active ? 'btn-ghost border-base-300' : 'btn-success'}`}
                        onClick={() => act(() => api.updateAccount(a.account_id, { active: !a.active }))}>{a.active ? 'Deactivate' : 'Activate'}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
