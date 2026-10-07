import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorBars, ForecastChart } from './Charts';
import { phone } from '../ids';
import PageGuide from './PageGuide';

const featureName = {
  target_dom: 'Day of the month (allowance days)', lag_same_dow: 'Same day last week',
  mean_28: 'Average of the last 4 weeks', max_28: 'Busiest day in 4 weeks', target_dow: 'Day of the week',
  std_28: 'How much it changes', mean_7: 'Average of last week', h: 'Days ahead',
  zero_share_28: 'Days with no cash-outs', trend_7_28: 'Recent trend', volume_band_code: 'Agent size',
};

const dayName = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const sizeName = { low: 'Small agents', medium: 'Medium agents', high: 'Large agents' };

const terms = [
  { term: 'Likely amount', meaning: 'The cash-out total the AI expects on a normal day.' },
  { term: 'Busy-day amount (P90)', meaning: 'On 9 of 10 days, cash-outs stay below this. Keeping this much covers almost every day.' },
  { term: 'Keep ready', meaning: 'Busy-day amount for the peak day, rounded up to the next ৳1,000.' },
  { term: 'Extra cash needed', meaning: 'How much more than their busiest day last month the agent may need.' },
  { term: 'Error (WAPE)', meaning: 'Average miss as a share of real cash-outs. 0.79 means the forecast is off by 79% of the day’s total on average. Lower is better.' },
  { term: 'Coverage', meaning: 'How often the busy-day amount was enough in the test. The goal is 90%.' },
];

export function LiquidityGuide({ agent = false }) {
  return agent ? (
    <PageGuide
      what="Shows how much cash you should keep in your shop each day for the next week, so you never have to turn a customer away."
      steps={[
        'Sathi reads your own cash-outs from the last 90 days.',
        'It learns your weekly pattern and the allowance and salary days when more people come.',
        'It predicts a normal day and a busy day for each of the next 7 days.',
      ]}
      actions={[
        'Keep at least the “Keep this much cash ready” amount at the start of the busiest day.',
        'If it says more customers than usual are coming, arrange extra cash early.',
        'This is only advice. It never limits what a customer can withdraw.',
      ]}
      terms={terms.slice(0, 3)}
    />
  ) : (
    <PageGuide
      what="Agents run out of cash on busy days (allowance and salary days), and customers are turned away. This page predicts each agent’s cash need for the next 7 days, so the area team can send cash before it runs out."
      steps={[
        'Every 15 minutes Sathi reads the live cash-out ledger (last 90 days per agent).',
        'A LightGBM model learns weekly patterns, month-day peaks and each agent’s recent trend.',
        'For each of the next 7 days it predicts a likely amount and a busy-day amount (P90).',
        'Agents whose busy day is higher than any day last month are flagged as needing extra cash.',
      ]}
      actions={[
        'Start with the top of the “Agents needing extra cash” list.',
        'Click an agent to see their 7-day chart and the plain-English advice.',
        'Send cash (or tell the agent) before the peak day. Agents see their own forecast in their app.',
      ]}
      terms={terms}
    />
  );
}

export function AgentAdvice({ agent }) {
  if (!agent) return null;
  if (agent.history_supported === false) {
    return (
      <div className="rounded-box border border-warning/50 bg-warning/10 p-3 text-sm" data-testid="thin-history">
        <strong>Not enough history for agent-specific advice.</strong> This agent had cash-outs on only{' '}
        {agent.active_days_28} of the last 28 days (recent peak {bdt(agent.max_daily_35d_bdt)}). The
        forecast above comes from the model, but it is not reliable for such a thin record, so no
        peak-versus-usual ratio is shown.{' '}
        {agent.peer_peak_p90_bdt != null
          ? <>Qualified peer estimate (median of similar agents with enough history): keep about <strong>{bdt(agent.recommended_opening_float_bdt)}</strong> ready on the busiest day. This is a peer estimate, not this agent&apos;s own pattern.</>
          : 'No comparable peers with enough history either, so there is no cash advice yet.'}
      </div>
    );
  }
  const ratio = agent.pressure_ratio ?? (agent.typical_daily_bdt ? agent.peak_p90_bdt / agent.typical_daily_bdt : null);
  return (
    <div className="rounded-box bg-base-200 p-3 text-sm">
      On <strong>{dayName(agent.peak_date)}</strong> this agent may need up to <strong>{bdt(agent.peak_p90_bdt)}</strong>
      {ratio ? <> — about <strong>{ratio.toFixed(1)}×</strong> a usual day ({bdt(agent.typical_daily_bdt)})</> : null}.
      {' '}Their busiest day last month was {bdt(agent.max_daily_35d_bdt)}.
      {' '}Advice: keep <strong>{bdt(agent.recommended_opening_float_bdt)}</strong> ready that morning.
    </div>
  );
}

