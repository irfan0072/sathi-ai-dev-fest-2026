import { useState, useEffect } from 'react';
import { api } from '../api';
export function UserReasons({ data }) {
  return <div className="glass-card"><h3>{data.user_id} · saved model explanation</h3>
    <p>Calibrated assisted probability: {(data.score * 100).toFixed(2)}%. Outreach only.</p>
    <p>SHAP contributions explain the fitted base model in raw log-odds, not calibrated probability.</p>
    <table className="data-table"><thead><tr><th>Behavior</th><th>Observed value</th><th>SHAP raw log-odds</th></tr></thead>
      <tbody>{data.top_reasons.map((reason) => <tr key={reason.feature}><td>{reason.feature}</td><td>{reason.value.toFixed(3)}</td><td>{reason.attribution.toFixed(4)}</td></tr>)}</tbody></table></div>;
}
export default function OutreachList({ initialData = null }) {
  const [data, setData] = useState(initialData);
  const [score, setScore] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    if (!initialData) api.getOutreachList().then((value) => { if (live) setData(value); }).catch((err) => { if (live) { setData(null); setError(err.message); } });
    return () => { live = false; };
  }, [initialData]);
  const select = async (id) => {
    setScore(null); setError('');
    try { setScore(await api.getUserAssistedScore(id)); } catch (err) { setError(err.message); }
  };
  return <div><h2 className="card-title">Assisted User Outreach List</h2>
    <p>Bounded frozen synthetic snapshot · highest predicted outreach probabilities · separate from runtime demo customer.</p>
    {error && <p role="alert" className="error-box">Unavailable: {error}</p>}
    {!data ? <p>Unavailable — waiting for verified saved evidence.</p> : <>
      <p>{data.total} saved subjects · snapshot {data.run_provenance.as_of} · {data.selection}</p>
      <div className="glass-card"><table className="data-table"><thead><tr><th>Rank</th><th>Synthetic ID</th><th>Saved probability</th><th>Evidence</th></tr></thead>
        <tbody>{data.items.map((item, index) => <tr key={item.user_id}><td>{index + 1}</td><td>{item.user_id}</td><td>{(item.assisted_score * 100).toFixed(2)}%</td><td><button className="chip-btn" onClick={() => select(item.user_id)}>View SHAP evidence</button></td></tr>)}</tbody></table></div>
    </>}{score && <UserReasons data={score} />}</div>;
}
