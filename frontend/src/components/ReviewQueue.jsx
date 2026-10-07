import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import CaseBrief from './CaseBrief';
import { WatchButton } from './CommandCenter';
import { caseStatus, eventLabel, priorityName, reasonLabel } from '../copy';
import { phone } from '../ids';
import { FollowupNotice } from './ops/kit';

const decisions = [
  { id: 'approved', label: 'Cleared: no wrongdoing', tone: 'btn-success' },
  { id: 'denied', label: 'Problem confirmed', tone: 'btn-error' },
  { id: 'escalated', label: 'Escalate to fraud team', tone: 'btn-warning' },
];
const priorityTone = { urgent: 'badge-error', high: 'badge-warning', normal: 'badge-ghost' };
const statusTone = (status) => (status === 'open' ? 'badge-info' : status === 'escalated' ? 'badge-error' : 'badge-ghost');
const filters = [
  { id: 'open', label: 'Open', test: (c) => ['open', 'escalated'].includes(c.status) },
  { id: 'urgent', label: 'Urgent', test: (c) => c.priority === 'urgent' && ['open', 'escalated'].includes(c.status) },
  { id: 'overdue', label: 'Late', test: (c) => c.sla_breached },
  { id: 'all', label: 'All', test: () => true },
];

const slaText = (c) => {
  if (!['open', 'escalated'].includes(c.status)) return 'closed';
  const left = c.sla_minutes - c.age_minutes;
  const fmt = (m) => (Math.abs(m) >= 60 ? `${Math.round(Math.abs(m) / 60)}h` : `${Math.round(Math.abs(m))}m`);
  return left >= 0 ? `${fmt(left)} left to respond` : `${fmt(left)} late`;
};

function Timeline({ caseId, onFollowup = () => {} }) {
  const [events, setEvents] = useState(null);
  useEffect(() => {
    let live = true;
    api.getCaseTimeline(caseId).then((v) => { if (live) { setEvents(v.events); onFollowup(v.followup); } }).catch(() => { if (live) setEvents([]); });
    return () => { live = false; };
  }, [caseId]);
  if (!events) return <span className="loading loading-dots loading-xs" />;
  return (
    <ol className="relative ml-1 border-l border-base-300 pl-4">
      {events.map((e, i) => (
        <li key={i} className="mb-3 last:mb-0">
          <span className={`absolute -left-[5px] mt-1.5 inline-block size-2.5 rounded-full ${e.kind === 'review' ? 'bg-secondary' : e.kind === 'call' ? 'bg-primary' : e.kind === 'case' ? 'bg-error' : 'bg-base-300'}`} />
          <div className="text-sm">{e.kind === 'audit' ? eventLabel(e.label) : e.label}</div>
          <div className="muted">{e.actor} · {new Date(e.at).toLocaleString()}</div>
        </li>
      ))}
    </ol>
  );
}