function DayTable({ days }) {
  return (
    <div className="overflow-x-auto">
      <table className="table table-xs">
        <thead><tr><th>Day</th><th className="text-right">Likely</th><th className="text-right">Busy day (P90)</th></tr></thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.date}><td>{dayName(d.date)}</td><td className="text-right font-mono">{bdt(d.forecast_bdt)}</td><td className="text-right font-mono">{bdt(d.p90_bdt)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

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
        <Tile label={data.history_supported === false ? 'Peer estimate: cash to keep ready' : 'Keep this much cash ready'} value={bdt(data.recommended_opening_float_bdt)} note={data.history_supported === false ? 'peers with enough history, not this agent' : `on ${data.peak_date}`} />
        <Tile label="Busiest day coming" value={bdt(data.peak_p90_bdt)} note={data.peak_date} />
        <Tile label="Your busiest day last month" value={bdt(data.max_daily_35d_bdt)} note={data.exceeds_recent_max ? 'More customers than usual are coming. Keep extra cash.' : data.max_daily_35d_bdt == null ? 'No past data yet' : 'Normal week ahead'} />
      </div>
      <div className="panel shadow-sm">
        <div className="panel-body">
          <h3 className="font-semibold">Cash needed in the next 7 days · {phone(data.agent_id)}</h3>
          <ForecastChart days={data.days} />
          <AgentAdvice agent={data} />
          <DayTable days={data.days} />
          <p className="muted">
            {data.basis?.startsWith('own') ? 'Based on your past cash-outs.' : data.basis?.startsWith('qualified') ? 'Qualified peer estimate: your own history is too thin.' : 'Based on agents like you, because you have no history yet.'}{' '}
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
                      <td className="font-mono text-xs">{phone(a.agent_id)}</td>
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
            <h3 className="font-semibold">{phone(selected?.agent_id)}</h3>
            {selected && <ForecastChart days={selected.days} />}
            <AgentAdvice agent={selected} />
            {selected && <DayTable days={selected.days} />}
          </div>
        </div>
      </div>

      {data.cohorts && (
        <div className="panel shadow-sm">
          <div className="panel-body">
            <h3 className="font-semibold">Average cash need per agent, by agent size</h3>
            <p className="muted">What a typical agent of each size should plan for next week.</p>
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead><tr><th>Group</th><th className="text-right">Agents</th><th className="text-right">Likely, 7 days total</th><th className="text-right">Busiest day</th><th className="text-right">Busy-day amount</th></tr></thead>
                <tbody>
                  {['low', 'medium', 'high'].filter((k) => data.cohorts[k]).map((size) => {
                    const c = data.cohorts[size];
                    const peak = c.days.reduce((a, d) => (d.p90_bdt > a.p90_bdt ? d : a), c.days[0]);
                    return (
                      <tr key={size}>
                        <td>{sizeName[size] || size}</td>
                        <td className="text-right font-mono">{c.agents.toLocaleString()}</td>
                        <td className="text-right font-mono">{bdt(c.days.reduce((a, d) => a + d.forecast_bdt, 0))}</td>
                        <td className="text-right">{dayName(peak.date)}</td>
                        <td className="text-right font-mono">{bdt(peak.p90_bdt)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {data.provenance && (
              <p className="muted">
                Source: {data.provenance.source}, last {data.provenance.history_days} days · {data.provenance.agents_with_cashouts?.toLocaleString()} agents with cash-outs ·
                {' '}{data.provenance.agents_forecast?.toLocaleString()} forecast · model trained on {data.provenance.agents_trained?.toLocaleString()} agents.
              </p>
            )}
          </div>
        </div>
      )}

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
    let timer;
    const run = () => {
      const load = isAgent ? api.getAgentLiquidity(session.subject) : api.getLiquidityOverview();
      load.then((v) => { if (live) { setData(v); setError(''); } })
        .catch((err) => { if (live) { setError(err.message); timer = setTimeout(run, 20000); } });
    };
    run();
    return () => { live = false; clearTimeout(timer); };
  }, [isAgent, session?.subject]);
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Cash planning</h2>
        <p className="page-lead mt-1">
          How much cash each agent will need in the next 7 days, so no customer is turned away for lack of cash.
          Re-trained every 15 minutes on the live cash-out ledger{data?.computed_at ? ` · updated ${new Date(data.computed_at).toLocaleTimeString()}` : ''}.
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
      <LiquidityGuide agent={isAgent} />
      {data && (isAgent ? <AgentForecast data={data} /> : <AnalystOverview data={data} />)}
    </div>
  );
}
