import { useEffect, useState } from 'react';
import { api } from '../../api';
import Icon from '../Icon';
import {
  Alert, AssignMenu, Badge, Empty, Kpi, LiveDot, PageHead, Panel, Pager, Tabs, bdt, manualReason,
  num, pct, priorityTone, taskLabel, taskTone, timeAgo, usePoll, useSupervisors, when, checkText, checkTone,
} from './kit';

const RESULTS = [
  { id: 'confirmed', label: 'Customer confirmed the amount', needsAmount: true, tone: 'success' },
  { id: 'amount_mismatch', label: 'Customer got a different amount', needsAmount: true, tone: 'error' },
  { id: 'denied', label: 'Customer did not make this cash-out', tone: 'error' },
  { id: 'duress', label: 'Customer was forced / asked for help', tone: 'error' },
  { id: 'callback', label: 'Call back later', tone: 'warning' },
  { id: 'unreachable', label: 'Could not reach the customer', tone: 'ghost' },
];
const interpretedText = {
  amount: 'said an amount', denied: 'said they did not do it', duress: 'secret help signal',
  unclear: 'AI could not understand', no_answer: 'did not pick up', callback: 'asked for call back',
  unreachable: 'unreachable', no_input: 'stayed silent', human_requested: 'asked for a person',
  language_switch: 'switched language',
};

