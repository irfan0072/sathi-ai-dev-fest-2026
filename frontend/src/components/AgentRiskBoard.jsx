import { useState, useEffect } from 'react';
import { api } from '../api';

const levelTone = (level) => ({ high: 'badge-error', medium: 'badge-warning', low: 'badge-success' }[String(level).toLowerCase()] || 'badge-ghost');

export function AgentEvidence({ data }) {
  return (
    <div className="panel">
      <div className="panel-body">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-mono text-lg font-semibold">{data.agent_id}</h3>
          <span className={`badge ${levelTone(data.level)}`}>{data.level}</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="radial-progress text-primary" style={{ '--value': Math.round(data.risk * 100), '--size': '4.5rem' }} role="img" aria-label="Saved anomaly risk">
            <span className="text-sm font-semibold">{(data.risk * 100).toFixed(0)}%</span>
          </div>
          <div className="text-sm">
            <p>Saved anomaly risk: {(data.risk * 100).toFixed(2)}% · {data.level}. Risk is a review score, not a fraud probability.</p>
            <p className="muted mt-1">{data.peer_group} · {data.provenance}</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead><tr><th>Behavior</th><th className="text-right">Observed value</th><th className="text-right">Saved reference</th></tr></thead>
            <tbody>{data.reasons.map((reason) => (
              <tr key={reason.feature}><td>{reason.feature}</td><td className="text-right font-mono">{reason.value}</td><td className="text-right font-mono">{reason.peer_median}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <p className="muted">Fee references use training volume peers. Allowance spike reference is an assumed normal ratio. This signal never authorizes or penalizes a transaction.</p>
      </div>
    </div>
  );
}

export default function AgentRiskBoard() {
  const [ids, setIds] = useState([]);
  const [selected, setSelected] = useState('');
  const [risk, setRisk] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api.getMetricsSummary().then((value) => { if (live) { setIds(value.snapshot_agent_ids); setSelected(value.snapshot_agent_ids[0] || ''); } }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    let live = true;
    setRisk(null);
    if (selected) api.getAgentRisk(selected).then((value) => { if (live) { setRisk(value); setError(''); } }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [selected]);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">Agent Anomaly Risk Board</h2>
        <p className="page-lead">Bounded frozen synthetic snapshot · highest saved risk scores · no ground-truth labels or demographic selection.</p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="panel h-fit">
          <div className="panel-body p-2 sm:p-3">
            <label className="px-2 lg:hidden">
              <span className="mb-1 block text-sm">Snapshot agent</span>
              <select className="select select-bordered w-full" value={selected} onChange={(e) => setSelected(e.target.value)}>
                {ids.map((id) => <option key={id}>{id}</option>)}
              </select>
            </label>
            <ul className="menu hidden w-full p-0 lg:flex">
              <li className="menu-title">Snapshot agent</li>
              {ids.map((id) => (
                <li key={id}><button className={`font-mono text-xs ${selected === id ? 'menu-active' : ''}`} onClick={() => setSelected(id)}>{id}</button></li>
              ))}
            </ul>
          </div>
        </div>
        <div className="lg:col-span-2">
          {risk ? <AgentEvidence data={risk} /> : <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Unavailable — waiting for verified saved evidence.</p>}
        </div>
      </div>
    </div>
  );
}
