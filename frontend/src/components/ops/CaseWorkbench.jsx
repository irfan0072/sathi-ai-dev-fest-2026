import { useEffect, useState } from 'react';
import { api } from '../../api';
import Icon from '../Icon';
import CaseBrief from '../CaseBrief';
import { WatchButton } from '../CommandCenter';
import {
  Alert, AssignMenu, Badge, Empty, LiveDot, PageHead, Panel, Pager, Tabs, bdt, pct, priorityTone,
  timeAgo, usePoll, useSupervisors, when,
} from './kit';

const statusTone = { open: 'badge-info', escalated: 'badge-error', approved: 'badge-success', denied: 'badge-error' };
const statusText = { open: 'Open', escalated: 'Escalated', approved: 'Cleared', denied: 'Problem confirmed' };
const noteTone = { critical: 'border-error/50 bg-error/5', message: 'border-base-300', call_log: 'border-primary/40 bg-primary/5', audit: 'border-success/40 bg-success/5', system: 'border-dashed border-base-300' };
const noteLabel = { critical: 'Critical', message: 'Message', call_log: 'Call log', audit: 'Audit', system: 'System' };

const slaText = (c) => {
  if (!['open', 'escalated'].includes(c.status)) return `closed ${timeAgo(c.closed_at)}`;
  const left = c.sla_minutes - c.age_minutes;
  const fmt = (m) => (Math.abs(m) >= 60 ? `${Math.round(Math.abs(m) / 60)}h` : `${Math.round(Math.abs(m))}m`);
  return left >= 0 ? `${fmt(left)} left` : `${fmt(left)} late`;
};

function Timeline({ caseId }) {
  const [events, setEvents] = useState(null);
  useEffect(() => {
    let live = true;
    api.getCaseTimeline(caseId).then((v) => live && setEvents(v.events)).catch(() => live && setEvents([]));
    return () => { live = false; };
  }, [caseId]);
  if (!events) return <span className="loading loading-dots loading-xs" />;
  return (
    <ol className="relative ml-1 border-l border-base-300 pl-4">
      {events.map((e, i) => (
        <li key={i} className="mb-2 last:mb-0 text-sm">
          <span className={`absolute -left-[5px] mt-1.5 inline-block size-2.5 rounded-full ${e.kind === 'review' ? 'bg-secondary' : e.kind === 'call' ? 'bg-primary' : e.kind === 'case' ? 'bg-error' : 'bg-base-300'}`} />
          <div>{e.label.replaceAll('_', ' ')}</div>
          <div className="muted text-xs">{e.actor} · {when(e.at)}</div>
        </li>
      ))}
    </ol>
  );
}

function NoteBox({ caseId, onSaved }) {
  const [type, setType] = useState('message');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (e) => {
    e.preventDefault(); if (!body.trim()) return;
    setBusy(true); setError('');
    try { await api.addCaseNote(caseId, { note_type: type, body }); setBody(''); onSaved(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={save} className="flex flex-col gap-2">
      <div className="flex gap-2">
        {['message', 'critical', 'call_log'].map((t) => (
          <button type="button" key={t} onClick={() => setType(t)}
            className={`btn btn-xs focus-ring ${type === t ? (t === 'critical' ? 'btn-error' : 'btn-primary') : 'btn-ghost border-base-300'}`}>
            {noteLabel[t]}
          </button>
        ))}
      </div>
      <textarea className="textarea textarea-bordered text-sm focus-ring" rows={2} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)}
        placeholder={type === 'critical' ? 'Something others must know right away…' : 'Add a note for the case record…'} />
      <Alert>{error}</Alert>
      <div className="flex justify-end"><button className="btn btn-sm btn-primary focus-ring" disabled={busy || !body.trim()}>Save note</button></div>
    </form>
  );
}

