import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorBars, QiniChart } from './Charts';

const channelName = { sms: 'SMS', ivr_call: 'Phone call', agent_visit: 'Agent visit' };
const featureName = {
  withdrawn_fraction: 'How much of their money they withdraw', pin_entry_seconds: 'Time taken to type PIN',
  app_share: 'How often they use the app', credit_to_cashout_hours: 'How fast they cash out after money arrives',
  cashout_median_bdt: 'Usual cash-out amount', top_agent_share: 'How much they rely on one agent',
  pin_retries_mean: 'Wrong PIN tries', service_count: 'Other services used', cashout_count: 'Number of cash-outs',
};

const policyNames = {
  uplift_t_learner: 'Sathi AI (picks people the invite will change)', response_model: 'Usual method (picks likely joiners)',
  agent_dependence_rule: 'Simple rule (relies on one agent)', random: 'Random pick',
};
const presets = [2000, 10000, 50000];

function Optimizer() {
  const [budget, setBudget] = useState('10000');
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = async (value = budget) => {
    setBusy(true); setError('');
    try { setPlan(await api.optimizeCampaign(Number(value))); } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const lift = plan && plan.comparison_response_model_ivr_only.expected_incremental_enrollments > 0
    ? plan.expected_incremental_enrollments / plan.comparison_response_model_ivr_only.expected_incremental_enrollments
    : null;
  return (
    <div className="panel"><div className="panel-body">
      <h3 className="font-semibold">Plan a campaign</h3>
      <p className="muted">Enter your budget. We pick who to invite and how (SMS, phone call or agent visit) to get the most new users for the money. People the invite would not help are never contacted.</p>
      <div className="flex flex-wrap items-end gap-2">
        <label>
          <span className="mb-1 block text-sm">Budget (Taka)</span>
          <input className="input input-bordered input-sm w-36" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </label>
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => run()}>Optimize</button>
        <div className="join">
          {presets.map((p) => <button key={p} className="btn btn-ghost btn-sm join-item" onClick={() => { setBudget(String(p)); run(p); }}>৳{p.toLocaleString()}</button>)}
        </div>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
      {plan && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-box bg-base-200 p-3">
            <div className="muted">New users you can expect</div>
            <div className="text-2xl font-bold">{plan.expected_incremental_enrollments}</div>
            <div className="muted">৳{plan.cost_per_incremental_bdt ?? '—'} per extra enrollment · spent ৳{plan.spent_bdt.toLocaleString()}</div>
          </div>
          <div className="rounded-box bg-base-200 p-3">
            <div className="muted">Same money, usual method</div>
            <div className="text-2xl font-bold">{plan.comparison_response_model_ivr_only.expected_incremental_enrollments}</div>
            <div className="muted">{lift ? `Our plan brings ${lift.toFixed(1)}× more new users` : 'No comparison available'}</div>
          </div>
          <div className="sm:col-span-2 flex flex-wrap gap-2 text-sm">
            {Object.entries(plan.by_channel).map(([channel, count]) => (
              <span key={channel} className="badge badge-outline gap-1">{channelName[channel] || channel} <strong>{count.toLocaleString()}</strong></span>
            ))}
            <span className="badge badge-ghost">{plan.skipped_non_positive_uplift.toLocaleString()} not contacted (invite would not help)</span>
          </div>
        </div>
      )}
    </div></div>
  );
}

export default function UpliftPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    api.getUpliftSummary().then((v) => { if (live) setData(v); }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, []);
  const p = data?.policies;
  const gain = p ? (p.uplift_t_learner.true_incremental_top20 / p.response_model.true_incremental_top20 - 1) * 100 : 0;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">Who to invite to Sathi</h2>
        <p className="page-lead mt-1">
          Find the customers who will start using Sathi because we invited them, not people who would join anyway.
        </p>
      </div>
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      {!data && !error && (
        <p className="flex items-center gap-2 text-sm text-base-content/70">
          <span className="loading loading-dots loading-sm" />
          Loading experiment…
        </p>
      )}
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="panel transition-colors hover:border-primary/40">
              <div className="panel-body gap-1 p-4">
                <span className="muted">New users when inviting the top 20%</span>
                <span className="text-2xl font-bold">{p.uplift_t_learner.true_incremental_top20}</span>
                <span className="muted">
                  {gain >= 0 ? '+' : ''}
                  {gain.toFixed(0)}% compared with the usual method ({p.response_model.true_incremental_top20})
                </span>
              </div>
            </div>
            <div className="panel transition-colors hover:border-primary/40">
              <div className="panel-body gap-1 p-4">
                <span className="muted">Tested on</span>
                <span className="text-2xl font-bold">{data.experiment.holdout_users.toLocaleString()}</span>
                <span className="muted">
                  customers · {data.experiment.holdout_treated.toLocaleString()} invited at random
                </span>
              </div>
            </div>
            <div className="panel transition-colors hover:border-primary/40">
              <div className="panel-body gap-1 p-4">
                <span className="muted">How close the AI is to the real answer</span>
                <span className="text-2xl font-bold">{Math.round(data.uplift_truth_correlation * 100)}%</span>
                <span className="muted">match with the known result in this test data</span>
              </div>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            <div className="panel shadow-sm lg:col-span-3">
              <div className="panel-body">
                <h3 className="font-semibold">New users as more people are invited</h3>
                <QiniChart policies={p} />
              </div>
            </div>
            <div className="panel shadow-sm lg:col-span-2">
              <div className="panel-body">
                <h3 className="font-semibold">Which way of choosing works best</h3>
                <div className="overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr>
                        <th>Method</th>
                        <th className="text-right">Score</th>
                        <th className="text-right">New users (top 20%)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(p)
                        .sort((a, b) => b[1].qini_coefficient - a[1].qini_coefficient)
                        .map(([name, v]) => (
                          <tr key={name}>
                            <td>{policyNames[name] || name}</td>
                            <td className="text-right font-mono">{v.qini_coefficient}</td>
                            <td className="text-right font-mono">{v.true_incremental_top20}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                <h4 className="mt-2 text-sm font-semibold">What the AI looks at most</h4>
                <ErrorBars
                  rows={data.feature_importance
                    .slice(0, 5)
                    .map((f) => ({ label: featureName[f.feature] || f.feature, value: f.gain_share }))}
                  format={(v) => `${(v * 100).toFixed(0)}%`}
                  highlightLowest={false}
                />
              </div>
            </div>
          </div>

          <Optimizer />
          <ul className="muted list-inside list-disc">
            {data.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
