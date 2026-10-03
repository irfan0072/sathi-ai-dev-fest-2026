import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { HourlyBars, StateBar } from './Charts';

const bdt = (v) => `৳${Math.round(v || 0).toLocaleString('en-US')}`;
const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`);
const actionLabel = (a) => a.replaceAll('_', ' ');
const timeAgo = (iso) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
};

// ASSUMPTION unit costs for one verification (≈45 s call). Quotes pending for local IVR.
const channelCosts = [
  { id: 'twilio', label: 'Twilio voice (live today)', cost: '≈ ৳5.5 / call', note: '$0.06/min to BD mobile' },
  { id: 'bd_http_ivr', label: 'Bangladesh IVR gateway', cost: '≈ ৳0.7–1 / call', note: 'local voice tier; DTMF quote pending' },
  { id: 'alpha', label: 'Alpha SMS receipt', cost: '≈ ৳0.25 / SMS', note: 'sms.net.bd API' },
];

function Kpi({ icon, label, value, note, tone = '' }) {
  return (
    <div className="panel">
      <div className="panel-body flex-row items-center gap-3 p-4">
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${tone || 'bg-base-200'}`}><Icon name={icon} /></span>
        <div className="min-w-0">
          <div className="muted truncate">{label}</div>
          <div className="text-xl font-bold leading-tight">{value}</div>
          {note && <div className="muted truncate">{note}</div>}
        </div>
      </div>
    </div>
  );
}

export function WatchButton({ agentId, watchlisted, caseId, onChange }) {
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      if (watchlisted) await api.removeFromWatchlist(agentId);
      else await api.addToWatchlist({ agentId, caseId, reason: caseId ? `Opened from case #${caseId}` : 'Analyst review from command center' });
      onChange?.();
    } finally { setBusy(false); }
  };
  return (
    <button className={`btn btn-xs ${watchlisted ? 'btn-warning' : 'btn-ghost border-base-300'}`} disabled={busy} onClick={toggle}
      title={watchlisted ? 'Remove enhanced verification' : 'Require a verification call for this agent'}>
      {watchlisted ? 'Watchlisted' : 'Watch'}
    </button>
  );
}

