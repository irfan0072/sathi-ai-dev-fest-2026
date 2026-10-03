import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import CaseBrief from './CaseBrief';
import { WatchButton } from './CommandCenter';

const decisions = [
  { id: 'approved', label: 'Approve', tone: 'btn-success' },
  { id: 'denied', label: 'Deny', tone: 'btn-error' },
  { id: 'escalated', label: 'Escalate', tone: 'btn-warning' },
];
const priorityTone = { urgent: 'badge-error', high: 'badge-warning', normal: 'badge-ghost' };
const statusTone = (status) => (status === 'open' ? 'badge-info' : status === 'escalated' ? 'badge-error' : 'badge-ghost');
const filters = [
  { id: 'open', label: 'Open', test: (c) => ['open', 'escalated'].includes(c.status) },
  { id: 'urgent', label: 'Urgent', test: (c) => c.priority === 'urgent' && ['open', 'escalated'].includes(c.status) },
  { id: 'overdue', label: 'Past target', test: (c) => c.sla_breached },
  { id: 'all', label: 'All', test: () => true },
];

const slaText = (c) => {
  if (!['open', 'escalated'].includes(c.status)) return 'closed';
  const left = c.sla_minutes - c.age_minutes;
  const fmt = (m) => (Math.abs(m) >= 60 ? `${Math.round(Math.abs(m) / 60)}h` : `${Math.round(Math.abs(m))}m`);
  return left >= 0 ? `${fmt(left)} left` : `overdue ${fmt(left)}`;
};

function Timeline({ caseId }) {
  const [events, setEvents] = useState(null);
  useEffect(() => {
    let live = true;
    api.getCaseTimeline(caseId).then((v) => { if (live) setEvents(v.events); }).catch(() => { if (live) setEvents([]); });
    return () => { live = false; };
  }, [caseId]);
  if (!events) return <span className="loading loading-dots loading-xs" />;
  return (
    <ol className="relative ml-1 border-l border-base-300 pl-4">
      {events.map((e, i) => (
        <li key={i} className="mb-3 last:mb-0">
          <span className={`absolute -left-[5px] mt-1.5 inline-block size-2.5 rounded-full ${e.kind === 'review' ? 'bg-secondary' : e.kind === 'call' ? 'bg-primary' : e.kind === 'case' ? 'bg-error' : 'bg-base-300'}`} />
          <div className="text-sm">{e.label.replaceAll('_', ' ')}</div>
          <div className="muted">{e.actor} · {new Date(e.at).toLocaleString()}</div>
        </li>
      ))}
    </ol>
  );
}