function OutcomeForm({ task, onDone }) {
  const [result, setResult] = useState('confirmed');
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const chosen = RESULTS.find((r) => r.id === result);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await api.recordCallOutcome(task.task_id, {
        result, note: note || null,
        stated_amount: chosen.needsAmount ? amount : null,
        callback_minutes: result === 'callback' ? Number(minutes) : null,
      });
      onDone();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-box border border-primary/30 bg-primary/5 p-4">
      <div className="font-semibold">What did the customer say?</div>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {RESULTS.map((r) => (
          <label key={r.id} className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${result === r.id ? 'border-primary bg-base-100' : 'border-base-300'}`}>
            <input type="radio" className="radio radio-sm radio-primary" checked={result === r.id} onChange={() => setResult(r.id)} />
            {r.label}
          </label>
        ))}
      </div>
      {chosen.needsAmount && (
        <label className="form-control">
          <span className="mb-1 text-sm font-medium">Amount the customer says they received (৳)</span>
          <input className="input input-bordered w-48 font-mono focus-ring" inputMode="numeric" required value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ''))} />
          <span className="muted mt-1">Ask "how much cash did you get?". Never say the amount first.</span>
        </label>
      )}
      {result === 'callback' && (
        <label className="form-control">
          <span className="mb-1 text-sm font-medium">Call again in (minutes)</span>
          <input type="number" min="5" max="10080" className="input input-bordered w-32 focus-ring" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
        </label>
      )}
      <label className="form-control">
        <span className="mb-1 text-sm font-medium">Call note (saved to the record)</span>
        <textarea className="textarea textarea-bordered focus-ring" rows={3} maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What the customer said, in their words." />
      </label>
      <Alert>{error}</Alert>
      <div className="flex justify-end">
        <button className="btn btn-primary focus-ring" disabled={busy}>
          {busy ? <span className="loading loading-spinner loading-sm" /> : 'Save outcome'}
        </button>
      </div>
      {['amount_mismatch', 'denied', 'duress'].includes(result) && (
        <p className="muted">Saving opens a case automatically with your note attached.</p>
      )}
    </form>
  );
}

function TaskDetail({ taskId, session, supervisors, onChanged, onClose }) {
  const [task, setTask] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const isAdmin = session.role === 'super_admin';
  const load = async () => {
    try { setTask(await api.getCallTask(taskId)); setError(''); }
    catch (err) { setError(err.message); }
  };
  useEffect(() => { load(); }, [taskId]);
  const act = async (fn) => {
    setBusy(true); setError('');
    try { await fn(); await load(); onChanged(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  if (!task) return <Panel><Alert>{error}</Alert>{!error && <span className="loading loading-dots loading-sm" />}</Panel>;
  const mine = task.assigned_to === session.subject;
  const active = ['assigned', 'in_progress'].includes(task.status);
  return (
    <Panel
      title={<span className="flex items-center gap-2">Call #{task.task_id} <Badge tone={taskTone[task.status]}>{taskLabel[task.status]}</Badge></span>}
      action={<button className="btn btn-ghost btn-xs btn-circle" onClick={onClose} aria-label="Close"><Icon name="x" className="size-4" /></button>}
    >
      <Alert>{error}</Alert>
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <div className="muted">Customer</div>
          <div className="font-mono">{task.user_id}</div>
          <div className="muted capitalize">{task.customer?.region} · {task.customer?.area} · {task.customer?.age_band}</div>
        </div>
        <div>
          <div className="muted">Cash-out</div>
          <div><strong>{bdt(task.amount)}</strong> via agent <span className="font-mono">{task.agent_id}</span></div>
          <div className="muted">{when(task.transaction?.ts)} · txn #{task.txn_id}</div>
        </div>
        <div>
          <div className="muted">Why a person is needed</div>
          <div>{manualReason[task.manual_reason] || '—'}</div>
        </div>
        <div>
          <div className="muted">Check</div>
          <Badge tone={checkTone[task.check_status]}>{checkText[task.check_status] || task.check_status}</Badge>
          {task.case_id && <span className="ml-2">case #{task.case_id}</span>}
        </div>
        <div>
          <div className="muted">Attempts</div>
          <div>{task.auto_attempts} automatic · {task.manual_attempts} by supervisor</div>
        </div>
        <div>
          <div className="muted">Assigned</div>
          <div>{task.assignee_name || task.assigned_to || 'Nobody yet'}{task.assigned_by && task.assigned_by !== task.assigned_to ? <span className="muted"> · by {task.assigned_by}</span> : ''}</div>
        </div>
      </div>

      <div>
        <div className="mb-1 text-sm font-semibold">Recorded customer responses</div>
        {task.responses.length === 0 ? <p className="muted">No answers recorded yet.</p> : (
          <ol className="flex flex-col gap-1.5 text-sm">
            {task.responses.map((r) => (
              <li key={r.response_id} className="flex flex-wrap items-baseline gap-x-2 rounded-lg bg-base-200/60 px-2 py-1">
                <Badge tone={r.interpreted === 'unclear' ? 'badge-secondary' : r.interpreted === 'no_answer' ? 'badge-ghost' : 'badge-info'}>{r.channel === 'manual' ? 'Supervisor' : 'AI call'}</Badge>
                <span>{interpretedText[r.interpreted] || r.interpreted}{r.amount != null ? `: ৳${r.amount}` : ''}</span>
                {r.raw_input && <span className="muted italic">"{r.raw_input}"</span>}
                {r.confidence != null && <span className="muted">· confidence {pct(r.confidence)}</span>}
                <span className="muted ml-auto text-xs">{timeAgo(r.at)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {task.calls.length > 0 && (
        <div className="text-xs">
          <span className="font-semibold">Calls placed: </span>
          {task.calls.map((c) => `${c.status} (${timeAgo(c.at)})`).join(' → ')}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {session.role === 'supervisor' && task.status === 'needs_manual' && !task.assigned_to && (
          <button className="btn btn-primary btn-sm focus-ring" disabled={busy} onClick={() => act(() => api.claimCall(task.task_id))}>Take this call</button>
        )}
        {session.role === 'supervisor' && mine && task.status === 'assigned' && (
          <button className="btn btn-primary btn-sm focus-ring" disabled={busy} onClick={() => act(() => api.startCall(task.task_id))}>
            <Icon name="phone" className="size-4" /> Start call
          </button>
        )}
        {active && (mine || isAdmin) && (
          <button className="btn btn-ghost btn-sm border-base-300 focus-ring" disabled={busy} onClick={() => act(() => api.releaseCall(task.task_id))}>Put back in queue</button>
        )}
        {isAdmin && ['needs_manual', 'assigned', 'retry_scheduled', 'ignored', 'auto'].includes(task.status) && (
          <AssignMenu supervisors={supervisors} disabled={busy} onAssign={(id) => act(() => api.assignCall(task.task_id, id))} />
        )}
        {isAdmin && ['retry_scheduled', 'ignored', 'auto'].includes(task.status) && (
          <button className="btn btn-warning btn-sm focus-ring" disabled={busy} onClick={() => act(() => api.escalateCall(task.task_id))}>Send to supervisors</button>
        )}
      </div>

      {active && (mine || isAdmin) && (
        <OutcomeForm task={task} onDone={() => { load(); onChanged(); }} />
      )}

      {task.history.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold">History ({task.history.length})</summary>
          <ul className="mt-1 flex flex-col gap-1">
            {task.history.map((h, i) => (
              <li key={i}>{when(h.at)} · <strong>{h.action.replace('call_task_', '').replaceAll('_', ' ')}</strong> by {h.actor}{h.detail?.to ? ` → ${h.detail.to}` : ''}{h.detail?.note ? ` · "${h.detail.note}"` : ''}</li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function TaskRow({ t, selected, onSelect, session, onClaim }) {
  return (
    <tr className={`cursor-pointer hover:bg-base-200/60 ${selected ? 'bg-primary/5' : ''}`} onClick={() => onSelect(t.task_id)}>
      <td className="font-mono text-xs">#{t.task_id}</td>
      <td><Badge tone={priorityTone[t.priority]}>{t.priority}</Badge></td>
      <td className="font-mono text-xs">{t.user_id}</td>
      <td className="tabular-nums">{bdt(t.amount)}</td>
      <td className="text-xs">{manualReason[t.manual_reason] || t.last_outcome || '—'}</td>
      <td><Badge tone={taskTone[t.status]}>{taskLabel[t.status]}</Badge></td>
      <td className="text-xs">{t.status === 'retry_scheduled' ? `next ${timeAgo(t.next_attempt_at)}` : t.assignee_name || t.assigned_to || '—'}</td>
      <td className="text-xs">{t.auto_attempts}/{t.manual_attempts}</td>
      <td className="muted text-xs">{timeAgo(t.updated_at)}</td>
      {session.role === 'supervisor' && (
        <td>
          {t.status === 'needs_manual' && !t.assigned_to && (
            <button className="btn btn-xs btn-primary focus-ring" onClick={(e) => { e.stopPropagation(); onClaim(t.task_id); }}>Take</button>
          )}
        </td>
      )}
    </tr>
  );
}

export default function CallCenter({ session }) {
  const isAdmin = session.role === 'super_admin';
  const scopes = isAdmin
    ? [{ id: 'manual', label: 'Needs a person' }, { id: 'pending', label: 'Unassigned' }, { id: 'retrying', label: 'Retrying' },
      { id: 'ignored', label: 'Ignored' }, { id: 'resolved', label: 'Resolved' }, { id: 'all', label: 'All' }]
    : [{ id: 'pending', label: 'Pending' }, { id: 'mine', label: 'My calls' }, { id: 'my_history', label: 'Done by me' }];
  const [scope, setScope] = useState(scopes[0].id);
  const [selected, setSelected] = useState(null);
  const [extra, setExtra] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState('');
  const [data, error, reload] = usePoll(() => api.getCallQueue({ scope, limit: 50 }), 5000, [scope]);
  const [stats, , reloadStats] = usePoll(() => (isAdmin ? api.getCallStats() : Promise.resolve(null)), 8000);
  const supervisors = useSupervisors(isAdmin, api);

  useEffect(() => { setExtra([]); setCursor(null); }, [scope]);
  useEffect(() => { if (data) setCursor((c) => (extra.length ? c : data.next_before_id)); }, [data, extra.length]);
  const items = [...(data?.items || []), ...extra];

  const refresh = () => { reload(); reloadStats(); };
  const claim = async (id) => {
    setFlash('');
    try { await api.claimCall(id); setSelected(id); setScope('mine'); }
    catch (err) { setFlash(err.message); }
    refresh();
  };
  const more = async () => {
    setBusy(true);
    try {
      const r = await api.getCallQueue({ scope, limit: 50, before_id: cursor });
      setExtra((x) => [...x, ...r.items]); setCursor(r.next_before_id);
    } finally { setBusy(false); }
  };
  const distribute = async () => {
    setFlash('');
    try { const r = await api.distributeCalls(); setFlash(`Assigned ${r.total} call(s) across supervisors.`); }
    catch (err) { setFlash(err.message); }
    refresh();
  };
  const s = stats;
  return (
    <div className="flex flex-col gap-5">
      <PageHead
        title={isAdmin ? 'Call management' : 'Call queue'}
        lead={isAdmin
          ? 'Every confirmation call: automatic retries for missed calls, customers marked unreachable after all retries, and answers the AI could not understand waiting for a supervisor.'
          : 'Customers the AI could not confirm. Take a call from the pending list, phone the customer, and record what they said. Two supervisors can never take the same call.'}
      >
        <LiveDot />
        {isAdmin && <button className="btn btn-sm btn-primary focus-ring" onClick={distribute}>Share pending calls evenly</button>}
      </PageHead>
      <Alert kind="info">{flash}</Alert>
      <Alert>{error}</Alert>

      {isAdmin && s && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <Kpi icon="phone" label="Answer rate, 24h" value={pct(s.calls_24h.answer_rate)} note={`${num(s.calls_24h.total)} calls placed`} tone="bg-success/15 text-success" />
          <Kpi icon="refresh" label="Retrying" value={num(s.retrying)} note={s.next_retry_at ? `next ${timeAgo(s.next_retry_at)}` : 'none due'} tone="bg-info/15 text-info" />
          <Kpi icon="users" label="Waiting for a person" value={num(s.manual_waiting)} note={`${num(s.manual_active)} in progress`} tone="bg-warning/20 text-warning-content" />
          <Kpi icon="x" label="Ignored (unreachable)" value={num(s.ignored)} note={`after ${s.policy.max_auto_attempts} tries`} />
          <Kpi icon="check" label="Recovered by retry" value={num(s.recovered_by_retry_24h)} note={`avg ${s.avg_auto_attempts} tries · manual ${s.avg_manual_resolution_minutes}m`} tone="bg-primary/15 text-primary" />
        </div>
      )}
      {isAdmin && s && (
        <p className="muted -mt-2">
          Policy: up to {s.policy.max_auto_attempts} automatic calls, first retry after {s.policy.retry_delay_seconds}s (doubling), ring timeout {s.policy.ring_timeout_seconds}s,
          spoken answers below {pct(s.policy.unclear_confidence)} confidence go to a person. Change in Settings → Call management.
        </p>
      )}

      <Tabs
        items={scopes.map((t) => ({ ...t, count: t.id === 'pending' ? data?.counts?.pending : t.id === 'mine' ? data?.counts?.mine : undefined }))}
        value={scope} onChange={(v) => { setScope(v); setSelected(null); }}
      />

      <div className={`grid gap-4 ${selected ? 'xl:grid-cols-[1fr_1fr]' : ''}`}>
        <Panel bodyClass="p-0">
          {items.length === 0 ? (
            <Empty title={data ? 'Nothing here right now' : 'Loading…'} body={scope === 'pending' ? 'When the AI cannot confirm a customer, the call appears here.' : undefined} />
          ) : (
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead>
                  <tr><th>#</th><th>Priority</th><th>Customer</th><th>Amount</th><th>Reason</th><th>Status</th><th>{scope === 'retrying' ? 'Next try' : 'Assignee'}</th><th>Tries</th><th>Updated</th>{session.role === 'supervisor' && <th />}</tr>
                </thead>
                <tbody>
                  {items.map((t) => <TaskRow key={t.task_id} t={t} selected={selected === t.task_id} onSelect={setSelected} session={session} onClaim={claim} />)}
                </tbody>
              </table>
            </div>
          )}
          <Pager hasMore={Boolean(cursor)} busy={busy} onMore={more} />
        </Panel>
        {selected && (
          <TaskDetail key={selected} taskId={selected} session={session} supervisors={supervisors}
            onChanged={refresh} onClose={() => setSelected(null)} />
        )}
      </div>
    </div>
  );
}
