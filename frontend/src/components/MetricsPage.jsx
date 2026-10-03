import { useState, useEffect } from 'react';
import { api } from '../api';

const fmt = (value, digits = 4) => value == null ? 'Undefined' : Number(value).toFixed(digits);
const percent = (value) => value == null ? 'Undefined' : `${(value * 100).toFixed(2)}%`;

function Table({ head, children }) {
  return (
    <div className="overflow-x-auto rounded-box border border-base-300">
      <table className="table table-sm table-zebra">
        <thead className="bg-base-200"><tr>{head.map((label) => <th key={label}>{label}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, note }) {
  return (
    <div className="panel">
      <div className="panel-body gap-1 p-4">
        <span className="muted">{label}</span>
        <span className="font-mono text-2xl font-bold">{value}</span>
        <span className="muted">{note}</span>
      </div>
    </div>
  );
}

function Tab({ label, checked = false, children }) {
  return <>
    <input type="radio" name="evidence-tabs" role="tab" className="tab whitespace-nowrap" aria-label={label} defaultChecked={checked} />
    <div role="tabpanel" className="tab-content pt-4">
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  </>;
}

export function EvidenceTables({ data }) {
  const [adoption, setAdoption] = useState('adoption_50pct');
  const r = data.results;
  const users = r.experiment_1_assisted_detection;
  const shifted = r.experiment_6_distribution_shift;
  const impact = r.experiment_5_adoption_sensitivity;
  const scenario = impact.scenarios[adoption];
  const userRows = [];
  for (const cohort of ['validation_diagnostic', 'held_out_test']) {
    const item = users[cohort];
    for (const method of ['rule_baseline', 'assisted_classifier']) userRows.push({ cohort, method, metrics: item[method], n: item.denominators });
  }
  userRows.push({ cohort: 'held_out_shifted', method: 'rule_baseline', metrics: shifted.assisted_classifier.rule_baseline_shifted });
  userRows.push({ cohort: 'held_out_shifted', method: 'assisted_classifier', metrics: shifted.assisted_classifier.shifted_test });
  const heldOutAgents = r.experiment_2_agent_anomaly.held_out_test;

  return <>
    <div className="grid gap-3 sm:grid-cols-3">
      <Stat label="Held-out assisted PR-AUC" value={fmt(users.held_out_test.assisted_classifier.pr_auc)} note={`rules ${fmt(users.held_out_test.rule_baseline.pr_auc)}`} />
      <Stat label="Held-out agent precision@K" value={fmt(heldOutAgents.combined_ensemble.precision_at_k)} note="combined ensemble" />
      <Stat label="Fairness target (held-out)" value={r.fairness_evaluation.held_out_canonical.satisfies_fairness_target == null ? 'n/a' : r.fairness_evaluation.held_out_canonical.satisfies_fairness_target ? 'Within' : 'Missed'} note={`max TPR gap ${percent(r.fairness_evaluation.held_out_canonical.global_max_tpr_gap)}`} />
    </div>

    <p className="muted">Verified frozen run {data.provenance.final_run_timestamp} · source {data.provenance.git_revision.slice(0, 8)} · seeds {Object.entries(data.seeds).map(([k, v]) => `${k}=${v}`).join(', ')}. {data.provenance.window_days}-day offline window · snapshot {data.provenance.as_of}. Synthetic future dates are simulation coordinates, not live events.</p>

    <div className="panel">
      <div className="panel-body">
        <div role="tablist" className="tabs tabs-border flex-nowrap overflow-x-auto">
          <Tab label="Assisted detection" checked>
            <h3 className="font-semibold">Assisted behavior: rules and LightGBM</h3>
            <p className="muted">Validation uses the calibration cohort and is diagnostic. Held-out/shifted cohorts are separate estimates. PR-AUC is trapezoidal area, not average precision. Undefined means not reported or insufficient coverage.</p>
            <Table head={['Cohort', 'Method', 'PR-AUC', 'Precision', 'Recall', 'Brier', 'Recall at ≥80% precision', 'n / positives']}>
              {userRows.map((row) => <tr key={row.cohort + row.method}><td>{row.cohort}</td><td>{row.method}</td><td className="font-mono">{fmt(row.metrics.pr_auc)}</td><td className="font-mono">{fmt(row.metrics.precision ?? row.metrics.precision_at_threshold)}</td><td className="font-mono">{fmt(row.metrics.recall ?? row.metrics.recall_at_threshold)}</td><td className="font-mono">{fmt(row.metrics.brier_score)}</td><td className="font-mono">{fmt(row.metrics.recall_at_80p_precision ?? row.metrics.operating_recall)}</td><td>{row.n ? `${row.n.total_users} / ${row.n.positives_assisted}` : 'See shifted fairness denominators'}</td></tr>)}
            </Table>
          </Tab>

          <Tab label="Agent review">
            <h3 className="font-semibold">Agent review: fixed top-K and high-risk threshold</h3>
            <p className="muted">Ranking precision@K differs from threshold flags. Small injected-skimmer and honest high-volume samples limit conclusions.</p>
            <Table head={['Cohort / method', 'Agents / skimmers / honest HV', 'K', 'Precision@K', 'Skimmer recall', 'Honest HV false flags']}>
              {['validation', 'held_out_test', 'shifted_test'].map((cohort) => {
                const item = cohort === 'shifted_test' ? shifted.agent_detector.shifted_test : r.experiment_2_agent_anomaly[cohort];
                return ['baseline_rule', 'peer_robust_zscore', 'isolation_forest', 'combined_ensemble'].map((method) => <tr key={cohort + method}><td>{cohort} / {method}</td><td>{item.denominators.total_agents} / {item.denominators.total_skimmers} / {item.denominators.total_honest_high_volume}</td><td>{item.review_top_k_clipped ?? item.denominators.review_top_k_clipped}</td><td className="font-mono">{fmt(item[method].precision_at_k)}</td><td className="font-mono">{percent(item[method].recall_on_skimmers)}</td><td className="font-mono">{percent(item[method].false_flag_rate_honest_high_volume)}</td></tr>);
              })}
            </Table>
          </Tab>

          <Tab label="Adoption impact">
            <h3 className="font-semibold">Adoption sensitivity · idealized ASSUMPTIONS</h3>
            <p className="muted">{impact.disclaimer}</p>
            <p className="text-sm">Eligible loss ৳{fmt(impact.eligible_assisted_skimming_loss_bdt, 2)} BDT from {impact.eligible_assisted_skimmer_actions} eligible skimmer actions; total injected loss ৳{fmt(impact.total_injected_skimming_loss_bdt, 2)} BDT from {impact.total_test_skimmer_actions} actions. Eligible assisted cash-outs: {impact.total_eligible_assisted_cashouts}.</p>
            <div>
              <span className="mb-1 block text-sm">Saved adoption scenario</span>
              <div className="join">
                {Object.entries(impact.scenarios).map(([key, value]) => (
                  <button key={key} className={`btn btn-sm join-item ${adoption === key ? 'btn-primary' : ''}`} aria-pressed={adoption === key} onClick={() => setAdoption(key)}>{percent(value.adoption_rate)}</button>
                ))}
              </div>
            </div>
            {scenario && <div className="alert alert-success alert-soft text-sm">Idealized eligible loss prevented: ৳{fmt(scenario.loss_prevented_bdt, 2)} BDT · {scenario.pct_eligible_assisted_loss_prevented}% eligible loss · {scenario.pct_total_injected_loss_prevented}% total injected loss.</div>}
            <p className="muted">Perfect compliance is assumed. Amount confirmation cannot prove physical cash delivery. This is not measured field benefit.</p>
          </Tab>

          <Tab label="Robustness">
            <h3 className="font-semibold">Skimming profiles and validation ablations</h3>
            <Table head={['Injected intensity', 'Skimmers / honest', 'Detection', 'Honest false flags']}>
              {Object.entries(r.experiment_3_skimming_sweep).map(([key, value]) => <tr key={key}><td>{key}</td><td>{value.skimmer_count} / {value.honest_agent_count}</td><td className="font-mono">{percent(value.skimmer_detection_rate)}</td><td className="font-mono">{percent(value.honest_false_flag_rate)}</td></tr>)}
            </Table>
            <p className="muted">Validation diagnostics; refits and references use train only. Report ablation removes all report-derived columns. Unchanged small-sample scores do not imply the signals lack field value.</p>
            <pre className="json-block">{JSON.stringify(r.experiment_4_signal_ablations, null, 2)}</pre>
            <h4 className="font-semibold">Training-label noise sensitivity</h4>
            <p className="muted">Configured baseline noise and extra5% independent flips; not pristine data or exactly15% effective corruption.</p>
            <pre className="json-block">{JSON.stringify(users.noise_comparison, null, 2)}</pre>
          </Tab>

          <Tab label="Fairness audit">
            <h3 className="font-semibold">Demographic fairness audit · evaluation only</h3>
            <p className="muted">No demographic features or group-specific authorization. Synthetic target checks do not establish universal fairness.</p>
            {['validation_diagnostic', 'held_out_canonical', 'held_out_shifted'].map((cohort) => {
              const audit = r.fairness_evaluation[cohort];
              return (
                <section key={cohort} className="flex flex-col gap-2">
                  <h4 className="font-mono text-sm font-semibold">{cohort}</h4>
                  <p className="text-sm">Maximum model TPR gap {percent(audit.global_max_tpr_gap)} against assumed target {percent(audit.target_max_tpr_gap)} · {audit.satisfies_fairness_target == null ? 'Insufficient coverage' : audit.satisfies_fairness_target ? 'Within target on these slices' : 'Target missed'}.</p>
                  <Table head={['Slice / category', 'n / positive / negative', 'Method', 'TPR', 'FPR', 'Review rate']}>
                    {Object.entries(audit.slices).flatMap(([column, categories]) => Object.entries(categories).flatMap(([category, value]) => ['rule_baseline', 'model'].map((method) => <tr key={column + category + method}><td>{column} / {category}</td><td>{value.count} / {value.positives} / {value.negatives}</td><td>{method}</td><td className="font-mono">{percent(value[method].tpr)}</td><td className="font-mono">{percent(value[method].fpr)}</td><td className="font-mono">{percent(value[method].review_rate)}</td></tr>)))}
                  </Table>
                  {audit.unmet_targets.map((miss) => <div className="alert alert-warning alert-soft text-sm" key={miss.slice}>Target missed: {miss.slice} · {percent(miss.observed_gap)}. {miss.proposed_mitigation}</div>)}
                </section>
              );
            })}
          </Tab>
        </div>
      </div>
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
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">Synthetic Evidence & Metrics</h2>
        <p className="page-lead">Saved offline evaluation on synthetic data. Every figure comes from the verified frozen run.</p>
      </div>
      {error && <div className="alert alert-error alert-soft text-sm" role="alert">Unavailable: {error}</div>}
      {data ? <EvidenceTables data={data} /> : <p className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-dots loading-sm" />Unavailable — waiting for verified evaluation artifacts. No fallback metrics.</p>}
    </div>
  );
}