export default function ReviewQueue() {
  const [cases, setCases] = useState(null);
  const [watch, setWatch] = useState(new Set());
  const [filter, setFilter] = useState('open');
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [result, list] = await Promise.all([api.getPrioritizedCases(), api.getWatchlist()]);
      setCases(result.cases);
      setWatch(new Set(list.agents.map((a) => a.agent_id)));
      setSelected((prev) => (prev ? result.cases.find((c) => c.case_id === prev.case_id) || null : null));
    } catch (err) { setError(err.message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const decide = async (decision) => {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await api.decideCase({ caseId: selected.case_id, decision, note });
      await refresh(); setNote(''); setMessage(`Case #${result.case_id}: ${result.decision}. Recorded in durable database audit. No redemption granted.`);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const active = filters.find((f) => f.id === filter);
  const shown = cases ? cases.filter(active.test) : [];
  const count = (f) => (cases ? cases.filter(f.test).length : 0);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="page-title">Supervisor Review Queue</h2>
          <p className="page-lead">Actual synthetic runtime cases from PostgreSQL, ordered by priority and time left to the response target. Human decisions update cases and audit only; models and review decisions never grant cash-out.</p>
        </div>
        <button className="btn btn-outline btn-sm" onClick={refresh}><Icon name="refresh" className="size-4" />Refresh cases</button>
      </div>

      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {message && <div role="status" className="alert alert-success alert-soft text-sm">{message}</div>}

      <div role="tablist" className="tabs tabs-box w-fit">
        {filters.map((f) => (
          <button key={f.id} role="tab" className={`tab gap-1.5 ${filter === f.id ? 'tab-active' : ''}`} onClick={() => setFilter(f.id)}>
            {f.label}<span className="badge badge-xs">{count(f)}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel lg:col-span-3">
          <div className="panel-body p-2 sm:p-3">
            {cases === null ? (
              <p className="flex items-center gap-2 p-4 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Unavailable — waiting for the database queue.</p>
            ) : shown.length === 0 ? (
              <div className="p-8 text-center text-sm opacity-70">{cases.length === 0 ? 'No review cases in the current database.' : 'Nothing in this view.'}</div>
            ) : (
              <ul className="flex flex-col gap-1">
                {shown.map((item) => (
                  <li key={item.case_id}>
                    <button onClick={() => { setSelected(item); setNote(''); }}
                      className={`flex w-full items-center gap-3 rounded-box px-3 py-3 text-left transition hover:bg-base-200 ${selected?.case_id === item.case_id ? 'bg-primary/10 ring-1 ring-primary' : ''}`}>
                      <span className="font-mono text-sm font-semibold">#{item.case_id}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{item.reason.replaceAll('_', ' ')}</span>
                        <span className="block truncate text-[11px] opacity-60">{item.agent_id || 'no agent'} · {slaText(item)}</span>
                      </span>
                      <span className="flex flex-col items-end gap-1">
                        <span className={`badge badge-sm ${priorityTone[item.priority]}`}>{item.priority}</span>
                        <span className={`badge badge-xs ${item.sla_breached ? 'badge-error' : statusTone(item.status)}`}>{item.sla_breached ? 'past target' : item.status}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="panel h-fit lg:col-span-2">
          <div className="panel-body">
            {!selected ? (
              <div className="py-8 text-center text-sm opacity-60">Select a case to review its evidence.</div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">Case #{selected.case_id} · {selected.reason.replaceAll('_', ' ')}</h3>
                  <span className={`badge ${priorityTone[selected.priority]}`}>{selected.priority} · {slaText(selected)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="muted font-mono">{selected.mandate_id || 'no mandate'}</span>
                  {selected.agent_id && <>
                    <span className="muted">· agent {selected.agent_id}</span>
                    <WatchButton agentId={selected.agent_id} watchlisted={watch.has(selected.agent_id)} caseId={selected.case_id} onChange={refresh} />
                  </>}
                </div>
                {selected.reason === 'duress_signal' && (
                  <div className="alert alert-error alert-soft text-sm"><Icon name="warning" /><span>Silent duress. Call the customer on the registered number, away from the agent, before anything else.</span></div>
                )}
                <CaseBrief key={selected.case_id} caseId={selected.case_id} />
                <details className="collapse collapse-arrow bg-base-200" open>
                  <summary className="collapse-title min-h-0 py-2 text-sm">Timeline</summary>
                  <div className="collapse-content"><Timeline key={selected.case_id} caseId={selected.case_id} /></div>
                </details>
                <details className="collapse collapse-arrow bg-base-200">
                  <summary className="collapse-title min-h-0 py-2 text-sm">Raw evidence</summary>
                  <div className="collapse-content"><pre className="json-block">{JSON.stringify(selected.evidence, null, 2)}</pre></div>
                </details>
                <label className="w-full">
                  <span className="mb-1 block text-sm">Human review note</span>
                  <textarea className="textarea textarea-bordered w-full" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {decisions.map((d) => (
                    <button key={d.id} className={`btn btn-sm btn-soft ${d.tone}`} disabled={busy} onClick={() => decide(d.id)}>{d.label}</button>
                  ))}
                </div>
                <p className="muted">Decisions are audited. They never redeem or authorize cash-out.</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
