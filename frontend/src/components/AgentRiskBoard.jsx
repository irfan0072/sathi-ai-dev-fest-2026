import { useState, useEffect } from 'react';
import { api } from '../api';
import { featureLabel } from '../copy';
import { phone } from '../ids';

const levelTone = (level) => ({ high: 'badge-error', medium: 'badge-warning', low: 'badge-success' }[String(level).toLowerCase()] || 'badge-ghost');

export function AgentEvidence({ data }) {
  return (
    <div className="panel shadow-sm">
      <div className="panel-body">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-mono text-lg font-semibold">{phone(data.agent_id)}</h3>
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
              Review score (a ranking for a person to look at, not a fraud probability): {(data.risk * 100).toFixed(0)}%. A high score means “take a look”, not
              “this agent is a fraud”.
            </p>
            <p className="muted mt-1">
              Compared with agents of a similar size ({data.peer_group}). Live, last {data.window_days || 30} days.
            </p>
            {data.cashouts_30d != null && (
              <p className="muted mt-1">
                {data.cashouts_30d.toLocaleString()} cash-outs · {data.checks_30d} confirmation calls · {data.suspicious_30d} suspicious
                {data.duress_30d ? ` · ${data.duress_30d} secret help signals` : ''}
              </p>
            )}
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

const levelText = { high: 'Needs checking', medium: 'Watch', low: 'Looks normal' };

export default function AgentRiskBoard() {
  const [board, setBoard] = useState(null);
  const [level, setLevel] = useState('');
  const [selected, setSelected] = useState('');
  const [risk, setRisk] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    const load = () => api.getAgentRiskBoard({ level, limit: 200 })
      .then((value) => {
        if (!live) return;
        setBoard(value); setError('');
        setSelected((prev) => prev || value.agents[0]?.agent_id || '');
      })
      .catch((err) => { if (live) setError(err.message); });
    load();
    const timer = setInterval(load, 30000);
    return () => { live = false; clearInterval(timer); };
  }, [level]);
  useEffect(() => {
    let live = true;
    setRisk(null);
    if (selected) api.getAgentRisk(selected).then((value) => { if (live) { setRisk(value); setError(''); } }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [selected]);

  const levels = board?.levels || {};
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Agent review ranking (AI)</h2>
        <p className="page-lead mt-1">
          Every agent with activity in the last 30 days, scored live by the trained anomaly model: fee charged compared
          with similar agents, allowance-day spikes, and cash gaps customers reported on their confirmation calls.
          {board?.computed_at ? ` Updated ${new Date(board.computed_at).toLocaleTimeString()} · ${board.total.toLocaleString()} agents scored in ${board.compute_seconds}s.` : ''}
        </p>
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {[['', 'All'], ['high', 'Needs checking'], ['medium', 'Watch'], ['low', 'Looks normal']].map(([id, label]) => (
          <button key={id} className={`btn btn-sm focus-ring ${level === id ? 'btn-primary' : 'btn-ghost border-base-300'}`} onClick={() => { setLevel(id); setSelected(''); }}>
            {label}{id && levels[id] != null ? ` · ${levels[id].toLocaleString()}` : ''}
          </button>
        ))}
      </div>
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="panel h-fit shadow-sm lg:col-span-3">
          <div className="panel-body p-0">
            {!board ? (
              <p className="flex items-center gap-2 p-4 text-sm text-base-content/70"><span className="loading loading-dots loading-sm" />Scoring agents on live data…</p>
            ) : (
              <div className="max-h-[36rem] overflow-auto">
                <table className="table table-sm table-pin-rows">
                  <thead><tr><th>Agent</th><th>Division</th><th>Risk</th><th>Cash-outs 30d</th><th>Suspicious</th><th /></tr></thead>
                  <tbody>
                    {board.agents.map((a) => (
                      <tr key={a.agent_id} onClick={() => setSelected(a.agent_id)} className={`cursor-pointer hover:bg-base-200/60 ${selected === a.agent_id ? 'bg-primary/10' : ''}`}>
                        <td className="font-mono text-xs">{phone(a.agent_id)}</td>
                        <td className="capitalize">{a.region}</td>
                        <td><span className={`badge badge-sm ${levelTone(a.level)}`}>{(a.risk * 100).toFixed(0)}% · {levelText[a.level]}</span></td>
                        <td className="tabular-nums">{a.cashouts_30d.toLocaleString()}</td>
                        <td className={a.suspicious_30d ? 'font-semibold text-error' : ''}>{a.suspicious_30d || ''}</td>
                        <td>{a.watchlisted && <span className="badge badge-warning badge-xs">watchlist</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
        <div className="lg:col-span-2">
          {risk ? <AgentEvidence data={risk} /> : selected && <span className="loading loading-dots loading-sm" />}
        </div>
      </div>
    </div>
  );
}
