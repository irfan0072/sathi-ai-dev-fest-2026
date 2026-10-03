import { useState, useEffect } from 'react';
import { api } from '../api';
import { featureLabel } from '../copy';

const levelTone = (level) => ({ high: 'badge-error', medium: 'badge-warning', low: 'badge-success' }[String(level).toLowerCase()] || 'badge-ghost');

export function AgentEvidence({ data }) {
  return (
    <div className="panel shadow-sm">
      <div className="panel-body">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-mono text-lg font-semibold">{data.agent_id}</h3>
          <span className={`badge ${levelTone(data.level)}`}>{({ high: 'Needs checking', medium: 'Watch', low: 'Looks normal' })[String(data.level).toLowerCase()] || data.level}</span>
        </div>
        <div className="flex items-center gap-4">
          <div
            className="radial-progress text-primary"
            style={{ '--value': Math.round(data.risk * 100), '--size': '4.5rem' }}
            role="img"
            aria-label="Unusual activity score"
          >
            <span className="text-sm font-semibold">{(data.risk * 100).toFixed(0)}%</span>
          </div>
          <div className="text-sm">
            <p>
              Unusual activity score: {(data.risk * 100).toFixed(0)}%. A high score means “take a look”, not
              “this agent is a fraud”.
            </p>
            <p className="muted mt-1">
              Compared with agents of a similar size.
            </p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>What we checked</th>
                <th className="text-right">This agent</th>
                <th className="text-right">Normal</th>
              </tr>
            </thead>
            <tbody>
              {data.reasons.map((reason) => (
                <tr key={reason.feature}>
                  <td>{featureLabel(reason.feature)}</td>
                  <td className="text-right font-mono">{reason.value}</td>
                  <td className="text-right font-mono">{reason.peer_median}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          This only helps supervisors decide whom to check. It never blocks or punishes an agent.
        </p>
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
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Agent check</h2>
        <p className="page-lead mt-1">
          Agents whose activity looks unusual compared with similar agents (frozen synthetic snapshot of demo data).
        </p>
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="panel h-fit shadow-sm">
          <div className="panel-body p-2 sm:p-3">
            <label className="px-2 lg:hidden">
              <span className="mb-1 block text-sm">Choose an agent</span>
              <select
                className="select select-bordered w-full focus-ring"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {ids.map((id) => (
                  <option key={id}>{id}</option>
                ))}
              </select>
            </label>
            <ul className="menu hidden w-full p-0 lg:flex">
              <li className="menu-title">Agents</li>
              {ids.map((id) => (
                <li key={id}>
                  <button
                    className={`font-mono text-xs focus-ring ${selected === id ? 'menu-active' : ''}`}
                    onClick={() => setSelected(id)}
                  >
                    {id}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="lg:col-span-2">
          {risk ? (
            <AgentEvidence data={risk} />
          ) : (
            <p className="flex items-center gap-2 text-sm text-base-content/70">
              <span className="loading loading-dots loading-sm" />
              Unavailable — loading the agent list.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
