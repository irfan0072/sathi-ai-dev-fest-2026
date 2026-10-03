import { useState, useEffect } from 'react';
import { api } from '../api';
const fmt = (value, digits = 4) => value == null ? 'Undefined' : Number(value).toFixed(digits);
const percent = (value) => value == null ? 'Undefined' : `${(value * 100).toFixed(2)}%`;
export function EvidenceTables({ data }) {
  const [adoption, setAdoption] = useState('adoption_50pct');
  const r = data.results;
  const users = r.experiment_1_assisted_detection;
  const shifted = r.experiment_6_distribution_shift;
  const impact = r.experiment_5_adoption_sensitivity;
  const scenario = impact.scenarios[adoption];
  const userRows = [];
  for (const cohort of ['validation_diagnostic','held_out_test']) {
    const item = users[cohort];
    for (const method of ['rule_baseline','assisted_classifier']) userRows.push({ cohort, method, metrics: item[method], n: item.denominators });
  }
  userRows.push({ cohort: 'held_out_shifted', method: 'rule_baseline', metrics: shifted.assisted_classifier.rule_baseline_shifted });
  userRows.push({ cohort: 'held_out_shifted', method: 'assisted_classifier', metrics: shifted.assisted_classifier.shifted_test });
  return <>
    <p>Verified frozen run {data.provenance.final_run_timestamp} · source {data.provenance.git_revision.slice(0, 8)} · seeds {Object.entries(data.seeds).map(([k,v]) => `${k}=${v}`).join(', ')}.</p>
    <p>{data.provenance.window_days}-day offline window · snapshot {data.provenance.as_of}. Synthetic future dates are simulation coordinates, not live events.</p>
    <div className="glass-card"><h3>Assisted behavior: rules and LightGBM</h3>
      <p>Validation uses the calibration cohort and is diagnostic. Held-out/shifted cohorts are separate estimates. PR-AUC is trapezoidal area, not average precision. Undefined means not reported or insufficient coverage.</p>
      <table className="data-table"><thead><tr><th>Cohort</th><th>Method</th><th>PR-AUC</th><th>Precision</th><th>Recall</th><th>Brier</th><th>Recall at ≥80% precision</th><th>n / positives</th></tr></thead>
        <tbody>{userRows.map((row) => <tr key={row.cohort + row.method}><td>{row.cohort}</td><td>{row.method}</td><td>{fmt(row.metrics.pr_auc)}</td><td>{fmt(row.metrics.precision ?? row.metrics.precision_at_threshold)}</td><td>{fmt(row.metrics.recall ?? row.metrics.recall_at_threshold)}</td><td>{fmt(row.metrics.brier_score)}</td><td>{fmt(row.metrics.recall_at_80p_precision ?? row.metrics.operating_recall)}</td><td>{row.n ? `${row.n.total_users} / ${row.n.positives_assisted}` : 'See shifted fairness denominators'}</td></tr>)}</tbody></table>
    </div>
    <div className="glass-card"><h3>Agent review: fixed top-K and high-risk threshold</h3><p>Ranking precision@K differs from threshold flags. Small injected-skimmer and honest high-volume samples limit conclusions.</p>
      <table className="data-table"><thead><tr><th>Cohort / method</th><th>Agents / skimmers / honest HV</th><th>K</th><th>Precision@K</th><th>Skimmer recall</th><th>Honest HV false flags</th></tr></thead><tbody>
        {['validation','held_out_test','shifted_test'].map((cohort) => {
          const item = cohort === 'shifted_test' ? shifted.agent_detector.shifted_test : r.experiment_2_agent_anomaly[cohort];
          return ['baseline_rule','peer_robust_zscore','isolation_forest','combined_ensemble'].map((method) => <tr key={cohort + method}><td>{cohort} / {method}</td><td>{item.denominators.total_agents} / {item.denominators.total_skimmers} / {item.denominators.total_honest_high_volume}</td><td>{item.review_top_k_clipped ?? item.denominators.review_top_k_clipped}</td><td>{fmt(item[method].precision_at_k)}</td><td>{percent(item[method].recall_on_skimmers)}</td><td>{percent(item[method].false_flag_rate_honest_high_volume)}</td></tr>);
        })}</tbody></table>
    </div>
    <div className="glass-card"><h3>Adoption sensitivity · idealized ASSUMPTIONS</h3><p>{impact.disclaimer}</p>
      <p>Eligible loss ৳{fmt(impact.eligible_assisted_skimming_loss_bdt, 2)} BDT from {impact.eligible_assisted_skimmer_actions} eligible skimmer actions; total injected loss ৳{fmt(impact.total_injected_skimming_loss_bdt, 2)} BDT from {impact.total_test_skimmer_actions} actions. Eligible assisted cash-outs: {impact.total_eligible_assisted_cashouts}.</p>
      <label>Saved adoption scenario<select value={adoption} onChange={(e) => setAdoption(e.target.value)}>{Object.entries(impact.scenarios).map(([key,value]) => <option key={key} value={key}>{percent(value.adoption_rate)}</option>)}</select></label>
      {scenario && <p className="result-box">Idealized eligible loss prevented: ৳{fmt(scenario.loss_prevented_bdt, 2)} BDT · {scenario.pct_eligible_assisted_loss_prevented}% eligible loss · {scenario.pct_total_injected_loss_prevented}% total injected loss.</p>}
      <p>Perfect compliance is assumed. Amount confirmation cannot prove physical cash delivery. This is not measured field benefit.</p>
    </div>
    <div className="glass-card"><h3>Skimming profiles and validation ablations</h3>
      <table className="data-table"><thead><tr><th>Injected intensity</th><th>Skimmers / honest</th><th>Detection</th><th>Honest false flags</th></tr></thead><tbody>{Object.entries(r.experiment_3_skimming_sweep).map(([key,value]) => <tr key={key}><td>{key}</td><td>{value.skimmer_count} / {value.honest_agent_count}</td><td>{percent(value.skimmer_detection_rate)}</td><td>{percent(value.honest_false_flag_rate)}</td></tr>)}</tbody></table>
      <p>Validation diagnostics; refits and references use train only. Report ablation removes all report-derived columns. Unchanged small-sample scores do not imply the signals lack field value.</p>
      <pre>{JSON.stringify(r.experiment_4_signal_ablations, null, 2)}</pre>
      <h4>Training-label noise sensitivity</h4><p>Configured baseline noise and extra5% independent flips; not pristine data or exactly15% effective corruption.</p><pre>{JSON.stringify(users.noise_comparison, null, 2)}</pre>
    </div>
    <div className="glass-card"><h3>Demographic fairness audit · evaluation only</h3><p>No demographic features or group-specific authorization. Synthetic target checks do not establish universal fairness.</p>
      {['validation_diagnostic','held_out_canonical','held_out_shifted'].map((cohort) => {
        const audit = r.fairness_evaluation[cohort];
        return <section key={cohort}><h4>{cohort}</h4><p>Maximum model TPR gap {percent(audit.global_max_tpr_gap)} against assumed target {percent(audit.target_max_tpr_gap)} · {audit.satisfies_fairness_target == null ? 'Insufficient coverage' : audit.satisfies_fairness_target ? 'Within target on these slices' : 'Target missed'}.</p>
          <table className="data-table"><thead><tr><th>Slice / category</th><th>n / positive / negative</th><th>Method</th><th>TPR</th><th>FPR</th><th>Review rate</th></tr></thead><tbody>{Object.entries(audit.slices).flatMap(([column,categories]) => Object.entries(categories).flatMap(([category,value]) => ['rule_baseline','model'].map((method) => <tr key={column + category + method}><td>{column} / {category}</td><td>{value.count} / {value.positives} / {value.negatives}</td><td>{method}</td><td>{percent(value[method].tpr)}</td><td>{percent(value[method].fpr)}</td><td>{percent(value[method].review_rate)}</td></tr>)))}</tbody></table>
          {audit.unmet_targets.map((miss) => <p className="error-box" key={miss.slice}>Target missed: {miss.slice} · {percent(miss.observed_gap)}. {miss.proposed_mitigation}</p>)}
        </section>;
      })}
    </div>
  </>;
}
export default function MetricsPage({ initialData = null }) {
  const [data, setData] = useState(initialData);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    if (!initialData) api.getMetricsSummary().then((value) => { if (live) setData(value); }).catch((err) => { if (live) { setData(null); setError(err.message); } });
    return () => { live = false; };
  }, [initialData]);
  return <div><h2 className="card-title">Synthetic Evidence & Metrics</h2>
    {error && <p className="error-box" role="alert">Unavailable: {error}</p>}
    {data ? <EvidenceTables data={data} /> : <p>Unavailable — waiting for verified evaluation artifacts. No fallback metrics.</p>}
  </div>;
}
