import { useState } from 'react';
import { api } from '../api';
import Icon from './Icon';

export const roleMeta = {
  agent: { principal: 'demo_agent', label: 'Agent', hint: 'Gives cash to customers', icon: 'store', tone: 'bg-secondary/15 text-secondary' },
  customer_channel: { principal: 'demo_customer', label: 'Customer', hint: 'Confirms the amount on their phone', icon: 'phone', tone: 'bg-primary/15 text-primary' },
  supervisor: { principal: 'demo_supervisor', label: 'Supervisor', hint: 'Handles calls and cases', icon: 'shield', tone: 'bg-accent/20 text-accent-content' },
  super_admin: { principal: 'demo_admin', label: 'Super admin', hint: 'Full platform access', icon: 'settings', tone: 'bg-warning/20 text-warning-content' },
  analyst: { principal: 'demo_analyst', label: 'Fraud analyst', hint: 'AI models and analytics', icon: 'radar', tone: 'bg-info/15 text-info' },
};

const pins = {
  demo_agent: '1234',
  demo_customer: '5678',
  demo_analyst: '9012',
  demo_supervisor: '3456',
  demo_admin: '7890',
};

export const principalForRole = (role) => roleMeta[role]?.principal || 'demo_agent';

export default function DemoLogin({ session = null, initialRole = 'agent', onDone = () => {} }) {
  const [principal, setPrincipal] = useState(principalForRole(initialRole));
  const [pin, setPin] = useState(pins[principalForRole(initialRole)]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [staffId, setStaffId] = useState('');
  const [phoneNo, setPhoneNo] = useState('');
  const accountType = { demo_agent: 'agent', demo_customer: 'customer' }[principal];
  const usePhone = Boolean(accountType && phoneNo.trim());

  const login = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      if (usePhone) await api.login({ principal: phoneNo.trim(), pin, accountType });
      else await api.login({ principal: staffId || principal, pin });
      onDone();
    }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <form onSubmit={login} className="flex flex-col gap-4">
      <fieldset className="grid gap-2 sm:grid-cols-3">
        <legend className="mb-2 text-sm font-medium">
          {session ? 'Who do you want to be?' : 'Who are you?'}
        </legend>
        {Object.entries(roleMeta).map(([role, meta]) => {
          const selected = principal === meta.principal;
          return (
            <label
              key={role}
              className={`flex cursor-pointer items-center gap-3 rounded-box border p-3 transition focus-within:ring-2 focus-within:ring-primary/60 sm:flex-col sm:items-start ${
                selected
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-base-300 hover:border-base-content/30'
              }`}
            >
              <input
                type="radio"
                name="principal"
                className="sr-only"
                checked={selected}
                onChange={() => {
                  setPrincipal(meta.principal);
                  setPin(pins[meta.principal]);
                  setStaffId('');
                  setPhoneNo('');
                }}
              />
              <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${meta.tone}`}>
                <Icon name={meta.icon} />
              </span>
              <span>
                <span className="block text-sm font-semibold">{meta.label}</span>
                <span className="block text-xs text-base-content/60">{meta.hint}</span>
              </span>
              {session?.role === role && (
                <span className="badge badge-success badge-xs sm:mt-auto">current</span>
              )}
            </label>
          );
        })}
      </fieldset>

      {principal === 'demo_supervisor' || staffId ? (
        <label className="form-control w-full">
          <span className="mb-1 block text-sm font-medium">Staff ID (optional)</span>
          <input
            className="input input-bordered w-full font-mono focus-ring"
            value={staffId}
            placeholder="demo_supervisor, or sup_nadia / sup_karim / sup_farzana"
            onChange={(e) => setStaffId(e.target.value.trim().toLowerCase())}
            autoComplete="off"
          />
        </label>
      ) : null}

      {accountType && (
        <label className="form-control w-full">
          <span className="mb-1 block text-sm font-medium">Phone number (test account, optional)</span>
          <input
            className="input input-bordered w-full font-mono focus-ring"
            value={phoneNo}
            inputMode="tel"
            placeholder="01XXXXXXXXX — leave empty for the demo account"
            onChange={(e) => {
              setPhoneNo(e.target.value);
              setPin(e.target.value.trim() ? '' : pins[principal]);
            }}
            autoComplete="off"
          />
        </label>
      )}

      <label className="form-control w-full">
        <span className="mb-1 block text-sm font-medium">{usePhone ? 'PIN' : 'Demo PIN'}</span>
        <input
          className="input input-bordered w-full font-mono tracking-widest focus-ring"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          inputMode="numeric"
          autoComplete="off"
        />
        <span className="muted mt-1 block">
          {usePhone ? 'The PIN the super admin set for this test account.' : 'Filled in for you. Other supervisors: type their staff ID below (PIN 3456).'}
        </span>
      </label>

      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          {error}
        </div>
      )}

      <button disabled={busy} type="submit" className="btn btn-primary focus-ring">
        {busy ? (
          <>
            <span className="loading loading-spinner loading-sm" />
            Signing in…
          </>
        ) : session ? (
          'Switch user'
        ) : (
          'Sign in'
        )}
      </button>
    </form>
  );
}
