import { useState, useEffect } from 'react';
import { api } from '../api';

const fmt = (value, digits = 4) =>
  value == null ? 'Undefined' : Number(value).toFixed(digits);
const percent = (value) =>
  value == null ? 'Undefined' : `${(value * 100).toFixed(2)}%`;

function Table({ head, children, caption }) {
  return (
    <div className="overflow-x-auto rounded-box border border-base-300 bg-base-100">
      {caption && (
        <div className="border-b border-base-300 bg-base-200/60 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-base-content/70">
          {caption}
        </div>
      )}
      <table className="table table-sm table-zebra">
        <thead className="bg-base-200/80">
          <tr>
            {head.map((label) => (
              <th key={label} className="text-xs font-semibold uppercase tracking-wider text-base-content/70">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, note, tone = 'neutral' }) {
  const toneClass = {
    neutral: 'hover:border-primary/40',
    good: 'border-success/40 hover:border-success',
    warn: 'border-warning/40 hover:border-warning',
    bad: 'border-error/40 hover:border-error',
  }[tone] || 'hover:border-primary/40';
  return (
    <div className={`panel transition-colors shadow-sm ${toneClass}`}>
      <div className="panel-body gap-1.5 p-4">
        <span className="muted">{label}</span>
        <span className="font-mono text-2xl font-bold leading-tight tracking-tight">
          {value}
        </span>
        {note && <span className="muted">{note}</span>}
      </div>
    </div>
  );
}

function Pill({ children, tone = 'neutral' }) {
  const tones = {
    neutral: 'badge-ghost',
    good: 'badge-success',
    warn: 'badge-warning',
    bad: 'badge-error',
    info: 'badge-info',
  };
  return <span className={`badge badge-sm ${tones[tone] || 'badge-ghost'}`}>{children}</span>;
}

function Section({ title, subtitle, children, action }) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-end justify-between gap-2 border-b border-base-300 pb-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{title}</h3>
          {subtitle && <p className="muted mt-0.5">{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function JsonBlock({ data }) {
  return (
    <pre className="json-block border border-base-300">{JSON.stringify(data, null, 2)}</pre>
  );
}

const TABS = [
  { id: 'detection', label: 'Assisted detection', icon: 'radar' },
  { id: 'agents', label: 'Agent review', icon: 'chart' },
  { id: 'adoption', label: 'Adoption impact', icon: 'users' },
  { id: 'robustness', label: 'Robustness', icon: 'shield' },
  { id: 'fairness', label: 'Fairness audit', icon: 'info' },
];

function TabNav({ active, onChange }) {
  return (
    <div
      role="tablist"
      aria-label="Evidence sections"
      className="flex flex-wrap gap-1 rounded-box border border-base-300 bg-base-100 p-1 shadow-sm"
    >
      {TABS.map((tab) => {
        const selected = active === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`tab-panel-${tab.id}`}
            id={`tab-${tab.id}`}
            onClick={() => onChange(tab.id)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition focus-ring ${
              selected
                ? 'bg-primary text-primary-content shadow-sm'
                : 'text-base-content/70 hover:bg-base-200 hover:text-base-content'
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

function DetectionTab({ data }) {
  const r = data.results;
  const users = r.experiment_1_assisted_detection;
  const shifted = r.experiment_6_distribution_shift;
  const userRows = [];
  for (const cohort of ['validation_diagnostic', 'held_out_test']) {
    const item = users[cohort];
    for (const method of ['rule_baseline', 'assisted_classifier']) {
      userRows.push({ cohort, method, metrics: item[method], n: item.denominators });
    }
  }
  userRows.push({
    cohort: 'held_out_shifted',
    method: 'rule_baseline',
    metrics: shifted.assisted_classifier.rule_baseline_shifted,
  });
  userRows.push({
    cohort: 'held_out_shifted',
    method: 'assisted_classifier',
    metrics: shifted.assisted_classifier.shifted_test,
  });

  return (
    <Section
      title="Assisted behavior: rules vs LightGBM"
      subtitle="Validation uses the calibration cohort and is diagnostic. Held-out and shifted cohorts are separate estimates. PR-AUC is trapezoidal area, not average precision. Undefined means not reported or insufficient coverage."
    >
      <Table head={['Cohort', 'Method', 'PR-AUC', 'Precision', 'Recall', 'Brier', 'Recall @ ≥80% precision', 'n / positives']}>
        {userRows.map((row) => (
          <tr key={row.cohort + row.method}>
            <td>
              <span className="font-mono text-xs">{row.cohort}</span>
            </td>
            <td>
              <Pill tone={row.method === 'assisted_classifier' ? 'info' : 'neutral'}>
                {row.method.replace('_', ' ')}
              </Pill>
            </td>
            <td className="font-mono">{fmt(row.metrics.pr_auc)}</td>
            <td className="font-mono">
              {fmt(row.metrics.precision ?? row.metrics.precision_at_threshold)}
            </td>
            <td className="font-mono">
              {fmt(row.metrics.recall ?? row.metrics.recall_at_threshold)}
            </td>
            <td className="font-mono">{fmt(row.metrics.brier_score)}</td>
            <td className="font-mono">
              {fmt(row.metrics.recall_at_80p_precision ?? row.metrics.operating_recall)}
            </td>
            <td>
              {row.n ? (
                <span className="font-mono text-xs">
                  {row.n.total_users} / {row.n.positives_assisted}
                </span>
              ) : (
                <span className="muted text-xs">See shifted fairness denominators</span>
              )}
            </td>
          </tr>
        ))}
      </Table>
    </Section>
  );
}

function AgentsTab({ data }) {
  const r = data.results;
  const shifted = r.experiment_6_distribution_shift;
  const methods = ['baseline_rule', 'peer_robust_zscore', 'isolation_forest', 'combined_ensemble'];

  return (
    <Section
      title="Agent review: fixed top-K vs high-risk threshold"
      subtitle="Ranking precision@K differs from threshold flags. Small injected-skimmer and honest high-volume samples limit conclusions."
    >
      <div className="grid gap-3 lg:grid-cols-3">
        {['validation', 'held_out_test', 'shifted_test'].map((cohort) => {
          const item =
            cohort === 'shifted_test'
              ? shifted.agent_detector.shifted_test
              : r.experiment_2_agent_anomaly[cohort];
          return (
            <Table
              key={cohort}
              caption={`${cohort} · ${
                item.denominators.total_agents
              } agents · ${item.denominators.total_skimmers} skimmers · ${
                item.denominators.total_honest_high_volume
              } honest HV`}
              head={['Method', 'Precision@K', 'Skimmer recall', 'Honest HV false flags']}
            >
              {methods.map((method) => (
                <tr key={cohort + method}>
                  <td>
                    <Pill tone={method === 'combined_ensemble' ? 'info' : 'neutral'}>
                      {method.replace(/_/g, ' ')}
                    </Pill>
                  </td>
                  <td className="font-mono">{fmt(item[method].precision_at_k)}</td>
                  <td className="font-mono">
                    {percent(item[method].recall_on_skimmers)}
                  </td>
                  <td className="font-mono">
                    {percent(item[method].false_flag_rate_honest_high_volume)}
                  </td>
                </tr>
              ))}
            </Table>
          );
        })}
      </div>
      <p className="muted">
        K = {r.experiment_2_agent_anomaly.held_out_test.review_top_k_clipped}
      </p>
    </Section>
  );
}

function AdoptionTab({ data }) {
  const impact = data.results.experiment_5_adoption_sensitivity;
  const [adoption, setAdoption] = useState('adoption_50pct');
  const scenario = impact.scenarios[adoption];

  return (
    <Section
      title="Adoption sensitivity · idealized ASSUMPTIONS"
      subtitle={impact.disclaimer}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Eligible loss pool"
          value={`৳${fmt(impact.eligible_assisted_skimming_loss_bdt, 2)}`}
          tone="bad"
        />
        <Stat
          label="Eligible skimmer actions"
          value={impact.eligible_assisted_skimmer_actions.toLocaleString()}
          tone="warn"
        />
        <Stat
          label="Eligible assisted cash-outs"
          value={impact.total_eligible_assisted_cashouts.toLocaleString()}
          tone="neutral"
        />
      </div>

      <div className="panel shadow-sm">
        <div className="panel-body gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h4 className="text-sm font-semibold">Saved adoption scenario</h4>
              <p className="muted mt-0.5">
                Pick the share of eligible users that adopt Sathi to compare prevented loss.
              </p>
            </div>
            <div className="join">
              {Object.entries(impact.scenarios).map(([key, value]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={adoption === key}
                  onClick={() => setAdoption(key)}
                  className={`btn btn-sm join-item focus-ring ${
                    adoption === key ? 'btn-primary' : 'btn-ghost border-base-300'
                  }`}
                >
                  {percent(value.adoption_rate)}
                </button>
              ))}
            </div>
          </div>

          {scenario && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat
                label="Idealized eligible loss prevented"
                value={`৳${fmt(scenario.loss_prevented_bdt, 2)}`}
                tone="good"
              />
              <Stat
                label="% of eligible loss prevented"
                value={`${scenario.pct_eligible_assisted_loss_prevented}%`}
                tone="good"
              />
              <Stat
                label="% of total injected loss prevented"
                value={`${scenario.pct_total_injected_loss_prevented}%`}
                tone="good"
              />
            </div>
          )}

          <div className="alert alert-info alert-soft text-sm">
            <span>
              Perfect compliance is assumed. Amount confirmation cannot prove physical cash delivery. This is
              not measured field benefit.
            </span>
          </div>
        </div>
      </div>
    </Section>
  );
}

function RobustnessTab({ data }) {
  const r = data.results;
  const users = r.experiment_1_assisted_detection;

  return (
    <Section
      title="Skimming profiles and validation ablations"
      subtitle="Validation diagnostics; refits and references use train only. Report ablation removes all report-derived columns."
    >
      <Table head={['Injected intensity', 'Skimmers / honest', 'Detection', 'Honest false flags']}>
        {Object.entries(r.experiment_3_skimming_sweep).map(([key, value]) => (
          <tr key={key}>
            <td>
              <Pill tone="info">{key}</Pill>
            </td>
            <td className="font-mono">
              {value.skimmer_count} / {value.honest_agent_count}
            </td>
            <td className="font-mono">{percent(value.skimmer_detection_rate)}</td>
            <td className="font-mono">{percent(value.honest_false_flag_rate)}</td>
          </tr>
        ))}
      </Table>

      <p className="muted">
        Unchanged small-sample scores do not imply the signals lack field value.
      </p>

      <details className="collapse collapse-arrow border border-base-300 bg-base-100">
        <summary className="collapse-title text-sm font-medium">Signal ablation summary</summary>
        <div className="collapse-content">
          <JsonBlock data={r.experiment_4_signal_ablations} />
        </div>
      </details>

      <Section
        title="Training-label noise sensitivity"
        subtitle="Configured baseline noise and extra5% independent flips; not pristine data or exactly15% effective corruption."
      >
        <JsonBlock data={users.noise_comparison} />
      </Section>
    </Section>
  );
}

function FairnessTab({ data }) {
  const r = data.results;
  const cohorts = ['validation_diagnostic', 'held_out_canonical', 'held_out_shifted'];

  return (
    <Section
      title="Demographic fairness audit · evaluation only"
      subtitle="No demographic features or group-specific authorization. Synthetic target checks do not establish universal fairness."
    >
      {cohorts.map((cohort) => {
        const audit = r.fairness_evaluation[cohort];
        const within =
          audit.satisfies_fairness_target == null
            ? 'warn'
            : audit.satisfies_fairness_target
              ? 'good'
              : 'bad';
        const withinLabel =
          audit.satisfies_fairness_target == null
            ? 'Insufficient coverage'
            : audit.satisfies_fairness_target
              ? 'Within target'
              : 'Target missed';

        return (
          <div key={cohort} className="panel shadow-sm">
            <div className="panel-body gap-3">
              <header className="flex flex-wrap items-center justify-between gap-2 border-b border-base-300 pb-2">
                <h4 className="font-mono text-sm font-semibold">{cohort}</h4>
                <Pill tone={within}>{withinLabel}</Pill>
              </header>

              <p className="text-sm text-base-content/80">
                Maximum model TPR gap{' '}
                <strong>{percent(audit.global_max_tpr_gap)}</strong> against assumed target{' '}
                <strong>{percent(audit.target_max_tpr_gap)}</strong>.
              </p>

              <Table
                head={['Slice / category', 'n / pos / neg', 'Method', 'TPR', 'FPR', 'Review rate']}
              >
                {Object.entries(audit.slices).flatMap(([column, categories]) =>
                  Object.entries(categories).flatMap(([category, value]) =>
                    ['rule_baseline', 'model'].map((method) => (
                      <tr key={column + category + method}>
                        <td>
                          <span className="font-mono text-xs">{column} / {category}</span>
                        </td>
                        <td className="font-mono text-xs">
                          {value.count} / {value.positives} / {value.negatives}
                        </td>
                        <td>
                          <Pill tone={method === 'model' ? 'info' : 'neutral'}>
                            {method.replace('_', ' ')}
                          </Pill>
                        </td>
                        <td className="font-mono">{percent(value[method].tpr)}</td>
                        <td className="font-mono">{percent(value[method].fpr)}</td>
                        <td className="font-mono">{percent(value[method].review_rate)}</td>
                      </tr>
                    ))
                  )
                )}
              </Table>

              {audit.unmet_targets && audit.unmet_targets.length > 0 && (
                <div className="flex flex-col gap-2">
                  {audit.unmet_targets.map((miss) => (
                    <div
                      className="alert alert-warning alert-soft text-sm"
                      key={miss.slice}
                    >
                      <span>
                        <strong>Target missed:</strong> {miss.slice} ·{' '}
                        {percent(miss.observed_gap)}. {miss.proposed_mitigation}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </Section>
  );
}

export function EvidenceTables({ data }) {
  const [tab, setTab] = useState('detection');
  const r = data.results;
  const users = r.experiment_1_assisted_detection;
  const heldOutAgents = r.experiment_2_agent_anomaly.held_out_test;
  const fairness = r.fairness_evaluation.held_out_canonical;

  const fairnessTone =
    fairness.satisfies_fairness_target == null
      ? 'warn'
      : fairness.satisfies_fairness_target
        ? 'good'
        : 'bad';
  const fairnessLabel =
    fairness.satisfies_fairness_target == null
      ? 'n/a'
      : fairness.satisfies_fairness_target
        ? 'Within'
        : 'Missed';

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Held-out assisted PR-AUC"
          value={fmt(users.held_out_test.assisted_classifier.pr_auc)}
          note={`rules ${fmt(users.held_out_test.rule_baseline.pr_auc)}`}
        />
        <Stat
          label="Held-out agent precision@K"
          value={fmt(heldOutAgents.combined_ensemble.precision_at_k)}
          note="combined ensemble"
        />
        <Stat
          label="Fairness target (held-out)"
          value={fairnessLabel}
          note={`max TPR gap ${percent(fairness.global_max_tpr_gap)}`}
          tone={fairnessTone}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-box border border-base-300 bg-base-200/40 px-3 py-2 text-xs text-base-content/70">
        <Pill tone="info">Verified frozen</Pill>
        <span>
          Run {data.provenance.final_run_timestamp} · source{' '}
          <span className="font-mono">
            {data.provenance.git_revision.slice(0, 8)}
          </span>
          {' · seeds '}
          {Object.entries(data.seeds)
            .map(([k, v]) => `${k}=${v}`)
            .join(', ')}
        </span>
        <span className="hidden sm:inline">
          · {data.provenance.window_days}-day offline window · snapshot{' '}
          {data.provenance.as_of}
        </span>
        <span className="hidden md:inline">
          · Synthetic future dates are simulation coordinates, not live events.
        </span>
      </div>

      <TabNav active={tab} onChange={setTab} />

      <div
        role="tabpanel"
        id={`tab-panel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className="panel shadow-sm"
      >
        <div className="panel-body">
          {tab === 'detection' && <DetectionTab data={data} />}
          {tab === 'agents' && <AgentsTab data={data} />}
          {tab === 'adoption' && <AdoptionTab data={data} />}
          {tab === 'robustness' && <RobustnessTab data={data} />}
          {tab === 'fairness' && <FairnessTab data={data} />}
        </div>
      </div>
    </div>
  );
}

export default function MetricsPage({ initialData = null }) {
  const [data, setData] = useState(initialData);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    if (!initialData)
      api
        .getMetricsSummary()
        .then((value) => {
          if (live) setData(value);
        })
        .catch((err) => {
          if (live) {
            setData(null);
            setError(err.message);
          }
        });
    return () => {
      live = false;
    };
  }, [initialData]);
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="page-title">How well the AI works</h2>
          <p className="page-lead mt-1">
            Offline test results of the AI models on a held-out test set, for judges and technical reviewers. These are fixed on purpose so anyone can reproduce them; the same trained models score the live data on the Agent risk and Customers pages.
          </p>
        </div>
      </div>
      {error && (
        <div className="alert alert-error alert-soft text-sm" role="alert">
          Unavailable: {error}
        </div>
      )}
      {data ? (
        <EvidenceTables data={data} />
      ) : (
        <div className="panel shadow-sm">
          <div className="panel-body items-center justify-center py-10 text-center">
            <span className="loading loading-dots loading-md text-primary" />
            <p className="text-sm text-base-content/70">
              Unavailable — waiting for verified evaluation artifacts. No fallback metrics.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}