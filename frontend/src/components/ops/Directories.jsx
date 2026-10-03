import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import Icon from '../Icon';
import { eventLabel } from '../../copy';
import {
  Alert, Badge, Empty, Kpi, LiveDot, PageHead, Panel, Pager, bdt, checkText, checkTone,
  num, pct, timeAgo, usePoll, when,
} from './kit';

/** Keyset-paginated list loader shared by every directory. */
function useKeyset(fetchPage, deps) {
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [total, setTotal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async (next) => {
    setBusy(true); setError('');
    try {
      const page = await fetchPage(next);
      setItems((prev) => (next ? [...prev, ...page.items] : page.items));
      setCursor(page.cursor || null);
      if (page.total) setTotal(page.total);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }, deps);
  useEffect(() => { load(null); }, [load]);
  return { items, cursor, total, busy, error, more: () => load(cursor), reload: () => load(null) };
}

function SearchBox({ value, onChange, placeholder }) {
  const [text, setText] = useState(value);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onChange(text.trim()); }} className="join">
      <input className="input input-bordered input-sm join-item w-56 font-mono focus-ring" value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} />
      <button className="btn btn-sm join-item">Search</button>
    </form>
  );
}

const totalText = (t) => (t ? `${t.exact ? '' : '≈ '}${num(t.value)} total` : '');

