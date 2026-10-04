import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { HourlyBars, StateBar } from './Charts';
import { eventLabel } from '../copy';
import { phone } from '../ids';

const bdt = (v) => `৳${Math.round(v || 0).toLocaleString('en-US')}`;
const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`);
const actionLabel = eventLabel;
const timeAgo = (iso) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
};

// Unit costs come from Settings → Cost assumptions (planning ASSUMPTIONS, not quotes).
const channelCosts = (costs) => [
  { id: 'twilio', label: 'Phone call (Twilio)', cost: costs ? `≈ ৳${costs.twilio_bdt_per_call} / call` : '…', note: 'works today' },
  { id: 'bd_http_ivr', label: 'Phone call (Bangladesh provider)', cost: costs ? `≈ ৳${costs.bd_ivr_bdt_per_call} / call` : '…', note: 'cheaper; waiting for price quote' },
  { id: 'alpha', label: 'SMS receipt (Alpha SMS)', cost: costs ? `≈ ৳${costs.sms_bdt} / SMS` : '…', note: 'sent after every cash-out' },
];

function Kpi({ icon, label, value, note, tone = '' }) {
  return (
    <div className="panel shadow-sm transition-colors hover:border-primary/40">
      <div className="panel-body flex-row items-center gap-3 p-4">
        <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${tone || 'bg-base-200'}`}>
          <Icon name={icon} />
        </span>
        <div className="min-w-0 flex-1">
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
      else await api.addToWatchlist({ agentId, caseId, reason: caseId ? `From case #${caseId}` : 'Added from the dashboard' });
      onChange?.();
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      className={`btn btn-xs focus-ring ${watchlisted ? 'btn-warning' : 'btn-ghost border-base-300'}`}
      disabled={busy}
      onClick={toggle}
      title={watchlisted ? 'Stop extra checks for this agent' : 'Require a verification call for this agent'}
    >
      {watchlisted ? 'Watchlisted' : 'Add extra checks'}
    </button>
  );
}