export default function CommandCenter({ onOpenCases }) {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try { setData(await api.getOpsOverview()); setError(''); } catch (err) { setError(err.message); }
  }, []);
  useEffect(() => {
    load();
    api.getVoiceConfig().then(setConfig).catch(() => {});
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  const bands = data?.risk_bands || {};
  const calls = data?.calls || {};
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="page-title">Fraud Command Center</h2>
          <p className="page-lead">Live runtime view of the last 24 hours. Refreshes every 10 seconds. Nothing here moves money; analysts decide.</p>
        </div>
        {data && <span className="badge badge-ghost gap-1.5"><span className="inline-block size-2 animate-pulse rounded-full bg-success" />Live · {new Date(data.generated_at).toLocaleTimeString()}</span>}
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {!data && !error && <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Loading live operations…</p>}

      {data && <>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi icon="flow" label="Mandates (24h)" value={data.totals.mandates} note={`${pct(data.totals.confirmation_rate)} confirmed by customer`} tone="bg-primary/15 text-primary" />
          <Kpi icon="receipt" label="Paid out (24h)" value={bdt(data.totals.redeemed_bdt)} note={`${bdt(data.totals.held_bdt)} held before payout`} tone="bg-secondary/15 text-secondary" />
          <Kpi icon="warning" label="Open cases" value={data.cases.open} note={`${data.cases.urgent} urgent · ${data.cases.sla_breached} past target`} tone={data.cases.urgent ? 'bg-error/15 text-error' : 'bg-base-200'} />
          <Kpi icon="phone" label="Verification calls (24h)" value={Object.values(calls).reduce((a, b) => a + b, 0)} note={`${calls.verified || 0} confirmed · ${(calls.duress || 0) + (calls.rejected || 0) + (calls.mismatch || 0)} not confirmed`} tone="bg-accent/20" />
        </div>

        {data.cases.urgent > 0 && (
          <div role="alert" className="alert alert-error alert-soft">
            <Icon name="warning" />
            <span><strong>{data.cases.urgent} urgent case{data.cases.urgent > 1 ? 's' : ''}.</strong> A silent duress signal needs contact with the customer on the registered number, away from the agent, within 15 minutes.</span>
            <button className="btn btn-error btn-sm" onClick={onOpenCases}>Open queue</button>
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-3">
          <div className="panel lg:col-span-2"><div className="panel-body">
            <h3 className="font-semibold">Mandates per hour</h3>
            <HourlyBars hours={data.hourly} />
          </div></div>
          <div className="panel"><div className="panel-body gap-4">
            <div>
              <h3 className="mb-2 font-semibold">Risk at request</h3>
              <StateBar parts={[
                { label: 'Low', value: bands.low || 0, color: 'var(--status-good)' },
                { label: 'Medium', value: bands.medium || 0, color: 'var(--status-warning)' },
                { label: 'High', value: bands.high || 0, color: 'var(--status-critical)' },
              ]} />
            </div>
            <div>
              <h3 className="mb-2 font-semibold">Call outcomes</h3>
              <StateBar parts={[
                { label: 'Confirmed', value: calls.verified || 0, color: 'var(--status-good)' },
                { label: 'No answer', value: (calls.no_answer || 0) + (calls.failed || 0), color: 'var(--status-warning)' },
                { label: 'Not confirmed', value: (calls.mismatch || 0) + (calls.rejected || 0), color: 'var(--status-serious)' },
                { label: 'Duress', value: calls.duress || 0, color: 'var(--status-critical)' },
              ]} />
            </div>
          </div></div>
        </div>

        <div className="grid gap-5 lg:grid-cols-5">
          <div className="panel lg:col-span-3"><div className="panel-body">
            <h3 className="font-semibold">Agents with most cases (7 days)</h3>
            {data.agents.length === 0 ? <p className="muted">No agent cases this week.</p> : (
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead><tr><th>Agent</th><th className="text-right">Cases</th><th className="text-right">Duress</th><th className="text-right">Enhanced verification</th></tr></thead>
                  <tbody>{data.agents.map((a) => (
                    <tr key={a.agent_id}>
                      <td className="font-mono text-xs">{a.agent_id}</td>
                      <td className="text-right">{a.cases_7d}</td>
                      <td className="text-right">{a.duress_7d ? <span className="badge badge-error badge-sm">{a.duress_7d}</span> : 0}</td>
                      <td className="text-right"><WatchButton agentId={a.agent_id} watchlisted={a.watchlisted} onChange={load} /></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <p className="muted">Watchlisting never blocks an agent. It makes every mandate from that agent need a verification call.</p>
          </div></div>
          <div className="panel lg:col-span-2"><div className="panel-body">
            <h3 className="font-semibold">Live event feed</h3>
            <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
              {data.events.map((e, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className={`mt-1.5 inline-block size-2 shrink-0 rounded-full ${/duress|denied|mismatch|lock|gap/.test(e.action) ? 'bg-error' : /verified|redeemed/.test(e.action) ? 'bg-success' : 'bg-base-300'}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{actionLabel(e.action)}</span>
                    <span className="muted block truncate">{e.actor} · {timeAgo(e.at)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div></div>
        </div>

        <div className="panel"><div className="panel-body">
          <h3 className="font-semibold">Channels and unit cost</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            {channelCosts.map((c) => {
              const active = c.id === config?.provider || c.id === config?.sms_provider;
              return (
                <div key={c.id} className={`rounded-box border p-3 ${active ? 'border-primary bg-primary/5' : 'border-base-300'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{c.label}</span>
                    {active && <span className="badge badge-primary badge-xs">active</span>}
                  </div>
                  <div className="text-lg font-bold">{c.cost}</div>
                  <div className="muted">{c.note}</div>
                </div>
              );
            })}
          </div>
          <p className="muted">Current: voice <strong>{config?.provider || '…'}</strong>, SMS <strong>{config?.sms_provider || '…'}</strong>. Costs are ASSUMPTIONS for planning, not quotes.</p>
        </div></div>
      </>}
    </div>
  );
}