export default function ReviewQueue({ initialCaseId = null, session = null }) {
  const [cases, setCases] = useState(null);
  const [watch, setWatch] = useState(new Set());
  const [filter, setFilter] = useState(initialCaseId ? 'all' : 'open');
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [followup, setFollowup] = useState(null);

  const canDecide = session?.role !== 'supervisor';
  const canWatchlist = session?.role !== 'supervisor';

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [result, list] = await Promise.all([
        api.getPrioritizedCases(),
        canWatchlist ? api.getWatchlist() : Promise.resolve({ agents: [] }),
      ]);
      setCases(result.cases);
      setWatch(new Set(list.agents.map((a) => a.agent_id)));
      setSelected((prev) => {
        const want = prev?.case_id ?? initialCaseId;
        return want ? result.cases.find((c) => c.case_id === want) || null : null;
      });
    } catch (err) { setError(err.message); }
  }, [initialCaseId, canWatchlist]);
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
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="page-title">Cases to review</h2>
          <p className="page-lead mt-1">Problems found during cash-outs, most urgent first. Open a case, read what happened, then decide. Your decision never pays out cash.</p>
        </div>
        <button className="btn btn-outline btn-sm focus-ring" onClick={refresh}>
          <Icon name="refresh" className="size-4" />
          Refresh
        </button>
      </div>

      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {message && <div role="status" className="alert alert-success alert-soft text-sm">{message}</div>}

      <div role="tablist" className="tabs tabs-box w-fit">
        {filters.map((f) => (
          <button
            key={f.id}
            role="tab"
            className={`tab gap-1.5 focus-ring ${filter === f.id ? 'tab-active' : ''}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
            <span className="badge badge-xs">{count(f)}</span>
          </button>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel shadow-sm lg:col-span-3">
          <div className="panel-body p-2 sm:p-3">
            {cases === null ? (
              <p className="flex items-center gap-2 p-4 text-sm text-base-content/70">
                <span className="loading loading-dots loading-sm" />
                Unavailable — waiting for the database queue.
              </p>
            ) : shown.length === 0 ? (
              <div className="p-8 text-center text-sm text-base-content/70">
                {cases.length === 0 ? 'No cases right now. Good news!' : 'No cases in this list.'}
              </div>
            ) : (
              <ul className="flex flex-col gap-1">
                {shown.map((item) => (
                  <li key={item.case_id}>
                    <button
                      onClick={() => {
                        setSelected(item);
                        setNote('');
                      }}
                      className={`flex w-full items-center gap-3 rounded-box px-3 py-3 text-left transition focus-ring hover:bg-base-200 ${
                        selected?.case_id === item.case_id ? 'bg-primary/10 ring-1 ring-primary' : ''
                      }`}
                    >
                      <span className="font-mono text-sm font-semibold">#{item.case_id}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{reasonLabel(item.reason)}</span>
                        <span className="block truncate text-[11px] text-base-content/60">
                          Agent {phone(item.agent_id) || '—'} · {slaText(item)}
                        </span>
                      </span>
                      <span className="flex flex-col items-end gap-1">
                        <span className={`badge badge-sm ${priorityTone[item.priority]}`}>{priorityName[item.priority] || item.priority}</span>
                        <span className={`badge badge-xs ${item.sla_breached ? 'badge-error' : statusTone(item.status)}`}>
                          {item.sla_breached ? 'late' : caseStatus[item.status] || item.status}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="panel h-fit shadow-sm lg:col-span-2">
          <div className="panel-body">
            {!selected ? (
              <div className="py-8 text-center text-sm opacity-60">Select a case to review its evidence.</div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold">Case #{selected.case_id} · {reasonLabel(selected.reason)}</h3>
                  <span className={`badge ${priorityTone[selected.priority]}`}>{priorityName[selected.priority] || selected.priority} · {slaText(selected)}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="muted">Reference {selected.mandate_id ? selected.mandate_id.slice(0, 8) : '—'}</span>
                  {selected.agent_id && <>
                    <span className="muted">· agent {phone(selected.agent_id)}</span>
                    {canWatchlist && (
                      <WatchButton agentId={selected.agent_id} watchlisted={watch.has(selected.agent_id)} caseId={selected.case_id} onChange={refresh} />
                    )}
                  </>}
                </div>
                {selected.reason === 'duress_signal' && (
                  <div className="alert alert-error alert-soft text-sm"><Icon name="warning" /><span>The customer asked for help secretly. Call them on their registered number, away from the agent, before anything else.</span></div>
                )}
                <CaseBrief key={selected.case_id} caseId={selected.case_id} canGenerate={canDecide} />
                <details className="collapse collapse-arrow bg-base-200" open>
                  <summary className="collapse-title min-h-0 py-2 text-sm">What happened, step by step</summary>
                  <div className="collapse-content"><Timeline key={selected.case_id} caseId={selected.case_id} onFollowup={setFollowup} /></div>
                </details>
                <details className="collapse collapse-arrow bg-base-200">
                  <summary className="collapse-title min-h-0 py-2 text-sm">Technical details</summary>
                  <div className="collapse-content"><pre className="json-block">{JSON.stringify(selected.evidence, null, 2)}</pre></div>
                </details>
                {canDecide ? (
                  <>
                    <label className="w-full">
                      <span className="mb-1 block text-sm">Your note (optional)</span>
                      <textarea
                        className="textarea textarea-bordered w-full focus-ring"
                        rows={3}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </label>
                    <FollowupNotice followup={followup} />
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {decisions.map((d) => (
                        <button
                          key={d.id}
                          className={`btn btn-sm btn-soft focus-ring ${d.tone}`}
                          disabled={busy}
                          onClick={() => decide(d.id)}
                        >
                          {d.label}
                        </button>
                      ))}
                    </div>
                    <p className="muted">Your decision is saved with your name. It never pays out cash.</p>
                  </>
                ) : (
                  <p className="muted rounded-box border border-base-300 bg-base-200/40 px-3 py-2 text-xs">
                    Read-only view. Case decisions are made by an operator.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
