import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorBars, ForecastChart } from './Charts';

const featureName = {
  target_dom: 'Day of the month (allowance days)', lag_same_dow: 'Same day last week',
  mean_28: 'Average of the last 4 weeks', max_28: 'Busiest day in 4 weeks', target_dow: 'Day of the week',
  std_28: 'How much it changes', mean_7: 'Average of last week', h: 'Days ahead',
  zero_share_28: 'Days with no cash-outs', trend_7_28: 'Recent trend', volume_band_code: 'Agent size',
};

const bdt = (v) => (v == null ? '—' : `৳${Math.round(v).toLocaleString('en-US')}`);

function Tile({ label, value, note }) {
  return (
    <div className="panel transition-colors hover:border-primary/40">
      <div className="panel-body gap-1 p-4">
        <span className="muted">{label}</span>
        <span className="text-2xl font-bold">{value}</span>
        {note && <span className="muted">{note}</span>}
      </div>
    </div>
  );
}

export function AgentForecast({ data }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="Keep this much cash ready" value={bdt(data.recommended_opening_float_bdt)} note={`on ${data.peak_date}`} />
        <Tile label="Busiest day coming" value={bdt(data.peak_p90_bdt)} note={data.peak_date} />
        <Tile label="Your busiest day last month" value={bdt(data.max_daily_35d_bdt)} note={data.exceeds_recent_max ? 'More customers than usual are coming. Keep extra cash.' : data.max_daily_35d_bdt == null ? 'No past data yet' : 'Normal week ahead'} />
      </div>
      <div className="panel shadow-sm">
        <div className="panel-body">
          <h3 className="font-semibold">Cash needed in the next 7 days · {data.agent_id}</h3>
          <ForecastChart days={data.days} />
          <p className="muted">
            {data.basis?.startsWith('own') ? 'Based on your past cash-outs.' : 'Based on agents like you, because you have no history yet.'}{' '}
            This only helps you plan; it never limits a customer&apos;s cash-out.
          </p>
        </div>
      </div>
    </div>
  );
}

function AnalystOverview({ data }) {
  const [selected, setSelected] = useState(data.agents[0]);
  const holdout = data.evaluation.time_holdout;
  const unseen = data.evaluation.unseen_agent_population;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="How accurate (lower is better)" value={holdout.lightgbm.wape.toFixed(2)} note={`simple average method: ${holdout.moving_average_7.wape.toFixed(2)}`} />
        <Tile label="Busy-day estimate was enough" value={`${(holdout.p90_coverage * 100).toFixed(1)}%`} note="of days (goal: 90%)" />
        <Tile label="Agents who need extra cash" value={`${data.agents_under_pressure} / ${data.total_agents}`} note="busier than any day last month" />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel shadow-sm lg:col-span-3">
          <div className="panel-body">
            <h3 className="font-semibold">Agents needing extra cash</h3>
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th className="text-right">Busiest day last month</th>
                    <th className="text-right">Busiest day coming</th>
                    <th className="text-right">Extra cash needed</th>
                    <th className="text-right">Keep ready</th>
                  </tr>
                </thead>
                <tbody>
                  {data.agents.map((a) => (
                    <tr
                      key={a.agent_id}
                      className={`cursor-pointer transition-colors hover:bg-base-200 ${
                        selected?.agent_id === a.agent_id ? 'bg-primary/10' : ''
                      }`}
                      onClick={() => setSelected(a)}
                    >
                      <td className="font-mono text-xs">{a.agent_id}</td>
                      <td className="text-right font-mono text-xs">{bdt(a.max_daily_35d_bdt)}</td>
                      <td className="text-right font-mono text-xs">{bdt(a.peak_p90_bdt)}</td>
                      <td className="text-right">
                        {a.exceeds_recent_max ? (
                          <span className="badge badge-sm badge-warning gap-1 whitespace-nowrap">
                            +{bdt(a.headroom_needed_bdt)}
                          </span>
                        ) : (
                          <span className="badge badge-sm badge-ghost">{bdt(a.headroom_needed_bdt)}</span>
                        )}
                      </td>
                      <td className="text-right font-mono text-xs">{bdt(a.recommended_opening_float_bdt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div className="panel shadow-sm lg:col-span-2">
          <div className="panel-body">
            <h3 className="font-semibold">{selected?.agent_id}</h3>
            {selected && <ForecastChart days={selected.days} />}
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="panel shadow-sm">
          <div className="panel-body">
            <h3 className="font-semibold">Our AI vs simple methods (lower is better)</h3>
            <ErrorBars
              rows={[
                { label: 'Sathi AI', value: holdout.lightgbm.wape },
                { label: '7-day average', value: holdout.moving_average_7.wape },
                { label: 'Same day last week', value: holdout.seasonal_naive.wape },
              ]}
            />
            <p className="muted">
              Tested on {holdout.rows.toLocaleString()} agent-days the AI had never seen.
              {unseen && ` On a completely new group of agents: ${unseen.lightgbm.wape.toFixed(2)}.`} Daily cash
              needs jump around a lot, so no method is perfect.
            </p>
          </div>
        </div>
        <div className="panel shadow-sm">
          <div className="panel-body">
            <h3 className="font-semibold">What the AI looks at most</h3>
            <ErrorBars
              rows={data.feature_importance.slice(0, 6).map((f) => ({ label: featureName[f.feature] || f.feature, value: f.gain_share }))}
              format={(v) => `${(v * 100).toFixed(0)}%`}
              highlightLowest={false}
            />
            <ul className="muted list-inside list-disc">
              {data.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LiquidityPage({ session }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const isAgent = session?.role === 'agent';
  useEffect(() => {
    let live = true;
    const load = isAgent ? api.getAgentLiquidity(session.subject) : api.getLiquidityOverview();
    load.then((v) => { if (live) setData(v); }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [isAgent, session?.subject]);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Cash planning</h2>
        <p className="page-lead mt-1">
          How much cash each agent will need in the next 7 days, so no customer is turned away for lack of cash.
        </p>
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Could not load: {error}
        </div>
      )}
      {!data && !error && (
        <p className="flex items-center gap-2 text-sm text-base-content/70">
          <span className="loading loading-dots loading-sm" />
          Loading…
        </p>
      )}
      {data && (isAgent ? <AgentForecast data={data} /> : <AnalystOverview data={data} />)}
    </div>
  );
}
