import { useEffect, useState } from 'react';
import { api } from '../api';
import { ErrorBars, QiniChart } from './Charts';

const policyNames = {
  uplift_t_learner: 'Uplift model (T-learner)', response_model: 'Response model',
  agent_dependence_rule: 'Agent-dependence rule', random: 'Random',
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
      <h3 className="font-semibold">Budget optimizer</h3>
      <p className="muted">Picks who to contact and by which channel (SMS, IVR call, agent visit) to get the most extra enrollments per taka. Customers with no positive uplift are never contacted.</p>
      <div className="flex flex-wrap items-end gap-2">
        <label>
          <span className="mb-1 block text-sm">Budget (BDT)</span>
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
            <div className="muted">Expected extra enrollments</div>
            <div className="text-2xl font-bold">{plan.expected_incremental_enrollments}</div>
            <div className="muted">৳{plan.cost_per_incremental_bdt ?? '—'} per extra enrollment · spent ৳{plan.spent_bdt.toLocaleString()}</div>
          </div>
          <div className="rounded-box bg-base-200 p-3">
            <div className="muted">Same budget, response model, IVR only</div>
            <div className="text-2xl font-bold">{plan.comparison_response_model_ivr_only.expected_incremental_enrollments}</div>
            <div className="muted">{lift ? `Uplift plan gets ${lift.toFixed(1)}× the extra enrollments` : 'No comparison available'}</div>
          </div>
          <div className="sm:col-span-2 flex flex-wrap gap-2 text-sm">
            {Object.entries(plan.by_channel).map(([channel, count]) => (
              <span key={channel} className="badge badge-outline gap-1">{channel.replace('_', ' ')} <strong>{count.toLocaleString()}</strong></span>
            ))}
            <span className="badge badge-ghost">{plan.skipped_non_positive_uplift.toLocaleString()} skipped (no positive uplift)</span>
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
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">Sathi Adoption Campaign · Uplift</h2>
        <p className="page-lead">Who should we invite to Sathi so the invitation itself changes behavior? Targets persuadable customers, not those who would enroll anyway.</p>
      </div>
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">Unavailable: {error}</div>}
      {!data && !error && <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Loading experiment…</p>}
      {data && <>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="panel"><div className="panel-body gap-1 p-4">
            <span className="muted">Extra enrollments, top 20% contacted</span>
            <span className="text-2xl font-bold">{p.uplift_t_learner.true_incremental_top20}</span>
            <span className="muted">{gain >= 0 ? '+' : ''}{gain.toFixed(0)}% vs response model ({p.response_model.true_incremental_top20})</span>
          </div></div>
          <div className="panel"><div className="panel-body gap-1 p-4">
            <span className="muted">Holdout experiment</span>
            <span className="text-2xl font-bold">{data.experiment.holdout_users.toLocaleString()}</span>
            <span className="muted">customers · {data.experiment.holdout_treated.toLocaleString()} contacted at random</span>
          </div></div>
          <div className="panel"><div className="panel-body gap-1 p-4">
            <span className="muted">Uplift vs injected truth</span>
            <span className="text-2xl font-bold">r = {data.uplift_truth_correlation}</span>
            <span className="muted">correlation with the known synthetic effect</span>
          </div></div>
        </div>

        <div className="grid gap-5 lg:grid-cols-5">
          <div className="panel lg:col-span-3"><div className="panel-body">
            <h3 className="font-semibold">Qini curves (holdout)</h3>
            <QiniChart policies={p} />
          </div></div>
          <div className="panel lg:col-span-2"><div className="panel-body">
            <h3 className="font-semibold">Policy comparison</h3>
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead><tr><th>Policy</th><th className="text-right">Qini</th><th className="text-right">Top 20% extra (true)</th></tr></thead>
                <tbody>{Object.entries(p).sort((a, b) => b[1].qini_coefficient - a[1].qini_coefficient).map(([name, v]) => (
                  <tr key={name}><td>{policyNames[name] || name}</td><td className="text-right font-mono">{v.qini_coefficient}</td><td className="text-right font-mono">{v.true_incremental_top20}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <h4 className="mt-2 text-sm font-semibold">Top uplift drivers</h4>
            <ErrorBars rows={data.feature_importance.slice(0, 5).map((f) => ({ label: f.feature, value: f.gain_share }))} format={(v) => `${(v * 100).toFixed(0)}%`} highlightLowest={false} />
          </div></div>
        </div>

        <Optimizer />
        <ul className="muted list-inside list-disc">{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
      </>}
    </div>
  );
}