export default function CommandCenter({ onOpenCases, onOpenTransactions }) {
  const [data, setData] = useState(null);
  const [config, setConfig] = useState(null);
  const [costs, setCosts] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      setData(await api.getOpsOverview());
      setError('');
    } catch (err) {
      setError(err.message);
    }
  }, []);
  useEffect(() => {
    load();
    api.getVoiceConfig().then(setConfig).catch(() => {});
    api.getSettings().then((s) => setCosts(s.unit_costs)).catch(() => {});
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  const calls = data?.calls || {};
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="page-title">Today at a glance</h2>
          <p className="page-lead mt-1">
            What happened in the last 24 hours. Updates by itself every 10 seconds.
          </p>
        </div>
        {data && (
          <span className="badge badge-ghost gap-1.5 border-base-300 py-3.5 font-medium">
            <span className="inline-block size-2 animate-pulse rounded-full bg-success" />
            Live · {new Date(data.generated_at).toLocaleTimeString()}
          </span>
        )}
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      {!data && !error && (
        <p className="flex items-center gap-2 text-sm text-base-content/70">
          <span className="loading loading-dots loading-sm" />
          Loading today’s activity…
        </p>
      )}

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              icon="flow"
              label="Cash-outs today"
              value={data.check_totals?.cashouts ?? 0}
              note={`${bdt(data.check_totals?.cashout_bdt)} given out`}
              tone="bg-primary/15 text-primary"
            />
            <Kpi
              icon="check"
              label="Verified by customer"
              value={data.check_totals?.verified ?? 0}
              note={`${pct(data.check_totals?.verified_rate)} of answered calls`}
              tone="bg-secondary/15 text-secondary"
            />
            <Kpi
              icon="warning"
              label="Cases to review"
              value={data.cases.open}
              note={`${data.cases.urgent} urgent · ${data.cases.sla_breached} late`}
              tone={data.cases.urgent ? 'bg-error/15 text-error' : 'bg-base-200'}
            />
            <Kpi
              icon="shield"
              label="Marked suspicious"
              value={data.check_totals?.suspicious ?? 0}
              note={`${data.check_totals?.waiting ?? 0} waiting · ${data.check_totals?.no_answer ?? 0} no answer`}
              tone="bg-accent/20 text-accent-content"
            />
          </div>

          {data.cases.urgent > 0 && (
            <div role="alert" className="alert alert-error alert-soft">
              <Icon name="warning" />
              <span>
                <strong>{data.cases.urgent} customer{data.cases.urgent > 1 ? 's' : ''} asked for help secretly.</strong>{' '}
                Call the customer on their registered number, away from the agent, as soon as possible.
              </span>
              <button className="btn btn-error btn-sm focus-ring" onClick={onOpenCases}>
                See cases
              </button>
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-3">
            <div className="panel shadow-sm lg:col-span-2">
              <div className="panel-body">
                <h3 className="font-semibold">Cash-outs per hour</h3>
                <HourlyBars hours={data.hourly} />
              </div>
            </div>
            <div className="panel shadow-sm">
              <div className="panel-body gap-4">
                <div>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h3 className="font-semibold">Customer confirmations</h3>
                    {onOpenTransactions && <button className="btn btn-ghost btn-xs" onClick={onOpenTransactions}>See all</button>}
                  </div>
                  <StateBar
                    parts={[
                      { label: 'Verified', value: data.check_totals?.verified || 0, color: 'var(--status-good)' },
                      { label: 'Waiting', value: data.check_totals?.waiting || 0, color: 'var(--status-warning)' },
                      { label: 'No answer', value: data.check_totals?.no_answer || 0, color: 'var(--status-serious)' },
                      { label: 'Suspicious', value: data.check_totals?.suspicious || 0, color: 'var(--status-critical)' },
                    ]}
                  />
                </div>
                <div>
                  <h3 className="mb-2 font-semibold">What happened on the calls?</h3>
                  <StateBar
                    parts={[
                      { label: 'Confirmed', value: calls.verified || 0, color: 'var(--status-good)' },
                      {
                        label: 'No answer',
                        value: (calls.no_answer || 0) + (calls.failed || 0),
                        color: 'var(--status-warning)',
                      },
                      {
                        label: 'Not confirmed',
                        value: (calls.mismatch || 0) + (calls.rejected || 0),
                        color: 'var(--status-serious)',
                      },
                      { label: 'Secret help', value: calls.duress || 0, color: 'var(--status-critical)' },
                    ]}
                  />
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <div className="panel shadow-sm lg:col-span-3">
              <div className="panel-body">
                <h3 className="font-semibold">Agents with the most problems (last 7 days)</h3>
                {data.agents.length === 0 ? (
                  <p className="muted">No problems with agents this week.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="table table-sm">
                      <thead>
                        <tr>
                          <th>Agent</th>
                          <th className="text-right">Cases</th>
                          <th className="text-right">Secret help</th>
                          <th className="text-right">Extra checks</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.agents.map((a) => (
                          <tr key={a.agent_id}>
                            <td className="font-mono text-xs">{phone(a.agent_id)}</td>
                            <td className="text-right">{a.cases_7d}</td>
                            <td className="text-right">
                              {a.duress_7d ? (
                                <span className="badge badge-error badge-sm">{a.duress_7d}</span>
                              ) : (
                                0
                              )}
                            </td>
                            <td className="text-right">
                              <WatchButton
                                agentId={a.agent_id}
                                watchlisted={a.watchlisted}
                                onChange={load}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="muted">
                  Extra checks never block an agent. Their customers just have to confirm every cash-out by phone.
                </p>
              </div>
            </div>
            <div className="panel shadow-sm lg:col-span-2">
              <div className="panel-body">
                <h3 className="font-semibold">Recent activity</h3>
                <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto pr-1">
                  {data.events.map((e, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm">
                      <span
                        className={`mt-1.5 inline-block size-2 shrink-0 rounded-full ${
                          /duress|denied|mismatch|lock|gap/.test(e.action)
                            ? 'bg-error'
                            : /verified|redeemed/.test(e.action)
                              ? 'bg-success'
                              : 'bg-base-300'
                        }`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">{actionLabel(e.action)}</span>
                        <span className="muted block truncate">
                          {e.actor} · {timeAgo(e.at)}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>

          <div className="panel shadow-sm">
            <div className="panel-body">
              <h3 className="font-semibold">Costs per message</h3>
              <div className="grid gap-3 sm:grid-cols-3">
                {channelCosts(costs).map((c) => {
                  const active = c.id === config?.provider || c.id === config?.sms_provider;
                  return (
                    <div
                      key={c.id}
                      className={`rounded-box border p-3 transition-colors ${
                        active ? 'border-primary bg-primary/5' : 'border-base-300'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold">{c.label}</span>
                        {active && (
                          <span className="badge badge-primary badge-xs">
                            active
                          </span>
                        )}
                      </div>
                      <div className="text-lg font-bold">{c.cost}</div>
                      <div className="muted">{c.note}</div>
                    </div>
                  );
                })}
              </div>
              <p className="muted">
                Now using: calls <strong>{config?.provider === 'simulated' ? 'built-in phone simulator' : config?.provider || '…'}</strong>, SMS{' '}
                <strong>{config?.sms_provider === 'simulated' ? 'built-in SMS inbox' : config?.sms_provider || '…'}</strong>. Prices are estimates. Change them in Settings.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}