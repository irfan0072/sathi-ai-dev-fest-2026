import { useState, useEffect } from 'react';
import { api } from '../api';
export function AgentEvidence({ data }) {
  return <div className="glass-card"><h3>{data.agent_id}</h3>
    <p>Saved anomaly risk: {(data.risk * 100).toFixed(2)}% · {data.level}. Risk is a review score, not a fraud probability.</p>
    <p>{data.peer_group} · {data.provenance}</p>
    <table className="data-table"><thead><tr><th>Behavior</th><th>Observed value</th><th>Saved reference</th></tr></thead>
      <tbody>{data.reasons.map((reason) => <tr key={reason.feature}><td>{reason.feature}</td><td>{reason.value}</td><td>{reason.peer_median}</td></tr>)}</tbody></table>
    <p>Fee references use training volume peers. Allowance spike reference is an assumed normal ratio. This signal never authorizes or penalizes a transaction.</p>
  </div>;
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
  return <div><h2 className="card-title">Agent Anomaly Risk Board</h2>
    <p>Bounded frozen synthetic snapshot · highest saved risk scores · no ground-truth labels or demographic selection.</p>
    {error && <p className="error-box" role="alert">Unavailable: {error}</p>}
    <label>Snapshot agent<select value={selected} onChange={(e) => setSelected(e.target.value)}>{ids.map((id) => <option key={id}>{id}</option>)}</select></label>
    {risk ? <AgentEvidence data={risk} /> : <p>Unavailable — waiting for verified saved evidence.</p>}
  </div>;
}
