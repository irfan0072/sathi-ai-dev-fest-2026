import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { callStatus, checkStatus, takaFmt } from '../copy';

const filters = [
  { id: '', label: 'All' },
  { id: 'suspicious', label: 'Suspicious' },
  { id: 'verified', label: 'Verified' },
  { id: 'calling', label: 'Calling' },
  { id: 'no_answer', label: 'No answer' },
];

function Tile({ label, value, tone, onClick, active }) {
  return (
    <button type="button" onClick={onClick}
      className={`panel text-left shadow-sm transition hover:border-primary/50 ${active ? 'ring-2 ring-primary' : ''}`}>
      <div className="panel-body gap-1 p-4">
        <span className="muted">{label}</span>
        <span className={`text-2xl font-bold ${tone || ''}`}>{value}</span>
      </div>
    </button>
  );
}

function Journey({ item }) {
  const decided = ['verified', 'suspicious'].includes(item.status);
  const steps = [
    { label: 'Cash-out completed', state: 'done' },
    { label: 'Customer called', state: item.status === 'pending' ? 'todo' : item.status === 'no_answer' ? 'warn' : 'done' },
    { label: 'Customer typed amount', state: decided ? 'done' : 'todo' },
    { label: item.status === 'suspicious' ? 'Marked suspicious' : 'Verified', state: item.status === 'suspicious' ? 'bad' : item.status === 'verified' ? 'done' : 'todo' },
  ];
  const tone = { done: 'step-success', warn: 'step-warning', bad: 'step-error', todo: '' };
  return (
    <ul className="steps steps-vertical w-full text-xs md:steps-horizontal">
      {steps.map((s, i) => (
        <li key={s.label} className={`step ${tone[s.state]}`} data-content={s.state === 'done' ? '✓' : s.state === 'bad' ? '!' : i + 1}>{s.label}</li>
      ))}
    </ul>
  );
}