function AuditForm({ caseId, onSaved }) {
  const [form, setForm] = useState({ decision: 'denied', risk_level: 'high', customer_contacted: true, findings: '', action_taken: '', recommendation: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try { await api.submitAuditReport(caseId, { ...form, recommendation: form.recommendation || null }); onSaved(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-box border border-secondary/30 bg-secondary/5 p-4">
      <div className="font-semibold">Audit report and decision</div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="form-control">
          <span className="mb-1 text-xs font-medium">Decision</span>
          <select className="select select-bordered select-sm focus-ring" value={form.decision} onChange={set('decision')}>
            <option value="approved">Cleared: no wrongdoing</option>
            <option value="denied">Problem confirmed</option>
            <option value="escalated">Escalate to fraud team</option>
          </select>
        </label>
        <label className="form-control">
          <span className="mb-1 text-xs font-medium">Risk level</span>
          <select className="select select-bordered select-sm focus-ring" value={form.risk_level} onChange={set('risk_level')}>
            {['low', 'medium', 'high', 'critical'].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 pt-5 text-sm">
          <input type="checkbox" className="checkbox checkbox-sm" checked={form.customer_contacted} onChange={set('customer_contacted')} />
          Customer contacted
        </label>
      </div>
      <label className="form-control">
        <span className="mb-1 text-xs font-medium">Findings (what you found)</span>
        <textarea required minLength={10} maxLength={4000} rows={3} className="textarea textarea-bordered text-sm focus-ring" value={form.findings} onChange={set('findings')} />
      </label>
      <label className="form-control">
        <span className="mb-1 text-xs font-medium">Action taken</span>
        <textarea required minLength={3} maxLength={2000} rows={2} className="textarea textarea-bordered text-sm focus-ring" value={form.action_taken} onChange={set('action_taken')} />
      </label>
      <label className="form-control">
        <span className="mb-1 text-xs font-medium">Recommendation (optional)</span>
        <textarea maxLength={2000} rows={2} className="textarea textarea-bordered text-sm focus-ring" value={form.recommendation} onChange={set('recommendation')} />
      </label>
      <Alert>{error}</Alert>
      <div className="flex justify-end"><button className="btn btn-secondary btn-sm focus-ring" disabled={busy}>File report and close case</button></div>
    </form>
  );
}

export function ReportView({ r }) {
  return (
    <article className="flex flex-col gap-1.5 rounded-box border border-base-300 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <strong>Report #{r.report_id}</strong>
        <Badge tone={r.decision === 'denied' ? 'badge-error' : r.decision === 'approved' ? 'badge-success' : 'badge-warning'}>{r.decision_text}</Badge>
        <Badge tone={r.risk_level === 'critical' || r.risk_level === 'high' ? 'badge-error' : 'badge-ghost'}>risk {r.risk_level}</Badge>
        <span className="muted ml-auto text-xs">{r.author_name || r.author} · {when(r.created_at)}</span>
      </div>
      <div><span className="muted">Findings: </span>{r.findings}</div>
      <div><span className="muted">Action: </span>{r.action_taken}</div>
      {r.recommendation && <div><span className="muted">Recommendation: </span>{r.recommendation}</div>}
      <div className="muted text-xs">Customer contacted: {r.customer_contacted ? 'yes' : 'no'}</div>
    </article>
  );
}

function CaseFile({ caseId, session, supervisors, onChanged, onClose }) {
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(false);
  const isAdmin = session.role === 'super_admin';
  const load = async () => {
    try {
      const f = await api.getCaseFile(caseId);
      setFile(f); setError('');
      setWatch(Boolean(f.agent_profile?.watchlisted));
    } catch (err) { setError(err.message); }
  };
  useEffect(() => { load(); }, [caseId]);
  const act = async (fn) => {
    setBusy(true); setError('');
    try { await fn(); await load(); onChanged(); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  if (!file) return <Panel><Alert>{error}</Alert>{!error && <span className="loading loading-dots loading-sm" />}</Panel>;
  const open = ['open', 'escalated'].includes(file.status);
  const ev = file.evidence || {};
  return (
    <Panel
      title={<span className="flex flex-wrap items-center gap-2">Case #{file.case_id} <Badge tone={statusTone[file.status]}>{statusText[file.status]}</Badge> <Badge tone={priorityTone[file.priority]}>{file.priority}</Badge></span>}
      action={<button className="btn btn-ghost btn-xs btn-circle" onClick={onClose} aria-label="Close"><Icon name="x" className="size-4" /></button>}
    >
      <Alert>{error}</Alert>
      <div className="rounded-box bg-base-200/60 p-3 text-sm">
        <div className="font-semibold capitalize">{file.reason_text}</div>
        <div className="mt-1 grid gap-x-4 gap-y-1 sm:grid-cols-2">
          {file.user_id && <span>Customer <span className="font-mono">{file.user_id}</span></span>}
          {file.agent_id && <span>Agent <span className="font-mono">{file.agent_id}</span></span>}
          {ev.ledger_amount != null && <span>Ledger {bdt(ev.ledger_amount)}</span>}
          {ev.stated_amount != null && <span>Customer said {bdt(ev.stated_amount)}</span>}
          {ev.difference != null && <span className="text-error">Gap {bdt(ev.difference)}</span>}
          {ev.channel && <span>Found by {ev.channel}</span>}
          <span>{slaText(file)}</span>
          <span>Assigned: {file.assignee_name || file.assigned_to || 'nobody'}</span>
        </div>
        {ev.guidance && <div className="mt-2 rounded bg-error/10 p-2 text-error">{ev.guidance}</div>}
        {ev.reasons?.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-xs">{ev.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        )}
        {file.agent_profile && (
          <div className="muted mt-2 text-xs">Agent last 30 days: {file.agent_profile.suspicious_30d} suspicious of {file.agent_profile.checks_30d} checks{file.agent_profile.watchlisted ? ' · on watchlist' : ''}</div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {session.role === 'supervisor' && open && !file.assigned_to && (
          <button className="btn btn-primary btn-sm focus-ring" disabled={busy} onClick={() => act(() => api.claimCase(file.case_id))}>Take this case</button>
        )}
        {open && file.assigned_to && (file.assigned_to === session.subject || isAdmin) && (
          <button className="btn btn-ghost btn-sm border-base-300 focus-ring" disabled={busy} onClick={() => act(() => api.releaseCase(file.case_id))}>Put back in queue</button>
        )}
        {isAdmin && open && <AssignMenu supervisors={supervisors} disabled={busy} onAssign={(id) => act(() => api.assignCase(file.case_id, id))} />}
        {isAdmin && file.agent_id && (
          <WatchButton agentId={file.agent_id} watchlisted={watch} caseId={file.case_id} onChange={load} />
        )}
      </div>

      {file.responses?.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-semibold">Customer responses on record</div>
          <ul className="flex flex-col gap-1 text-xs">
            {file.responses.map((r, i) => (
              <li key={i} className="rounded bg-base-200/60 px-2 py-1">
                <strong>{r.channel === 'manual' ? `Supervisor (${r.recorded_by})` : 'AI call'}</strong>: {r.interpreted}
                {r.amount != null ? ` ৳${r.amount}` : ''}{r.raw_input ? ` · "${r.raw_input}"` : ''}{r.confidence != null ? ` · ${pct(r.confidence)} sure` : ''}
                <span className="muted"> · {timeAgo(r.at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <CaseBrief key={file.case_id} caseId={file.case_id} canGenerate />

      <div>
        <div className="mb-1 text-sm font-semibold">Notes</div>
        <ul className="flex flex-col gap-1.5">
          {file.notes_list.length === 0 && <li className="muted">No notes yet.</li>}
          {file.notes_list.map((n) => (
            <li key={n.note_id} className={`rounded-lg border p-2 text-sm ${noteTone[n.note_type]}`}>
              <div className="flex items-center gap-2 text-xs">
                <Badge tone={n.note_type === 'critical' ? 'badge-error' : 'badge-ghost'}>{noteLabel[n.note_type]}</Badge>
                <span className="font-medium">{n.author_name || n.author}</span>
                <span className="muted ml-auto">{when(n.at)}</span>
              </div>
              <div className="mt-1 whitespace-pre-wrap">{n.body}</div>
            </li>
          ))}
        </ul>
      </div>
      {file.can_act && <NoteBox caseId={file.case_id} onSaved={load} />}
      {file.reports.map((r) => <ReportView key={r.report_id} r={r} />)}
      {file.can_act && <AuditForm caseId={file.case_id} onSaved={() => { load(); onChanged(); }} />}
      {open && !file.can_act && session.role === 'supervisor' && (
        <p className="muted">Take this case to add notes and write the audit report.</p>
      )}
      <details>
        <summary className="cursor-pointer text-sm font-semibold">Timeline</summary>
        <div className="mt-2"><Timeline caseId={file.case_id} /></div>
      </details>
    </Panel>
  );
}

export default function CaseWorkbench({ session, initialCaseId = null }) {
  const isAdmin = session.role === 'super_admin';
  const scopes = isAdmin
    ? [{ id: 'open', label: 'Open' }, { id: 'pending', label: 'Unassigned' }, { id: 'assigned', label: 'Assigned' }, { id: 'closed', label: 'Closed' }, { id: 'all', label: 'All' }]
    : [{ id: 'pending', label: 'Pending' }, { id: 'mine', label: 'My cases' }, { id: 'my_closed', label: 'Closed by me' }];
  const [scope, setScope] = useState(initialCaseId ? (isAdmin ? 'all' : 'pending') : scopes[0].id);
  const [selected, setSelected] = useState(initialCaseId);
  const [extra, setExtra] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState('');
  const [data, error, reload] = usePoll(() => api.getCaseQueue({ scope, limit: 100 }), 6000, [scope]);
  const supervisors = useSupervisors(isAdmin, api);
  useEffect(() => { setExtra([]); setCursor(null); }, [scope]);
  useEffect(() => { if (data && !extra.length) setCursor(data.next_before_id); }, [data, extra.length]);
  const items = [...(data?.cases || []), ...extra];

  const claim = async (id) => {
    setFlash('');
    try { await api.claimCase(id); setSelected(id); setScope('mine'); }
    catch (err) { setFlash(err.message); }
    reload();
  };
  const more = async () => {
    setBusy(true);
    try { const r = await api.getCaseQueue({ scope, limit: 100, before_id: cursor }); setExtra((x) => [...x, ...r.cases]); setCursor(r.next_before_id); }
    finally { setBusy(false); }
  };
  const distribute = async () => {
    setFlash('');
    try { const r = await api.distributeCases(); setFlash(`Assigned ${r.total} case(s) across supervisors.`); }
    catch (err) { setFlash(err.message); }
    reload();
  };
  return (
    <div className="flex flex-col gap-5">
      <PageHead
        title={isAdmin ? 'Cases' : 'Cases to review'}
        lead={isAdmin
          ? 'Cases open automatically when a customer disputes a cash-out. Assign them to a supervisor or share the queue evenly; every case ends with an audit report.'
          : 'Take a case from the pending list, check it with the customer, write notes (mark critical ones), then file an audit report with your decision.'}
      >
        <LiveDot />
        {isAdmin && <button className="btn btn-sm btn-primary focus-ring" onClick={distribute}>Share unassigned cases evenly</button>}
      </PageHead>
      <Alert kind="info">{flash}</Alert>
      <Alert>{error}</Alert>
      <Tabs items={scopes.map((t) => ({ ...t, count: t.id === 'pending' ? data?.counts?.pending : t.id === 'mine' ? data?.counts?.mine : undefined }))}
        value={scope} onChange={(v) => { setScope(v); setSelected(null); }} />
      <div className={`grid gap-4 ${selected ? 'xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]' : ''}`}>
        <Panel bodyClass="p-0">
          {items.length === 0 ? <Empty title={data ? 'No cases here' : 'Loading…'} /> : (
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead><tr><th>Case</th><th>Priority</th><th>Reason</th><th>Agent</th><th>Amount</th><th>Due</th><th>Assignee</th>{session.role === 'supervisor' && <th />}</tr></thead>
                <tbody>
                  {items.map((c) => (
                    <tr key={c.case_id} onClick={() => setSelected(c.case_id)} className={`cursor-pointer hover:bg-base-200/60 ${selected === c.case_id ? 'bg-primary/5' : ''}`}>
                      <td className="font-mono text-xs">#{c.case_id}{c.critical_notes > 0 && <span className="badge badge-error badge-xs ml-1">!</span>}</td>
                      <td><Badge tone={priorityTone[c.priority]}>{c.priority}</Badge></td>
                      <td className="max-w-[16rem] truncate text-xs capitalize" title={c.reason_text}>{c.reason_text}</td>
                      <td className="font-mono text-xs">{c.agent_id || '—'}</td>
                      <td className="tabular-nums">{bdt(c.amount ?? c.evidence?.ledger_amount)}</td>
                      <td className={`text-xs ${c.sla_breached ? 'font-semibold text-error' : ''}`}>{slaText(c)}</td>
                      <td className="text-xs">{c.assignee_name || c.assigned_to || '—'}</td>
                      {session.role === 'supervisor' && (
                        <td>{['open', 'escalated'].includes(c.status) && !c.assigned_to && (
                          <button className="btn btn-xs btn-primary focus-ring" onClick={(e) => { e.stopPropagation(); claim(c.case_id); }}>Take</button>
                        )}</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager hasMore={Boolean(cursor)} busy={busy} onMore={more} />
        </Panel>
        {selected && <CaseFile key={selected} caseId={selected} session={session} supervisors={supervisors} onChanged={reload} onClose={() => setSelected(null)} />}
      </div>
    </div>
  );
}