// ---------------------------------------------------------------------------- customers
export function UsersPage() {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(null);
  const list = useKeyset(async (after) => {
    const r = await api.getAdminUsers({ q, after, limit: 50 });
    return { items: r.items, cursor: r.next_after, total: r.total };
  }, [q]);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Customers" lead={`Every upay customer account in the system. ${totalText(list.total)}. Search by ID prefix (for example U_9_00001).`}>
        <SearchBox value={q} onChange={setQ} placeholder="U_9_0000123" />
      </PageHead>
      <Alert>{list.error}</Alert>
      <div className={`grid gap-4 ${open ? 'xl:grid-cols-[1fr_1fr]' : ''}`}>
        <Panel bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Customer</th><th>Division</th><th>Area</th><th>Age</th><th>Balance</th><th>Last activity</th><th>Flags</th></tr></thead>
              <tbody>
                {list.items.map((u) => (
                  <tr key={u.user_id} className={`cursor-pointer hover:bg-base-200/60 ${open === u.user_id ? 'bg-primary/5' : ''}`} onClick={() => setOpen(u.user_id)}>
                    <td className="font-mono text-xs">{u.user_id}</td>
                    <td className="capitalize">{u.region}</td>
                    <td className="capitalize">{u.area}</td>
                    <td>{u.age_band}</td>
                    <td className="tabular-nums">{bdt(u.balance)}</td>
                    <td className="muted text-xs">{timeAgo(u.last_activity)}</td>
                    <td>{u.flagged > 0 ? <Badge tone="badge-error">{u.flagged} suspicious</Badge> : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!list.busy && list.items.length === 0 && <Empty title="No customers match" />}
          <Pager hasMore={Boolean(list.cursor)} busy={list.busy} onMore={list.more} />
        </Panel>
        {open && <UserDetail key={open} userId={open} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}

function UserDetail({ userId, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.getAdminUser(userId).then(setD).catch((e) => setError(e.message)); }, [userId]);
  return (
    <Panel title={<span className="font-mono">{userId}</span>} action={<button className="btn btn-ghost btn-xs btn-circle" onClick={onClose} aria-label="Close"><Icon name="x" className="size-4" /></button>}>
      <Alert>{error}</Alert>
      {d && (
        <>
          <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div><div className="muted">Balance</div><strong>{bdt(d.balance)}</strong></div>
            <div><div className="muted">Cash-outs</div><strong>{num(d.cashouts_total)}</strong></div>
            <div><div className="muted">Cashed out</div><strong>{bdt(d.cashout_bdt_total)}</strong></div>
            <div><div className="muted">Division</div><strong className="capitalize">{d.region}</strong></div>
          </div>
          {d.checks.length > 0 && (
            <div>
              <div className="mb-1 text-sm font-semibold">Confirmation checks</div>
              <ul className="flex flex-col gap-1 text-xs">
                {d.checks.map((c) => (
                  <li key={c.check_id} className="flex items-center gap-2">
                    <Badge tone={checkTone[c.status]}>{checkText[c.status]}</Badge> {bdt(c.amount)} via {c.agent_id}
                    {c.case_id && <span>· case #{c.case_id}</span>}<span className="muted ml-auto">{timeAgo(c.at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <div className="mb-1 text-sm font-semibold">Recent transactions</div>
            <table className="table table-xs">
              <thead><tr><th>#</th><th>Type</th><th>Amount</th><th>Agent</th><th>Balance</th><th>When</th></tr></thead>
              <tbody>
                {d.transactions.map((t) => (
                  <tr key={t.txn_id}><td className="font-mono">{t.txn_id}</td><td>{t.txn_type.replace('_', '-')}</td><td>{bdt(t.amount)}</td><td className="font-mono">{t.agent_id || '—'}</td><td>{bdt(t.balance_after)}</td><td className="muted">{when(t.ts)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------- agents
export function AgentsDirectory() {
  const [q, setQ] = useState('');
  const [region, setRegion] = useState('');
  const [open, setOpen] = useState(null);
  const list = useKeyset(async (after) => {
    const r = await api.getAdminAgents({ q, after, region, limit: 50 });
    return { items: r.items, cursor: r.next_after, total: r.total };
  }, [q, region]);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Agents" lead={`All cash-out agents with their last-30-day confirmation record. ${totalText(list.total)}.`}>
        <select className="select select-bordered select-sm focus-ring" value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Division">
          <option value="">All divisions</option>
          {['dhaka', 'chittagong', 'rajshahi', 'khulna', 'barishal', 'sylhet', 'rangpur', 'mymensingh'].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <SearchBox value={q} onChange={setQ} placeholder="A_000042" />
      </PageHead>
      <Alert>{list.error}</Alert>
      <div className={`grid gap-4 ${open ? 'xl:grid-cols-[1fr_1fr]' : ''}`}>
        <Panel bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Agent</th><th>Division</th><th>Volume</th><th>Txns 30d</th><th>Checks</th><th>Suspicious</th><th>Open cases</th><th /></tr></thead>
              <tbody>
                {list.items.map((a) => (
                  <tr key={a.agent_id} className={`cursor-pointer hover:bg-base-200/60 ${open === a.agent_id ? 'bg-primary/5' : ''}`} onClick={() => setOpen(a.agent_id)}>
                    <td className="font-mono text-xs">{a.agent_id}</td>
                    <td className="capitalize">{a.region}</td>
                    <td>{a.volume_band}</td>
                    <td className="tabular-nums">{num(a.txns_30d)}</td>
                    <td className="tabular-nums">{num(a.checks_30d)}</td>
                    <td className={a.suspicious_30d ? 'font-semibold text-error' : ''}>{a.suspicious_30d}{a.suspicious_rate != null && a.suspicious_30d ? ` (${pct(a.suspicious_rate)})` : ''}</td>
                    <td>{a.open_cases || ''}</td>
                    <td>{a.watchlisted && <Badge tone="badge-warning">watchlist</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager hasMore={Boolean(list.cursor)} busy={list.busy} onMore={list.more} />
        </Panel>
        {open && <AgentDetail key={open} agentId={open} onClose={() => setOpen(null)} />}
      </div>
    </div>
  );
}

function AgentDetail({ agentId, onClose }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.getAdminAgent(agentId).then(setD).catch((e) => setError(e.message)); }, [agentId]);
  return (
    <Panel title={<span className="font-mono">{agentId}</span>} action={<button className="btn btn-ghost btn-xs btn-circle" onClick={onClose} aria-label="Close"><Icon name="x" className="size-4" /></button>}>
      <Alert>{error}</Alert>
      {d && (
        <>
          <div className="text-sm capitalize">{d.region} · {d.volume_band} volume{d.watchlist && <span className="normal-case text-warning"> · on watchlist: {d.watchlist.reason}</span>}</div>
          {d.daily.length > 0 && (
            <div className="flex h-16 items-end gap-1" aria-label="Cash-outs per day">
              {d.daily.map((x) => {
                const max = Math.max(...d.daily.map((y) => y.cashouts));
                return <div key={x.day} title={`${new Date(x.day).toLocaleDateString()}: ${x.cashouts}`} className="flex-1 rounded-t" style={{ height: `${(x.cashouts / max) * 100}%`, background: 'var(--viz-1)' }} />;
              })}
            </div>
          )}
          <div className="text-sm font-semibold">Cases</div>
          {d.cases.length === 0 ? <p className="muted">No cases.</p> : (
            <ul className="text-xs">{d.cases.map((c) => <li key={c.case_id}>#{c.case_id} · {c.reason?.replaceAll('_', ' ')} · {c.status}{c.assigned_to ? ` · ${c.assigned_to}` : ''} · {timeAgo(c.at)}</li>)}</ul>
          )}
          <div className="text-sm font-semibold">Recent confirmation checks</div>
          <ul className="flex flex-col gap-1 text-xs">
            {d.checks.map((c) => (
              <li key={c.check_id} className="flex items-center gap-2"><Badge tone={checkTone[c.status]}>{checkText[c.status]}</Badge>{bdt(c.amount)} · {c.user_id}<span className="muted ml-auto">{timeAgo(c.at)}</span></li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------- staff
export function StaffPage() {
  const [data, error, reload] = usePoll(() => api.getStaff(), 10000);
  const [form, setForm] = useState({ staff_id: '', display_name: '', role: 'supervisor', pin: '' });
  const [flash, setFlash] = useState('');
  const [busy, setBusy] = useState(false);
  const session = api.getSession();
  const create = async (e) => {
    e.preventDefault(); setBusy(true); setFlash('');
    try { await api.createStaff(form); setFlash(`Created ${form.staff_id}. They can sign in with their staff ID and PIN.`); setForm({ staff_id: '', display_name: '', role: 'supervisor', pin: '' }); reload(); }
    catch (err) { setFlash(err.message); }
    finally { setBusy(false); }
  };
  const toggle = async (s) => {
    setFlash('');
    try { await api.updateStaff(s.staff_id, { active: !s.active }); reload(); }
    catch (err) { setFlash(err.message); }
  };
  const resetPin = async (s) => {
    const pin = window.prompt(`New PIN for ${s.display_name} (4-8 digits)`);
    if (!pin) return;
    try { await api.updateStaff(s.staff_id, { pin }); setFlash(`PIN reset for ${s.staff_id}.`); }
    catch (err) { setFlash(err.message); }
  };
  const items = data?.items || [];
  const sups = items.filter((s) => s.role === 'supervisor');
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Supervisors and admins" lead="Staff accounts, their live workload and what they finished in the last 24 hours. Deactivating someone hands their open calls and cases back to the shared queue." />
      <Alert kind="info">{flash}</Alert>
      <Alert>{error}</Alert>
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi icon="users" label="Active supervisors" value={sups.filter((s) => s.active).length} note={`${sups.length} total`} />
        <Kpi icon="phone" label="Open calls held" value={num(sups.reduce((a, s) => a + s.open_calls, 0))} note={`${num(sups.reduce((a, s) => a + s.calls_resolved_24h, 0))} resolved in 24h`} />
        <Kpi icon="cases" label="Open cases held" value={num(sups.reduce((a, s) => a + s.open_cases, 0))} note={`${num(sups.reduce((a, s) => a + s.reports_24h, 0))} audit reports in 24h`} />
      </div>
      <Panel bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead><tr><th>Name</th><th>Staff ID</th><th>Role</th><th>Open calls</th><th>Open cases</th><th>Calls done 24h</th><th>Reports 24h</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.staff_id} className={s.active ? '' : 'opacity-50'}>
                  <td className="font-medium">{s.display_name}</td>
                  <td className="font-mono text-xs">{s.staff_id}</td>
                  <td><Badge tone={s.role === 'super_admin' ? 'badge-warning' : 'badge-ghost'}>{s.role === 'super_admin' ? 'Super admin' : 'Supervisor'}</Badge></td>
                  <td>{s.open_calls}</td><td>{s.open_cases}</td><td>{s.calls_resolved_24h}</td><td>{s.reports_24h}</td>
                  <td className="muted text-xs">{s.last_login_at ? timeAgo(s.last_login_at) : 'never'}</td>
                  <td className="flex gap-1">
                    <button className="btn btn-xs btn-ghost border-base-300" onClick={() => resetPin(s)}>Reset PIN</button>
                    {s.staff_id !== session?.subject && (
                      <button className={`btn btn-xs ${s.active ? 'btn-ghost border-base-300' : 'btn-success'}`} onClick={() => toggle(s)}>{s.active ? 'Deactivate' : 'Activate'}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Add a staff member">
        <form onSubmit={create} className="grid gap-3 sm:grid-cols-5">
          <input required className="input input-bordered input-sm font-mono focus-ring" placeholder="staff id (sup_rahim)" value={form.staff_id} onChange={(e) => setForm({ ...form, staff_id: e.target.value.toLowerCase() })} />
          <input required className="input input-bordered input-sm focus-ring" placeholder="Full name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          <select className="select select-bordered select-sm focus-ring" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="supervisor">Supervisor</option><option value="super_admin">Super admin</option>
          </select>
          <input required className="input input-bordered input-sm font-mono focus-ring" placeholder="PIN (4-8 digits)" inputMode="numeric" value={form.pin} onChange={(e) => setForm({ ...form, pin: e.target.value.replace(/\D/g, '').slice(0, 8) })} />
          <button className="btn btn-primary btn-sm focus-ring" disabled={busy}>Create</button>
        </form>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------- ledger
export function LedgerPage() {
  const [filters, setFilters] = useState({ txn_type: '', check_status: '', user_id: '', agent_id: '' });
  const [applied, setApplied] = useState(filters);
  const [live, setLive] = useState(true);
  const list = useKeyset(async (before) => {
    const r = await api.getAdminTransactions({ ...applied, before, limit: 50 });
    return { items: r.items, cursor: r.next_before, total: r.total };
  }, [applied]);
  useEffect(() => {
    if (!live) return undefined;
    const t = setInterval(() => { if (document.visibilityState !== 'hidden') list.reload(); }, 5000);
    return () => clearInterval(t);
  }, [live, applied]);
  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value });
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="All transactions" lead={`Every transaction on the platform, newest first, with its customer confirmation result. ${totalText(list.total)}.`}>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="toggle toggle-sm toggle-success" checked={live} onChange={(e) => setLive(e.target.checked)} /> Live</label>
        {live && <LiveDot />}
      </PageHead>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setApplied(filters); }}>
        <select className="select select-bordered select-sm focus-ring" value={filters.txn_type} onChange={set('txn_type')} aria-label="Type">
          <option value="">All types</option><option value="cash_out">Cash-out</option><option value="credit">Credit</option><option value="send">Send</option><option value="bill_pay">Bill pay</option>
        </select>
        <select className="select select-bordered select-sm focus-ring" value={filters.check_status} onChange={set('check_status')} aria-label="Check">
          <option value="">Any check result</option>
          {Object.entries(checkText).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input className="input input-bordered input-sm w-40 font-mono focus-ring" placeholder="Customer ID" value={filters.user_id} onChange={set('user_id')} />
        <input className="input input-bordered input-sm w-36 font-mono focus-ring" placeholder="Agent ID" value={filters.agent_id} onChange={set('agent_id')} />
        <button className="btn btn-sm btn-primary">Apply</button>
      </form>
      <Alert>{list.error}</Alert>
      <Panel bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead><tr><th>#</th><th>When</th><th>Type</th><th>Customer</th><th>Agent</th><th>Amount</th><th>Fee</th><th>Check</th><th>Source</th></tr></thead>
            <tbody>
              {list.items.map((t) => (
                <tr key={t.txn_id}>
                  <td className="font-mono text-xs">{t.txn_id}</td>
                  <td className="muted whitespace-nowrap text-xs">{timeAgo(t.ts)}</td>
                  <td>{t.txn_type.replace('_', '-')}</td>
                  <td className="font-mono text-xs">{t.user_id}</td>
                  <td className="font-mono text-xs">{t.agent_id || '—'}</td>
                  <td className="tabular-nums">{bdt(t.amount)}</td>
                  <td className="tabular-nums text-xs">{t.fee ? bdt(t.fee) : ''}</td>
                  <td>{t.check_status && <Badge tone={checkTone[t.check_status]}>{checkText[t.check_status]}</Badge>}{t.case_id && <span className="ml-1 text-xs">#{t.case_id}</span>}</td>
                  <td className="muted text-xs">{t.source === 'simulator' ? 'live sim' : t.source || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!list.busy && list.items.length === 0 && <Empty title="No transactions match" />}
        <Pager hasMore={Boolean(list.cursor)} busy={list.busy} onMore={list.more} />
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------- audit log
export function AuditLogPage() {
  const [actor, setActor] = useState('');
  const list = useKeyset(async (before) => {
    const r = await api.getAuditLog({ before, actor, limit: 50 });
    return { items: r.items, cursor: r.next_before };
  }, [actor]);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Audit log" lead="Append-only record of every action by people and by the system.">
        <SearchBox value={actor} onChange={setActor} placeholder="actor (e.g. sup_nadia)" />
        <button className="btn btn-sm btn-ghost border-base-300" onClick={list.reload}><Icon name="refresh" className="size-4" /></button>
      </PageHead>
      <Alert>{list.error}</Alert>
      <Panel bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead><tr><th>#</th><th>When</th><th>Who</th><th>Action</th><th>On</th><th>Detail</th></tr></thead>
            <tbody>
              {list.items.map((e) => (
                <tr key={e.log_id}>
                  <td className="font-mono text-xs">{e.log_id}</td>
                  <td className="muted whitespace-nowrap text-xs">{when(e.at)}</td>
                  <td className="font-mono text-xs">{e.actor}</td>
                  <td>{eventLabel(e.action)}</td>
                  <td className="text-xs">{e.entity} {e.entity_id}</td>
                  <td className="max-w-xs truncate font-mono text-[11px]" title={JSON.stringify(e.detail)}>{e.detail ? JSON.stringify(e.detail) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager hasMore={Boolean(list.cursor)} busy={list.busy} onMore={list.more} />
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------- supervisor desk
export function SupervisorDesk({ session, onOpen }) {
  const [d, error] = usePoll(() => api.getDeskSummary(), 5000);
  const [calls] = usePoll(() => api.getCallQueue({ scope: 'mine', limit: 5 }), 8000);
  const [cases] = usePoll(() => api.getCaseQueue({ scope: 'mine', limit: 5 }), 8000);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title={`Hello, ${d?.display_name || session.display_name || session.subject}`} lead="Your work today. Pending lists are shared by all supervisors; take items one by one.">
        <LiveDot />
      </PageHead>
      <Alert>{error}</Alert>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon="phone" label="Calls waiting for anyone" value={num(d?.calls.pending)} tone="bg-warning/20 text-warning-content" onClick={() => onOpen('callcenter')} />
        <Kpi icon="flow" label="My calls" value={num(d?.calls.mine)} note={`${num(d?.calls.resolved_24h)} done in 24h`} tone="bg-primary/15 text-primary" onClick={() => onOpen('callcenter')} />
        <Kpi icon="cases" label="Cases waiting for anyone" value={num(d?.cases.pending)} tone="bg-error/15 text-error" onClick={() => onOpen('casework')} />
        <Kpi icon="shield" label="My cases" value={num(d?.cases.mine)} note={`${num(d?.cases.closed_24h)} closed · ${num(d?.reports_24h)} reports in 24h`} tone="bg-secondary/15 text-secondary" onClick={() => onOpen('casework')} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="My calls" action={<button className="link text-xs" onClick={() => onOpen('callcenter')}>Open call queue</button>}>
          {(calls?.items || []).length === 0 ? <p className="muted">No calls assigned to you. Take one from the pending list.</p> : (
            <ul className="flex flex-col gap-1.5 text-sm">{calls.items.map((t) => <li key={t.task_id} className="flex justify-between"><span>#{t.task_id} · {t.user_id}</span><span className="muted">{bdt(t.amount)}</span></li>)}</ul>
          )}
        </Panel>
        <Panel title="My cases" action={<button className="link text-xs" onClick={() => onOpen('casework')}>Open cases</button>}>
          {(cases?.cases || []).length === 0 ? <p className="muted">No cases assigned to you.</p> : (
            <ul className="flex flex-col gap-1.5 text-sm">{cases.cases.map((c) => <li key={c.case_id} className="flex justify-between gap-2"><span className="truncate">#{c.case_id} · {c.reason_text}</span><Badge tone={c.priority === 'urgent' ? 'badge-error' : 'badge-ghost'}>{c.priority}</Badge></li>)}</ul>
          )}
        </Panel>
        <Panel title="Critical notes on open cases">
          {(d?.critical_notes || []).length === 0 ? <p className="muted">None.</p> : (
            <ul className="flex flex-col gap-2 text-sm">{d.critical_notes.map((n, i) => <li key={i} className="rounded border border-error/40 bg-error/5 p-2"><div className="text-xs font-semibold">Case #{n.case_id} · {n.author} · {timeAgo(n.at)}</div>{n.body}</li>)}</ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
