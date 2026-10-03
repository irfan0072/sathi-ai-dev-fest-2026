import { useState, useEffect } from 'react';
import { api } from '../api';

export function UserReasons({ data }) {
  return (
    <div className="panel">
      <div className="panel-body">
        <h3 className="font-semibold">{data.user_id} · saved model explanation</h3>
        <p className="text-sm">Calibrated assisted probability: <strong>{(data.score * 100).toFixed(2)}%</strong>. Outreach only.</p>
        <p className="muted">SHAP contributions explain the fitted base model in raw log-odds, not calibrated probability.</p>
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead><tr><th>Behavior</th><th className="text-right">Observed value</th><th className="text-right">SHAP raw log-odds</th></tr></thead>
            <tbody>{data.top_reasons.map((reason) => (
              <tr key={reason.feature}>
                <td>{reason.feature}</td>
                <td className="text-right font-mono">{reason.value.toFixed(3)}</td>
                <td className={`text-right font-mono ${reason.attribution >= 0 ? 'text-warning' : 'text-info'}`}>{reason.attribution.toFixed(4)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function OutreachList({ initialData = null }) {
  const [data, setData] = useState(initialData);
  const [score, setScore] = useState(null);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    if (!initialData) api.getOutreachList().then((value) => { if (live) setData(value); }).catch((err) => { if (live) { setData(null); setError(err.message); } });
    return () => { live = false; };
  }, [initialData]);
  const select = async (id) => {
    setScore(null); setError(''); setSelected(id);
    try { setScore(await api.getUserAssistedScore(id)); } catch (err) { setError(err.message); }
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">Assisted User Outreach List</h2>
        <p className="page-lead">Bounded frozen synthetic snapshot · highest predicted outreach probabilities · separate from runtime demo customer.</p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {!data ? (
        <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Unavailable — waiting for verified saved evidence.</p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="panel">
            <div className="panel-body p-2 sm:p-4">
              <p className="muted px-2">{data.total} saved subjects · snapshot {data.run_provenance.as_of} · {data.selection}</p>
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead><tr><th>Rank</th><th>Synthetic ID</th><th>Saved probability</th><th /></tr></thead>
                  <tbody>{data.items.map((item, index) => (
                    <tr key={item.user_id} className={selected === item.user_id ? 'bg-primary/10' : ''}>
                      <td>{index + 1}</td>
                      <td className="font-mono text-xs">{item.user_id}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <progress className="progress progress-primary hidden w-16 sm:block" value={item.assisted_score * 100} max="100" />
                          <span className="font-mono text-xs">{(item.assisted_score * 100).toFixed(2)}%</span>
                        </div>
                      </td>
                      <td className="text-right"><button className="btn btn-ghost btn-xs" onClick={() => select(item.user_id)}>View SHAP evidence</button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          </div>
          {score ? <UserReasons data={score} /> : <div className="panel"><div className="panel-body items-center justify-center py-10 text-center text-sm opacity-60">Select a subject to see why the model ranked them.</div></div>}
        </div>
      )}
    </div>
  );
}
