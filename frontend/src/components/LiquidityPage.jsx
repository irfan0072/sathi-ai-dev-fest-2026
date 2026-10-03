import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorBars, ForecastChart } from './Charts';

const bdt = (v) => (v == null ? '—' : `৳${Math.round(v).toLocaleString('en-US')}`);

function Tile({ label, value, note }) {
  return (
    <div className="panel">
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
        <Tile label="Recommended opening cash" value={bdt(data.recommended_opening_float_bdt)} note={`for ${data.peak_date}`} />
        <Tile label="Busiest day (P90)" value={bdt(data.peak_p90_bdt)} note={data.peak_date} />
        <Tile label="Busiest recent day" value={bdt(data.max_daily_35d_bdt)} note={data.exceeds_recent_max ? 'Surge expected: plan extra cash' : data.max_daily_35d_bdt == null ? 'no own history yet' : 'within recent range'} />
      </div>
      <div className="panel"><div className="panel-body">
        <h3 className="font-semibold">Next 7 days · {data.agent_id}</h3>
        <ForecastChart days={data.days} />
        <p className="muted">Basis: {data.basis}. Forecast origin {data.forecast_origin} (synthetic timeline). Planning aid only; it never limits a customer&apos;s cash-out.</p>
      </div></div>
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
        <Tile label="Forecast error (WAPE, holdout)" value={holdout.lightgbm.wape.toFixed(2)} note={`moving average ${holdout.moving_average_7.wape.toFixed(2)}`} />
        <Tile label="P90 coverage" value={`${(holdout.p90_coverage * 100).toFixed(1)}%`} note="target 90% of days at or below P90" />
        <Tile label="Surge alerts" value={`${data.agents_under_pressure} / ${data.total_agents}`} note="expected peak above busiest day of last 35 days" />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel lg:col-span-3"><div className="panel-body">
          <h3 className="font-semibold">Agents needing extra cash</h3>
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Agent</th><th className="text-right">Busiest recent day</th><th className="text-right">Peak P90</th><th className="text-right">Extra cash</th><th className="text-right">Open with</th></tr></thead>
              <tbody>{data.agents.map((a) => (
                <tr key={a.agent_id} className={`cursor-pointer hover:bg-base-200 ${selected?.agent_id === a.agent_id ? 'bg-primary/10' : ''}`} onClick={() => setSelected(a)}>
                  <td className="font-mono text-xs">{a.agent_id}</td>
                  <td className="text-right font-mono text-xs">{bdt(a.max_daily_35d_bdt)}</td>
                  <td className="text-right font-mono text-xs">{bdt(a.peak_p90_bdt)}</td>
                  <td className="text-right">{a.exceeds_recent_max
                    ? <span className="badge badge-sm badge-warning gap-1 whitespace-nowrap">surge +{bdt(a.headroom_needed_bdt)}</span>
                    : <span className="badge badge-sm badge-ghost">{bdt(a.headroom_needed_bdt)}</span>}</td>
                  <td className="text-right font-mono text-xs">{bdt(a.recommended_opening_float_bdt)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div></div>
        <div className="panel lg:col-span-2"><div className="panel-body">
          <h3 className="font-semibold">{selected?.agent_id}</h3>
          {selected && <ForecastChart days={selected.days} />}
        </div></div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="panel"><div className="panel-body">
          <h3 className="font-semibold">Model vs baselines (lower is better)</h3>
          <ErrorBars rows={[
            { label: 'LightGBM', value: holdout.lightgbm.wape },
            { label: '7-day average', value: holdout.moving_average_7.wape },
            { label: 'Same day last week', value: holdout.seasonal_naive.wape },
          ]} />
          <p className="muted">WAPE on {holdout.rows.toLocaleString()} agent-days from origins {data.test_origins.join(' → ')}, never used for training.
            {unseen && ` On an unseen agent population: WAPE ${unseen.lightgbm.wape.toFixed(2)}.`} Daily agent demand is lumpy, so errors stay high in absolute terms.</p>
        </div></div>
        <div className="panel"><div className="panel-body">
          <h3 className="font-semibold">What drives the forecast</h3>
          <ErrorBars rows={data.feature_importance.slice(0, 6).map((f) => ({ label: f.feature, value: f.gain_share }))} format={(v) => `${(v * 100).toFixed(0)}%`} highlightLowest={false} />
          <ul className="muted list-inside list-disc">{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div></div>
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
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">Agent Liquidity Forecast</h2>
        <p className="page-lead">Predicts each agent&apos;s cash-out demand for the next 7 days so they open with enough cash. Customers who are turned away go to informal, riskier cash-out.</p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {!data && !error && <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Loading forecast…</p>}
      {data && (isAgent ? <AgentForecast data={data} /> : <AnalystOverview data={data} />)}
    </div>
  );
}
