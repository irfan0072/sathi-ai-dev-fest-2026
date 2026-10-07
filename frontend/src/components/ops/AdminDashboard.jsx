import { phone } from '../../ids';
import { useState } from 'react';
import { api } from '../../api';
import { StateBar } from '../Charts';
import { eventLabel } from '../../copy';
import {
  Alert, Bars, Kpi, LiveDot, PageHead, Panel, bdt, compact, num, pct, timeAgo, useDeployment, usePoll,
} from './kit';

function Simulator({ sim, onChange }) {
  const { readOnly } = useDeployment();
  const [rate, setRate] = useState(sim?.rate_per_minute ?? 12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (enabled) => {
    setBusy(true); setError('');
    try { onChange(await api.setSimulator({ enabled, rate_per_minute: Number(rate) || 12 })); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  if (readOnly) {
    return (
      <div className="rounded-box border border-base-300 bg-base-100 px-3 py-2 text-sm" data-testid="simulator-disabled">
        <span className="font-medium">Live traffic simulator</span>{' '}
        <span className="muted">Disabled in the public demo (it changes platform settings). Record a cash-out as an agent to see the workflow.</span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-box border border-base-300 bg-base-100 px-3 py-2">
      <span className="text-sm font-medium">Live traffic simulator</span>
      <input
        type="number" min="1" max="600" value={rate}
        onChange={(e) => setRate(e.target.value)}
        className="input input-bordered input-sm w-20 focus-ring" aria-label="Cash-outs per minute"
      />
      <span className="muted">/min</span>
      {sim?.enabled ? (
        <button className="btn btn-sm btn-warning focus-ring" disabled={busy} onClick={() => save(false)}>Stop</button>
      ) : (
        <button className="btn btn-sm btn-primary focus-ring" disabled={busy} onClick={() => save(true)}>Start</button>
      )}
      {sim?.enabled && <LiveDot label="Generating traffic" />}
      {error && <span className="text-xs text-error">{error}</span>}
    </div>
  );
}

const minuteLabel = (p) => new Date(p.minute).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const hourLabel = (p) => `${new Date(p.hour).getHours()}:00`;

function fillHours(points) {
  const now = new Date(); now.setMinutes(0, 0, 0);
  return Array.from({ length: 24 }, (_, i) => {
    const d = new Date(now.getTime() - (23 - i) * 3600000);
    const hit = points.find((p) => new Date(p.hour).getTime() === d.getTime());
    return { hour: d.toISOString(), cashouts: hit?.cashouts || 0, suspicious: hit?.suspicious || 0 };
  });
}

function fillMinutes(points) {
  const now = new Date(); now.setSeconds(0, 0);
  return Array.from({ length: 30 }, (_, i) => {
    const d = new Date(now.getTime() - (29 - i) * 60000);
    const hit = points.find((p) => new Date(p.minute).getTime() === d.getTime());
    return { minute: d.toISOString(), cashouts: hit?.cashouts || 0, suspicious: hit?.suspicious || 0 };
  });
}

export default function AdminDashboard({ onOpen }) {
  const [data, error, reload, setData] = usePoll(() => api.getAdminOverview(), 5000);
  const d = data;
  const p = d?.platform || {};
  const money = d?.money_24h || {};
  const checks = d?.checks_24h || {};
  const by = checks.by_status || {};
  const calls = d?.calls || {};
  const cases = d?.cases || {};
  const cnt = (k) => by[k]?.count || 0;

  if (!d && !error) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        <PageHead title="Control center" lead="Loading live numbers from the database…" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton h-24 rounded-box" />)}
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="skeleton h-56 rounded-box lg:col-span-2" /><div className="skeleton h-56 rounded-box" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="Control center"
        lead="Live view of the whole platform: customers, money moving, confirmation calls, the supervisor queue and open cases. Refreshes every 5 seconds from the database."
      >
        {d && <LiveDot label={`Updated ${timeAgo(d.generated_at)}`} />}
        {d && <Simulator sim={d.simulator} onChange={(sim) => { setData({ ...d, simulator: sim }); reload(); }} />}
      </PageHead>
      <Alert>{error}</Alert>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon="users" label="Customers" value={compact(p.customers?.value)}
          note={p.customers ? `${p.customers.exact ? '' : '≈ '}${num(p.customers.value)} accounts` : ''}
          tone="bg-primary/15 text-primary" onClick={() => onOpen('users')} />
        <Kpi icon="store" label="Agents" value={num(p.agents?.value)} note={`${num(p.supervisors)} supervisors on staff · ${num(p.staff_online)} online`}
          tone="bg-secondary/15 text-secondary" onClick={() => onOpen('agents-dir')} />
        <Kpi icon="receipt" label="Transactions (all time)" value={compact(p.transactions?.value)}
          note={`${num(money.transactions_last_hour)} in the last hour`} onClick={() => onOpen('ledger')} />
        <Kpi icon="flow" label="Cash-out volume, 24h" value={bdt(money.cashout_bdt)}
          note={`${num(money.cashouts)} cash-outs · fees ${bdt(money.fees_bdt)}`} tone="bg-accent/20 text-accent-content" />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon="check" label="Confirmed by customer" value={pct(checks.verified_rate)}
          note={`${num(cnt('verified'))} verified of ${num(checks.total)} checks today`} tone="bg-success/15 text-success" />
        <Kpi icon="warning" label="Suspicious, 24h" value={num(cnt('suspicious'))}
          note={`${bdt(checks.suspicious_bdt)} at risk`} tone="bg-error/15 text-error" onClick={() => onOpen('ledger')} />
        <Kpi icon="phone" label="Calls needing a person" value={num(calls.manual_waiting)}
          note={`${num(calls.manual_active)} being handled · ${num(calls.retrying)} retrying`} tone="bg-warning/20 text-warning-content" onClick={() => onOpen('callcenter')} />
        <Kpi icon="cases" label="Open cases" value={num(cases.open)}
          note={`${num(cases.urgent)} urgent · ${num(cases.unassigned)} unassigned · ${num(cases.sla_breached)} late`}
          tone={cases.urgent ? 'bg-error/15 text-error' : ''} onClick={() => onOpen('casework')} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Cash-outs per minute (last 30 min)" className="lg:col-span-2"
          action={<span className="muted">red = suspicious</span>}>
          <Bars points={fillMinutes(d?.per_minute || [])} value="cashouts" overlay="suspicious"
            label="Cash-outs per minute" xLabel={minuteLabel} height={150} />
        </Panel>
        <Panel title="Confirmation calls, 24h">
          <div className="text-3xl font-bold tabular-nums">{pct(calls.answer_rate)}</div>
          <div className="muted -mt-2">answered of {num(calls.total_24h)} calls</div>
          <StateBar parts={[
            { label: 'Confirmed', value: calls.calls_24h?.verified || 0, color: 'var(--color-success)' },
            { label: 'Wrong amount', value: calls.calls_24h?.mismatch || 0, color: 'var(--color-error)' },
            { label: 'Refused', value: calls.calls_24h?.rejected || 0, color: 'var(--color-warning)' },
            { label: 'Secret help', value: calls.calls_24h?.duress || 0, color: 'oklch(45% 0.2 25)' },
            { label: 'Not understood', value: calls.calls_24h?.unclear || 0, color: 'var(--color-secondary)' },
            { label: 'No answer', value: calls.calls_24h?.no_answer || 0, color: 'var(--color-base-300)' },
          ]} />
          <div className="muted">{num(calls.ignored)} customers marked unreachable after all retries.</div>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Check results today" className="lg:col-span-2">
          <StateBar parts={[
            { label: 'Verified', value: cnt('verified'), color: 'var(--color-success)' },
            { label: 'Suspicious', value: cnt('suspicious'), color: 'var(--color-error)' },
            { label: 'Calling', value: cnt('pending') + cnt('calling'), color: 'var(--color-info)' },
            { label: 'No answer yet', value: cnt('no_answer'), color: 'var(--color-warning)' },
            { label: 'Supervisor review', value: cnt('manual_review'), color: 'var(--color-secondary)' },
            { label: 'Unreachable', value: cnt('unreachable'), color: 'var(--color-base-300)' },
          ]} />
          <Bars points={fillHours(d?.hourly || [])} value="cashouts" overlay="suspicious" label="Checks per hour"
            xLabel={hourLabel} height={120} />
        </Panel>
        <Panel title="Case work, 24h">
          <ul className="flex flex-col gap-2 text-sm">
            <li className="flex justify-between"><span>Opened</span><strong>{num(Object.values(cases.opened_24h || {}).reduce((a, b) => a + b, 0))}</strong></li>
            <li className="flex justify-between"><span>Audit reports filed</span><strong>{num(cases.reports_24h)}</strong></li>
            <li className="flex justify-between"><span>Problems confirmed</span><strong className="text-error">{num(cases.confirmed_problems_24h)}</strong></li>
            <li className="flex justify-between"><span>Past response target</span><strong className={cases.sla_breached ? 'text-error' : ''}>{num(cases.sla_breached)}</strong></li>
          </ul>
          <button className="btn btn-sm btn-ghost border-base-300 focus-ring" onClick={() => onOpen('staff')}>See supervisor workload</button>
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Agents with suspicious cash-outs (7 days)">
          {(d?.risky_agents || []).length === 0 ? <p className="muted">None this week.</p> : (
            <ul className="flex flex-col divide-y divide-base-300">
              {d.risky_agents.map((a) => (
                <li key={a.agent_id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span className="font-mono">{phone(a.agent_id)}<span className="muted ml-2 font-sans capitalize">{a.region}</span></span>
                  <span className="flex items-center gap-2">
                    {a.watchlisted && <span className="badge badge-warning badge-xs">watchlist</span>}
                    <strong className="text-error">{a.suspicious_7d}</strong>
                    <span className="muted">/ {a.checks_7d}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="By division, 24h">
          {(d?.regions || []).length === 0 ? <p className="muted">No cash-outs yet today.</p> : (
            <div className="flex flex-col gap-1.5">
              {d.regions.map((r) => {
                const max = Math.max(...d.regions.map((x) => x.cashouts));
                return (
                  <div key={r.region} className="grid grid-cols-[90px_1fr_70px] items-center gap-2 text-xs">
                    <span className="capitalize">{r.region}</span>
                    <div className="h-2.5 rounded-r" style={{ width: `${(r.cashouts / max) * 100}%`, background: 'var(--viz-1)' }} />
                    <span className="text-right tabular-nums">{r.cashouts}{r.suspicious ? <span className="text-error"> · {r.suspicious}</span> : ''}</span>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
        <Panel title="Live activity" action={<button className="link text-xs" onClick={() => onOpen('auditlog')}>Full audit log</button>}>
          <ul className="flex max-h-72 flex-col gap-1.5 overflow-y-auto text-xs">
            {(d?.events || []).map((e, i) => (
              <li key={i} className="flex justify-between gap-2">
                <span className="truncate"><span className="font-medium">{eventLabel(e.action)}</span> <span className="muted">· {e.actor}</span></span>
                <span className="muted shrink-0">{timeAgo(e.at)}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
