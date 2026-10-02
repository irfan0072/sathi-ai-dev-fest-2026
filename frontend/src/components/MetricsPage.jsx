import { useState, useEffect } from 'react';
import { api } from '../api';

export default function MetricsPage() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adoptionSlider, setAdoptionSlider] = useState(50);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api.getMetricsSummary()
      .then((data) => {
        if (mounted) {
          setMetrics(data);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err?.message || 'Evaluation metrics unavailable (503)');
          setMetrics(null);
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const clf = metrics?.assisted_classifier || null;
  const agent = metrics?.agent_anomaly || null;
  const fairness = metrics?.fairness_slices || null;
  const impact = metrics?.impact_simulation || null;
  const shift = metrics?.distribution_shift || null;

  return (
    <div>
      <div className="card-title-row" style={{ marginBottom: '1.5rem' }}>
        <div>
          <h2 className="card-title">
            <span>📊</span> Evaluation Evidence & Impact Metrics
          </h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
            {loading
              ? 'Checking evaluation metric status...'
              : error
              ? 'Evaluation metrics currently unavailable (HTTP 503) — pending model evaluation artifact wiring.'
              : 'Evaluation metrics from model evaluation run.'}
          </p>
        </div>
        <span style={{ fontSize: '0.78rem', color: error ? '#fb7185' : '#f59e0b', fontWeight: 600, padding: '0.3rem 0.7rem', background: error ? 'rgba(244,63,94,0.1)' : 'rgba(245,158,11,0.1)', borderRadius: '999px', border: `1px solid ${error ? 'rgba(244,63,94,0.3)' : 'rgba(245,158,11,0.3)'}` }}>
          {loading ? '⏳ Loading...' : error ? '⚠ Metrics Unavailable (503)' : '✓ Metrics Connected'}
        </span>
      </div>

      {error && (
        <div style={{ background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.3)', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1.5rem', color: '#fb7185', fontSize: '0.85rem' }}>
          <strong>Notice:</strong> Endpoint returned 503 Service Unavailable. Measured evidence and benchmark results will appear once model evaluation artifacts are wired.
        </div>
      )}

      {/* Section 1: Classifier Head-to-Head */}
      <div className="glass-card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1.25rem' }}>
          1. Assisted-User Classifier: Rule Baseline vs Sathi LightGBM
        </h3>

        <div className="metrics-row">
          <div className="metric-stat-card">
            <div className="stat-label">PR-AUC (Clean Test)</div>
            <div className="stat-value" style={{ color: clf?.pr_auc != null ? '#10b981' : 'var(--text-dim)' }}>
              {clf?.pr_auc != null ? clf.pr_auc.toFixed(4) : 'Unavailable'}
            </div>
            <div className="stat-delta">
              {clf?.lift_pr_auc
                ? `vs Rule Baseline ${clf.baseline_rule_pr_auc?.toFixed(4)} ${clf.lift_pr_auc}`
                : 'Pending evaluation run'}
            </div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">ROC-AUC</div>
            <div className="stat-value" style={{ color: clf?.roc_auc != null ? '#06b6d4' : 'var(--text-dim)' }}>
              {clf?.roc_auc != null ? clf.roc_auc.toFixed(4) : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {clf?.roc_auc != null ? 'Discrimination ability on held-out test' : 'Pending evaluation run'}
            </div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">Brier Score (Calibration)</div>
            <div className="stat-value" style={{ color: clf?.brier_score != null ? '#a855f7' : 'var(--text-dim)' }}>
              {clf?.brier_score != null ? clf.brier_score.toFixed(4) : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {clf?.brier_score != null ? 'Lower is better' : 'Pending evaluation run'}
            </div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">Recall @ 80% Precision</div>
            <div className="stat-value" style={{ color: clf?.recall_at_80_precision != null ? '#f59e0b' : 'var(--text-dim)' }}>
              {clf?.recall_at_80_precision != null ? `${(clf.recall_at_80_precision * 100).toFixed(1)}%` : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {clf?.recall_at_80_precision != null ? 'At target precision threshold' : 'Pending evaluation run'}
            </div>
          </div>
        </div>

        {/* Bar Comparison Chart */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.5rem' }}>
          {[
            { label: 'PR-AUC', rule: clf?.baseline_rule_pr_auc, model: clf?.pr_auc, max: 1 },
            { label: 'ROC-AUC', rule: clf?.baseline_rule_roc_auc, model: clf?.roc_auc, max: 1 },
          ].map((stat) => (
            <div key={stat.label} style={{ padding: '0.75rem', background: 'rgba(15,23,42,0.5)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '0.5rem' }}>{stat.label}</div>
              {stat.model != null ? (
                <>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.3rem' }}>
                    <span style={{ fontSize: '0.7rem', width: '60px', color: 'var(--text-muted)' }}>Rule:</span>
                    <div style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: '3px', height: '14px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${((stat.rule || 0) / stat.max) * 100}%`, background: '#475569', borderRadius: '3px' }} />
                    </div>
                    <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: '#64748b', width: '50px', textAlign: 'right' }}>{stat.rule?.toFixed(3) ?? '—'}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.7rem', width: '60px', color: 'var(--text-muted)' }}>Sathi:</span>
                    <div style={{ flex: 1, background: 'rgba(255,255,255,0.06)', borderRadius: '3px', height: '14px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${((stat.model || 0) / stat.max) * 100}%`, background: 'linear-gradient(90deg, #10b981, #06b6d4)', borderRadius: '3px' }} />
                    </div>
                    <span style={{ fontSize: '0.72rem', fontFamily: 'var(--font-mono)', color: '#10b981', width: '50px', textAlign: 'right' }}>{stat.model?.toFixed(3)}</span>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center', padding: '0.6rem' }}>
                  Comparison unavailable — awaiting benchmark artifacts
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Section 2: Agent Anomaly */}
      <div className="glass-card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1.25rem' }}>
          2. Agent Anomaly Ensemble Evaluation
        </h3>

        <div className="metrics-row">
          <div className="metric-stat-card">
            <div className="stat-label">Precision@R</div>
            <div className="stat-value" style={{ color: agent?.precision_at_k != null ? '#10b981' : 'var(--text-dim)' }}>
              {agent?.precision_at_k != null ? `${(agent.precision_at_k * 100).toFixed(0)}%` : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {agent?.precision_at_k != null ? 'Top rank detection' : 'Pending evaluation run'}
            </div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">Recall on Skimmers</div>
            <div className="stat-value" style={{ color: agent?.recall_skimmers != null ? '#10b981' : 'var(--text-dim)' }}>
              {agent?.recall_skimmers != null ? `${(agent.recall_skimmers * 100).toFixed(0)}%` : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {agent?.recall_skimmers != null ? 'Detection rate' : 'Pending evaluation run'}
            </div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">False-Flag (Honest High-Vol)</div>
            <div className="stat-value" style={{ color: agent?.false_flag_rate_honest_high_volume != null ? '#10b981' : 'var(--text-dim)' }}>
              {agent?.false_flag_rate_honest_high_volume != null ? `${(agent.false_flag_rate_honest_high_volume * 100).toFixed(1)}%` : 'Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              {agent?.false_flag_rate_honest_high_volume != null ? 'Alert rate on honest agents' : 'Pending evaluation run'}
            </div>
          </div>
        </div>

        <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: '0.75rem', padding: '0.6rem', background: 'rgba(255,255,255,0.02)', borderRadius: '6px' }}>
          Anomaly detection evaluation metrics unavailable until test execution is wired.
        </div>
      </div>

      {/* Section 3: Adoption Sensitivity Slider */}
      <div className="glass-card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '0.75rem' }}>
          3. Adoption Sensitivity — Simulated Skimming Loss Prevented
        </h3>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginBottom: '1rem' }}>
          {impact?.total_skimming_loss_test_bdt != null
            ? `Total skimming loss simulated in test set: ৳ ${impact.total_skimming_loss_test_bdt?.toLocaleString()} BDT across ${impact.total_skimmer_actions} skimmer actions.`
            : 'Simulated loss baseline unavailable until model evaluation artifacts are connected.'}
        </p>

        <div className="slider-container">
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
            <label htmlFor="adoption-slider">Sathi Mandate Adoption Rate</label>
            <strong style={{ color: '#10b981', fontFamily: 'var(--font-display)', fontSize: '1.2rem' }}>{adoptionSlider}%</strong>
          </div>
          <input
            id="adoption-slider"
            type="range"
            className="range-slider"
            min="0"
            max="100"
            value={adoptionSlider}
            onChange={(e) => setAdoptionSlider(Number(e.target.value))}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
            <span>0% (No Adoption)</span>
            <span>50% (Moderate)</span>
            <span>100% (Full Roll-Out)</span>
          </div>
        </div>

        <div style={{ textAlign: 'center', padding: '1.5rem', background: 'linear-gradient(135deg, rgba(16,185,129,0.1), rgba(6,182,212,0.08))', borderRadius: '12px', border: '1px solid rgba(16,185,129,0.25)', marginTop: '0.75rem' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>Simulated Loss Prevented @ {adoptionSlider}% Adoption</div>
          <div style={{ fontSize: '2.5rem', fontFamily: 'var(--font-display)', fontWeight: 800, color: impact?.total_skimming_loss_test_bdt ? '#34d399' : 'var(--text-dim)', marginTop: '0.25rem' }}>
            {impact?.total_skimming_loss_test_bdt != null
              ? `৳ ${Math.round(impact.total_skimming_loss_test_bdt * (adoptionSlider / 100)).toLocaleString()} BDT`
              : 'Unavailable'}
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            {impact?.total_skimming_loss_test_bdt != null
              ? `${adoptionSlider}% of cashouts protected without PIN sharing`
              : 'Simulation unavailable — no baseline metrics connected'}
          </div>
        </div>
      </div>

      {/* Section 4: Demographic Fairness */}
      <div className="glass-card" style={{ marginBottom: '1.5rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1.25rem' }}>
          4. Demographic Fairness Audit
        </h3>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', padding: '0.75rem 1rem', background: fairness?.compliant ? 'rgba(16,185,129,0.1)' : 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
          <div>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: fairness?.compliant ? '#34d399' : 'var(--text-dim)' }}>
              {fairness?.compliant != null
                ? (fairness.compliant ? '✓ Fairness Compliant' : '⚠ Fairness Threshold Exceeded')
                : 'Fairness Audit: Unavailable'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
              {fairness?.target_tpr_gap != null
                ? `Maximum TPR gap target: ≤ ${((fairness.target_tpr_gap) * 100).toFixed(0)}%`
                : 'Pending evaluation run'}
            </div>
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', fontWeight: 700, color: 'var(--text-dim)' }}>
            {fairness?.max_tpr_gap != null ? `${((fairness.max_tpr_gap) * 100).toFixed(1)}% max gap` : 'Unavailable'}
          </div>
        </div>

        <table className="data-table">
          <thead>
            <tr>
              <th>Demographic Slice</th>
              <th>Max TPR Gap</th>
              <th>Status</th>
              <th>Interpretation</th>
            </tr>
          </thead>
          <tbody>
            {[
              { slice: 'Gender', gap: fairness?.disparities?.gender?.gap },
              { slice: 'Age Band', gap: fairness?.disparities?.age_band?.gap },
              { slice: 'Region', gap: fairness?.disparities?.region?.gap },
              { slice: 'Urban / Rural', gap: fairness?.disparities?.urban_rural?.gap },
            ].map((row) => (
              <tr key={row.slice}>
                <td style={{ fontWeight: 600 }}>{row.slice}</td>
                <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                  {row.gap != null ? `${((row.gap) * 100).toFixed(1)}%` : 'Unavailable'}
                </td>
                <td>
                  <span className="badge badge-med">
                    {row.gap != null ? (row.gap <= 0.1 ? 'PASS' : 'FLAGGED') : 'UNAVAILABLE'}
                  </span>
                </td>
                <td style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>
                  {row.gap != null ? 'Evaluated against parity target' : 'Awaiting evaluation results'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ marginTop: '0.75rem', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
          Demographic attributes are evaluation-only slices and are never used as model inputs.
        </div>
      </div>

      {/* Section 5: Distribution Shift Robustness */}
      <div className="glass-card">
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1.25rem' }}>
          5. Robustness Under Distribution Shift
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          <div className="metric-stat-card">
            <div className="stat-label">Canonical Test PR-AUC</div>
            <div className="stat-value">{shift?.canonical_test_pr_auc != null ? shift.canonical_test_pr_auc.toFixed(4) : 'Unavailable'}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Pending evaluation run</div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">Shifted Test PR-AUC</div>
            <div className="stat-value">{shift?.shifted_test_pr_auc != null ? shift.shifted_test_pr_auc.toFixed(4) : 'Unavailable'}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>Pending evaluation run</div>
          </div>

          <div className="metric-stat-card">
            <div className="stat-label">PR-AUC Delta</div>
            <div className="stat-value">{shift?.delta ?? 'Unavailable'}</div>
            <div className="stat-delta">
              {shift?.robust != null
                ? (shift.robust ? '✓ Robust — no degradation under shift' : '⚠ Performance degraded')
                : 'Status: Unavailable'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