function Detail({ id, onOpenCases, onChanged }) {
  const [item, setItem] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => api.getTxnCheck(id).then(setItem).catch((err) => setError(err.message)), [id]);
  useEffect(() => { load(); }, [load]);
  if (!item) return <p className="muted p-6">{error || 'Loading…'}</p>;
  const rec = item.recommendation;
  const callAgain = async () => {
    setBusy(true); setError('');
    try { setItem({ ...(await api.callCheckAgain(id)), calls: item.calls }); onChanged(); load(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="muted">Receipt #{item.txn_id} · {new Date(item.ts).toLocaleString()}</div>
          <div className="text-2xl font-bold">{takaFmt(item.amount)}</div>
          <div className="muted">Customer {item.user_id} · Agent {item.agent_id}</div>
        </div>
        <span className={`badge ${checkStatus[item.status]?.tone}`}>{checkStatus[item.status]?.label}</span>
      </div>

      <Journey item={item} />

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-box bg-base-200 p-3"><div className="muted">Transaction amount</div><div className="font-semibold">{takaFmt(item.amount)}</div></div>
        <div className="rounded-box bg-base-200 p-3"><div className="muted">Customer typed</div><div className={`font-semibold ${item.status === 'suspicious' ? 'text-error' : ''}`}>{item.outcome === 'denied' ? 'Nothing (“I didn’t do this”)' : takaFmt(item.stated_amount)}</div></div>
      </div>

      {rec && (
        <div className={`rounded-box border p-4 ${rec.label === 'suspicious' ? 'border-error/40 bg-error/5' : 'border-success/40 bg-success/5'}`}>
          <div className="mb-1 flex items-center gap-2">
            <span className={`badge badge-sm ${rec.label === 'suspicious' ? 'badge-error' : 'badge-success'}`}>AI recommendation</span>
            <span className="font-semibold">{rec.label === 'suspicious' ? 'Suspicious — please review' : 'Looks fine'}</span>
          </div>
          <p className="text-sm font-medium">{rec.headline}</p>
          <ul className="mt-2 list-inside list-disc text-sm">{rec.reasons.map((r) => <li key={r.signal}>{r.text}</li>)}</ul>
          {rec.next_step && <p className="mt-2 text-sm"><strong>Next step:</strong> {rec.next_step}</p>}
          <p className="muted mt-2">{rec.note}</p>
        </div>
      )}

      {item.calls?.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-semibold">Calls</h4>
          <ul className="flex flex-col gap-1 text-sm">
            {item.calls.map((c, i) => (
              <li key={i} className="flex items-center justify-between gap-2">
                <span>{callStatus[c.status] || c.status}</span>
                <span className="muted">{c.provider === 'simulated' ? 'demo phone' : c.provider} · {new Date(c.at).toLocaleTimeString()}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {item.last_error && <div className="alert alert-warning alert-soft text-sm">Call problem: {item.last_error}</div>}
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}

      <div className="flex flex-wrap gap-2">
        {item.case_id && <button className="btn btn-primary btn-sm" onClick={() => onOpenCases?.(item.case_id)}>Open case #{item.case_id}</button>}
        {['pending', 'no_answer'].includes(item.status) && (
          <button className="btn btn-outline btn-sm" disabled={busy} onClick={callAgain}>
            <Icon name="phone" className="size-4" />Call the customer again
          </button>
        )}
      </div>
    </div>
  );
}

export default function TransactionsPage({ onOpenCases }) {
  const [filter, setFilter] = useState('');
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try { setData(await api.getTxnChecks(filter)); setError(''); } catch (err) { setError(err.message); }
  }, [filter]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const by = data?.summary?.by_status || {};
  const count = (s) => by[s]?.count || 0;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Transactions</h2>
        <p className="page-lead mt-1">Every cash-out is confirmed with the customer by phone. Matching amounts are verified. Anything else is marked suspicious for you to review — the AI only recommends, you decide.</p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile label="Cash-outs today" value={data?.summary?.total ?? '…'} onClick={() => setFilter('')} active={filter === ''} />
        <Tile label="Verified" value={count('verified')} tone="text-success" onClick={() => setFilter('verified')} active={filter === 'verified'} />
        <Tile label="Suspicious" value={count('suspicious')} tone="text-error" onClick={() => setFilter('suspicious')} active={filter === 'suspicious'} />
        <Tile label="Calling now" value={count('calling') + count('pending')} tone="text-info" onClick={() => setFilter('calling')} active={filter === 'calling'} />
        <Tile label="No answer" value={count('no_answer')} tone="text-warning" onClick={() => setFilter('no_answer')} active={filter === 'no_answer'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel shadow-sm lg:col-span-3">
          <div className="panel-body p-2 sm:p-4">
            <div role="tablist" className="tabs tabs-box w-fit">
              {filters.map((f) => (
                <button key={f.id} role="tab" className={`tab ${filter === f.id ? 'tab-active' : ''}`} onClick={() => setFilter(f.id)}>{f.label}</button>
              ))}
            </div>
            {!data ? <p className="muted p-4">Loading…</p> : data.items.length === 0 ? (
              <p className="muted p-6 text-center">No cash-outs in this list yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead><tr><th>Time</th><th>Customer</th><th className="text-right">Amount</th><th className="text-right">Typed</th><th>Result</th></tr></thead>
                  <tbody>{data.items.map((t) => (
                    <tr key={t.check_id} onClick={() => setSelected(t.check_id)}
                      className={`cursor-pointer hover:bg-base-200 ${selected === t.check_id ? 'bg-primary/10' : ''}`}>
                      <td className="whitespace-nowrap text-xs" title={new Date(t.ts).toLocaleString()}>{new Date(t.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                      <td className="font-mono text-xs">{t.user_id}</td>
                      <td className="text-right">{takaFmt(t.amount)}</td>
                      <td className={`text-right ${t.status === 'suspicious' ? 'font-semibold text-error' : ''}`}>{t.outcome === 'denied' ? '—' : takaFmt(t.stated_amount)}</td>
                      <td><span className={`badge badge-sm ${checkStatus[t.status]?.tone}`}>{checkStatus[t.status]?.label}</span></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        </div>
        <div className="panel h-fit shadow-sm lg:col-span-2">
          <div className="panel-body">
            {selected ? <Detail key={selected} id={selected} onOpenCases={onOpenCases} onChanged={load} />
              : <p className="muted py-10 text-center">Choose a cash-out to see what happened.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
