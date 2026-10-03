import { useState } from 'react';
import { api } from '../api';
import Icon from './Icon';

export const roleMeta = {
  agent: { principal: 'demo_agent', label: 'Agent terminal', hint: 'Requests, issues and redeems', icon: 'store', tone: 'bg-secondary/15 text-secondary' },
  customer_channel: { principal: 'demo_customer', label: 'Customer channel', hint: 'Confirms amount, reports cash', icon: 'phone', tone: 'bg-primary/15 text-primary' },
  analyst: { principal: 'demo_analyst', label: 'Human analyst', hint: 'Reviews cases and evidence', icon: 'shield', tone: 'bg-accent/20 text-accent-content' },
};

const pins = { demo_agent: '1234', demo_customer: '5678', demo_analyst: '9012' };

export const principalForRole = (role) => roleMeta[role]?.principal || 'demo_agent';

export default function DemoLogin({ session = null, initialRole = 'agent', onDone = () => {} }) {
  const [principal, setPrincipal] = useState(principalForRole(initialRole));
  const [pin, setPin] = useState(pins[principalForRole(initialRole)]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const login = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await api.login({ principal, pin }); onDone(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={login} className="flex flex-col gap-4">
      <fieldset className="grid gap-2 sm:grid-cols-3">
        <legend className="mb-2 text-sm font-medium">Choose a demo role</legend>
        {Object.entries(roleMeta).map(([role, meta]) => {
          const selected = principal === meta.principal;
          return (
            <label key={role} className={`flex cursor-pointer items-center gap-3 rounded-box border p-3 transition sm:flex-col sm:items-start ${selected ? 'border-primary bg-primary/5 ring-1 ring-primary' : 'border-base-300 hover:border-base-content/30'}`}>
              <input type="radio" name="principal" className="sr-only" checked={selected}
                onChange={() => { setPrincipal(meta.principal); setPin(pins[meta.principal]); }} />
              <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${meta.tone}`}><Icon name={meta.icon} /></span>
              <span>
                <span className="block text-sm font-semibold">{meta.label}</span>
                <span className="block text-xs opacity-60">{meta.hint}</span>
              </span>
              {session?.role === role && <span className="badge badge-success badge-xs sm:mt-auto">current</span>}
            </label>
          );
        })}
      </fieldset>

      <label className="form-control w-full">
        <span className="mb-1 block text-sm font-medium">Public demo PIN</span>
        <input className="input input-bordered w-full font-mono tracking-widest" value={pin}
          onChange={(e) => setPin(e.target.value)} inputMode="numeric" autoComplete="off" />
        <span className="muted mt-1 block">Public fixture PINs: agent 1234 · customer 5678 · analyst 9012.</span>
      </label>

      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}

      <button disabled={busy} type="submit" className="btn btn-primary">
        {busy ? <><span className="loading loading-spinner loading-sm" />Signing in…</> : session ? 'Switch role' : 'Sign in'}
      </button>
    </form>
  );
}
