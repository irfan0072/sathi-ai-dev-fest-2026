// Tiny saved-output contract fixture, never a final evaluation cohort.
const rates = { pr_auc: .7312, precision: .81, recall: .62, brier_score: .19, recall_at_80p_precision: .6 };
const user = { assisted_classifier: rates, rule_baseline: { ...rates, pr_auc: .5123 }, denominators: { total_users: 10, positives_assisted: 4 } };
const method = { precision_at_k: .2, recall_on_skimmers: .5, false_flag_rate_honest_high_volume: .75 };
const agents = { denominators: { total_agents: 8, total_skimmers: 2, total_honest_high_volume: 4, review_top_k_clipped: 5 }, review_top_k_clipped: 5, baseline_rule: method, peer_robust_zscore: method, isolation_forest: method, combined_ensemble: method };
const fairness = { global_max_tpr_gap: .12, target_max_tpr_gap: .1, satisfies_fairness_target: false,
  slices: { gender: { fixture: { count: 10, positives: 4, negatives: 6, rule_baseline: {tpr: null, fpr: .1}, model: {tpr: .62, fpr: .08, review_rate: .3} } } },
  unmet_targets: [{slice: 'gender', observed_gap: .12, proposed_mitigation: 'Audit representation; preserve demographics as evaluation-only.'}] };
export const evidenceFixture = { provenance: { final_run_timestamp: 'fixture-date', git_revision: '0123456789', window_days: 30, as_of: 'fixture-snapshot' }, seeds: { train: 42, validation: 4242, test: 2026 },
  results: { experiment_1_assisted_detection: { validation_diagnostic: user, held_out_test: user, noise_comparison: {} },
    experiment_2_agent_anomaly: { validation: agents, held_out_test: agents },
    experiment_6_distribution_shift: { assisted_classifier: {rule_baseline_shifted: rates, shifted_test: rates}, agent_detector: { shifted_test: agents } },
    experiment_3_skimming_sweep: {subtle: {skimmer_count: 2, honest_agent_count: 6, skimmer_detection_rate: 0, honest_false_flag_rate: .1}},
    experiment_4_signal_ablations: { test_fixture: 'unsupported-no-observations' },
    experiment_5_adoption_sensitivity: { disclaimer: 'Idealized perfect compliance assumption.', eligible_assisted_skimming_loss_bdt: 20, eligible_assisted_skimmer_actions: 2, total_injected_skimming_loss_bdt: 100, total_test_skimmer_actions: 4, total_eligible_assisted_cashouts: 10, scenarios: {adoption_30pct: { adoption_rate: .3, loss_prevented_bdt: 6, pct_eligible_assisted_loss_prevented: 30, pct_total_injected_loss_prevented: 6 }, adoption_50pct: { adoption_rate: .5, loss_prevented_bdt: 10, pct_eligible_assisted_loss_prevented: 50, pct_total_injected_loss_prevented: 10 }, adoption_70pct: { adoption_rate: .7, loss_prevented_bdt: 14, pct_eligible_assisted_loss_prevented: 70, pct_total_injected_loss_prevented: 14 }} },
    fairness_evaluation: { validation_diagnostic: fairness, held_out_canonical: fairness, held_out_shifted: fairness },
  },
};
