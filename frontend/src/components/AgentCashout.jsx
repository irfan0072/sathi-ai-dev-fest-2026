import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { publicCheck, takaFmt } from '../copy';
import { phone } from '../ids';

const quick = [500, 1000, 2000, 3000, 5000];

function FlowSteps({ last }) {
  const state = last?.check;
  const steps = [
    { label: 'Cash given', done: Boolean(last) },
    { label: 'Sathi calls the customer', done: ['done', 'missed', 'unreachable', 'manual'].includes(state), active: state === 'waiting' },
    { label: 'Confirmation finished', done: state === 'done' },
  ];
  return (
    <ul className="steps steps-vertical w-full sm:steps-horizontal">
      {steps.map((s, i) => (
        <li key={s.label} data-content={s.done ? '✓' : i + 1}
          className={`step text-xs sm:text-sm ${s.done ? 'step-success' : s.active ? 'step-primary' : ''}`}>
          {s.label}
        </li>
      ))}
    </ul>
  );
}

export default function AgentCashout({ session }) {
  const customers = session?.allowed_users || [];
  const [userId, setUserId] = useState(customers[0] || '');
  const [amount, setAmount] = useState('');
  const [items, setItems] = useState(null);
  const [last, setLast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const { items: rows } = await api.getMyTransactions();
      setItems(rows);
      setLast((prev) => (prev ? rows.find((r) => r.txn_id === prev.txn_id) || prev : prev));
    } catch (err) { setError(err.message); }
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      const result = await api.recordCashout({ userId, amount });
      setLast(result); setAmount('');
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Cash-out</h2>
        <p className="page-lead mt-1">Give the cash, then record it here. Sathi calls the customer afterwards to confirm the amount — you don&apos;t need to do anything else.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <form onSubmit={submit} className="panel shadow-sm lg:col-span-2">
          <div className="panel-body gap-4">
            <h3 className="font-semibold">Record a cash-out</h3>
            <label className="flex flex-col gap-1">
              <span className="text-sm">Customer</span>
              <select className="select select-bordered w-full" value={userId} onChange={(e) => setUserId(e.target.value)}>
                {customers.map((c) => <option key={c} value={c}>{phone(c)}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-sm">Cash given (Taka)</span>
              <label className="input input-bordered input-lg w-full">
                <span className="opacity-60">৳</span>
                <input aria-label="Cash given" inputMode="decimal" className="grow" placeholder="0" value={amount}
                  onChange={(e) => setAmount(e.target.value)} />
              </label>
            </label>
            <div className="flex flex-wrap gap-2">
              {quick.map((q) => (
                <button key={q} type="button" className="btn btn-ghost btn-xs border-base-300" onClick={() => setAmount(String(q))}>৳{q.toLocaleString()}</button>
              ))}
            </div>
            <button className="btn btn-primary" disabled={busy || !userId || !amount}>
              {busy && <span className="loading loading-spinner loading-sm" />}Record cash-out
            </button>
            {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
            <p className="muted">The fee is taken from the customer&apos;s account automatically. An SMS notice (without the amount) goes to the customer.</p>
          </div>
        </form>

        <div className="panel shadow-sm lg:col-span-3">
          <div className="panel-body gap-3">
            <h3 className="font-semibold">Last cash-out</h3>
            {!last ? <p className="muted">Record a cash-out to see its progress here.</p> : (
              <>
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <span className="text-3xl font-bold">{takaFmt(last.amount)}</span>
                  <span className="muted">fee {takaFmt(last.fee)} · customer {phone(last.user_id)} · receipt #{last.txn_id}</span>
                </div>
                <FlowSteps last={last} />
                <div className={`alert alert-soft text-sm ${['missed', 'unreachable'].includes(last.check) ? 'alert-warning' : last.check === 'done' ? 'alert-success' : 'alert-info'}`}>
                  {last.check === 'waiting' && <span className="loading loading-ring loading-sm" />}
                  <span>{last.check === 'done' ? 'The confirmation call is finished. Nothing else to do.'
                    : last.check === 'missed' ? 'The customer did not answer. A supervisor will follow up.'
                      : last.check === 'unreachable' ? 'The customer could not be reached after several tries. Nothing was confirmed.'
                        : last.check === 'manual' ? 'A supervisor will follow up with the customer.'
                      : 'Sathi is calling the customer to confirm the amount.'}</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="panel shadow-sm">
        <div className="panel-body">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-semibold">My cash-outs</h3>
            <button className="btn btn-ghost btn-sm" onClick={load}><Icon name="refresh" className="size-4" />Refresh</button>
          </div>
          {items === null ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No cash-outs yet.</p> : (
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead><tr><th>When</th><th>Customer</th><th className="text-right">Cash</th><th className="text-right">Fee</th><th>Customer check</th></tr></thead>
                <tbody>{items.map((t) => (
                  <tr key={t.txn_id}>
                    <td className="whitespace-nowrap">{new Date(t.ts).toLocaleString()}</td>
                    <td className="font-mono text-xs">{phone(t.user_id)}</td>
                    <td className="text-right font-semibold">{takaFmt(t.amount)}</td>
                    <td className="text-right">{takaFmt(t.fee)}</td>
                    <td><span className={`badge badge-sm ${publicCheck[t.check]?.tone}`}>{publicCheck[t.check]?.label || t.check}</span></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
