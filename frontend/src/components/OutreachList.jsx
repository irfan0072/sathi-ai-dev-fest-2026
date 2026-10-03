import { useState, useEffect } from 'react';
import { api } from '../api';
import { featureLabel } from '../copy';

export function UserReasons({ data }) {
  return (
    <div className="panel shadow-sm">
      <div className="panel-body">
        <h3 className="font-semibold">Why {data.user_id} may need help</h3>
        <p className="text-sm">
          Chance this person needs help with payments: <strong>{(data.score * 100).toFixed(0)}%</strong>. Used only to offer help.
        </p>
        <p className="muted">
          Bigger numbers pushed the score up more (technical unit: raw log-odds).
        </p>
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>What we noticed</th>
                <th className="text-right">Value</th>
                <th className="text-right">Effect on score</th>
              </tr>
            </thead>
            <tbody>
              {data.top_reasons.map((reason) => (
                <tr key={reason.feature}>
                  <td>{featureLabel(reason.feature)}</td>
                  <td className="text-right font-mono">{reason.value.toFixed(3)}</td>
                  <td
                    className={`text-right font-mono ${reason.attribution >= 0 ? 'text-warning' : 'text-info'}`}
                  >
                    {reason.attribution.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
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
    if (initialData) return () => { live = false; };
    const load = () => api.getOutreachList().then((value) => { if (live) { setData(value); setError(''); } }).catch((err) => { if (live) setError(err.message); });
    load();
    const timer = setInterval(load, 60000);
    return () => { live = false; clearInterval(timer); };
  }, [initialData]);
  const select = async (id) => {
    setScore(null); setError(''); setSelected(id);
    try { setScore(await api.getUserAssistedScore(id)); } catch (err) { setError(err.message); }
  };

  return (
    <div className="flex flex-col gap-2">
      <div>
        <h2 className="page-title">Customers who may need help</h2>
        <p className="page-lead mt-1">
          Customers active in the last 30 days who may need someone to help them pay, so we can offer Sathi to them first.
          Scored live by the trained AI from their real activity
          {data?.computed_at ? ` · updated ${new Date(data.computed_at).toLocaleTimeString()}` : ''}.
        </p>
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      {!data ? (
        <p className="flex items-center gap-2 text-sm text-base-content/70">
          <span className="loading loading-dots loading-sm" />
          Scoring active customers…
        </p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="panel shadow-sm">
            <div className="panel-body p-2 sm:p-4">
              <p className="muted px-2">
                {data.scored_customers?.toLocaleString() ?? data.total} customers scored · {data.likely_assisted ?? '—'} likely need help · top {data.items.length} shown
              </p>
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Customer</th>
                      <th>Chance</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((item, index) => (
                      <tr
                        key={item.user_id}
                        className={`transition-colors hover:bg-base-200 ${
                          selected === item.user_id ? 'bg-primary/10' : ''
                        }`}
                      >
                        <td>{index + 1}</td>
                        <td className="font-mono text-xs">{item.user_id}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <progress
                              className="progress progress-primary hidden w-16 sm:block"
                              value={item.assisted_score * 100}
                              max="100"
                            />
                            <span className="font-mono text-xs">{(item.assisted_score * 100).toFixed(1)}%</span>
                          </div>
                        </td>
                        <td className="text-right">
                          <button className="btn btn-ghost btn-xs focus-ring" onClick={() => select(item.user_id)}>
                            Why?
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          {score ? (
            <UserReasons data={score} />
          ) : (
            <div className="panel shadow-sm">
              <div className="panel-body items-center justify-center py-10 text-center text-sm text-base-content/60">
                Choose a customer to see why they are on this list.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
