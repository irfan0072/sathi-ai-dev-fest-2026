import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import { BriefView } from './components/CaseBrief';
import { FollowupPanel } from './components/ops/CallCenter';
import { EconomicsTable, EvidenceTables } from './components/ops/WorkflowEvidence';
import { tabs, canOpen } from './components/NavTabs';

const clean = (html) => html.replace(/<!-- -->/g, '');
const baseTask = { task_id: 7, followup_status: 'required', followup_attempts: 0, followup_assigned_to: null };

describe('independent follow-up panel', () => {
  it('explains that the registered handset cannot prove independence and has no phone field', () => {
    const html = clean(renderToString(<FollowupPanel task={baseTask} session={{ role: 'supervisor', subject: 's1' }} onDone={() => {}} />));
    expect(html).toContain('Independent follow-up');
    expect(html).toContain('Independent contact needed');
    expect(html).toContain('does not prove the customer is free to speak');
    expect(html).toContain('Take this follow-up');
    expect(html).not.toContain('type="tel"');
    expect(html).not.toContain('phone number');
  });

  it('offers "reached independently" only for in-person contact and keeps uncertain open', () => {
    const task = { ...baseTask, followup_assigned_to: 's1', followup_status: 'uncertain' };
    const html = clean(renderToString(<FollowupPanel task={task} session={{ role: 'supervisor', subject: 's1' }} onDone={() => {}} />));
    expect(html).toContain('Uncertain: still open');
    expect(html).toContain('Registered number (may be the agent');
    expect(html).not.toContain('Reached independently</option>'); // default channel is the registered number
  });

  it('renders nothing when no follow-up is needed', () => {
    const html = renderToString(<FollowupPanel task={{ ...baseTask, followup_status: 'not_required' }} session={{ role: 'supervisor', subject: 's1' }} onDone={() => {}} />);
    expect(html).toBe('');
  });
});

describe('case brief labelling', () => {
  const result = {
    provider: 'template', fallbacks: [], facts: [], mode: 'deterministic',
    mode_label: 'Deterministic summary from typed evidence', guard_limits: null,
    brief: { headline: 'h', what_happened: 'w', why_risky: [{ point: 'p', evidence: [] }], recommended_next_step_text: 'n', questions_for_customer: [], summary_bn: 'বাংলা' },
  };
  it('states whether the text is deterministic or AI-written and pattern-checked', () => {
    expect(clean(renderToString(<BriefView result={result} />))).toContain('Deterministic summary from typed evidence');
    const llm = { ...result, provider: 'gemini', mode: 'llm_guarded', mode_label: 'AI-written text, pattern-checked (not proven)', guard_limits: 'Pattern-level checks only.' };
    const html = clean(renderToString(<BriefView result={llm} />));
    expect(html).toContain('pattern-checked (not proven)');
    expect(html).toContain('Pattern-level checks only.');
  });
});

describe('workflow evidence page', () => {
  const r = (n, d) => ({ numerator: n, denominator: d, rate: d ? n / d : null });
  const ev = {
    calls: { attempted: 11, answered: r(6, 11), completed_with_a_clear_outcome: r(5, 11), completed_of_answered: r(5, 6), unclear: r(1, 11), no_answer: r(1, 11), failed_to_place: r(4, 11), definition: 'attempted = call rows' },
    retries: { of_checks_called: r(3, 8) },
    delivery_recovery: { tasks_with_a_placement_failure: r(2, 8), handed_to_a_person_after_provider_failure: 1 },
    cases: { total: 2, suspicious_checks_with_case: r(2, 2), decided_by_a_person: 2, cleared_no_wrongdoing_found: 0, confirmed_problem: 1, escalated: 1, meaning: 'A closed case is not recovered money and not proof of fraud.' },
    independent_followup: { unresolved: 1, note: 'uncertain stays open' },
    manual_handling: { resolved_by_a_person: 1 }, privacy: { transcripts_held: 3, audio_stored: false }, audit_trail: { events: 40 },
  };
  it('shows numerators over denominators and never claims recovered money', () => {
    const html = clean(renderToString(<EvidenceTables ev={ev} />));
    expect(html).toContain('6 / 11');
    expect(html).toContain('4 / 11');
    expect(html).toContain('not recovered money');
    expect(html).not.toMatch(/recovered \d/);
  });
  it('economics table labels itself as assumptions and shows the detection-only floor', () => {
    const eco = {
      status: 'ASSUMPTIONS ONLY. No invoices.',
      baseline: { cost: { total: 5390 }, benefit: { incidents_reached_by_call: 25.9, total: 0 }, net: -5390 },
      same_scenarios_corrected_delivery_and_explicit_intervention: { A_all_calls_loss_61: { intervention_0pct: -5390, intervention_25pct: -4418, intervention_50pct: -3446 } },
    };
    const html = clean(renderToString(<EconomicsTable eco={eco} />));
    expect(html).toContain('ASSUMPTIONS ONLY');
    expect(html).toContain('Net with detection only');
    expect(html).toContain('-506');
  });
});

describe('navigation', () => {
  it('lists the evidence page for staff only and names the AI ranking honestly', () => {
    const evidence = tabs.find((t) => t.id === 'evidence');
    expect(canOpen(evidence, { role: 'supervisor' })).toBe(true);
    expect(canOpen(evidence, { role: 'agent' })).toBe(false);
    expect(canOpen(evidence, { role: 'customer_channel' })).toBe(false);
    expect(tabs.find((t) => t.id === 'agents').label).toBe('Agent review ranking');
  });
});

// ---- visual follow-up regression tests -------------------------------------------------
import { exactTaka, roundedTaka } from './copy';
import { ExtendedBenchmarkView } from './components/ExtendedBenchmarkTab';
import { FollowupNotice, PublicDemoNote } from './components/ops/kit';
import { AuditForm } from './components/ops/CaseWorkbench';
import { AgentAdvice } from './components/LiquidityPage';

describe('exact money', () => {
  it('keeps cents on fees and balances and only rounds when asked', () => {
    expect(exactTaka(7.5)).toBe('৳7.50');
    expect(exactTaka(7.49)).toBe('৳7.49');
    expect(exactTaka(0)).toBe('৳0');
    expect(exactTaka(3000)).toBe('৳3,000');
    expect(exactTaka('12.30')).toBe('৳12.30');
    expect(exactTaka(null)).toBe('—');
    expect(roundedTaka(7.5)).toBe('≈৳8');
  });
});

describe('case decision defaults', () => {
  it('has no pre-selected decision and no pre-checked contact claim', () => {
    const html = clean(renderToString(<AuditForm caseId={1} followup={{ status: 'required', blocks_clearing: true }} onSaved={() => {}} />));
    expect(html).toContain('Choose a decision');
    expect(html).not.toMatch(/checkbox[^>]*checked/);
    expect(html).toContain('Cleared: no wrongdoing');
    expect(html).toContain('Independent contact needed');
    expect(html).toContain('cannot be cleared');
  });
  it('shows the clearance requirement and not a pre-claimed contact', () => {
    expect(renderToString(<FollowupNotice followup={{ status: 'uncertain' }} />)).toContain('Uncertain: still open');
    expect(renderToString(<FollowupNotice followup={{ status: 'not_required' }} />)).toBe('');
    expect(renderToString(<FollowupNotice followup={{ status: 'reached_independently' }} />)).toContain('can be cleared');
  });
});

describe('public demo and thin history', () => {
  it('explains disabled management instead of showing dead buttons', () => {
    const html = renderToString(<PublicDemoNote what="Creating staff is unavailable." />);
    expect(html).toContain('Disabled in the public demo');
    expect(html).toContain('still work');
  });
  it('does not present sparse history as the agent\'s own pattern and hides the ratio', () => {
    const html = clean(renderToString(<AgentAdvice agent={{
      history_supported: false, active_days_28: 3, max_daily_35d_bdt: 500, peak_p90_bdt: 29000,
      typical_daily_bdt: 18, peer_peak_p90_bdt: 4200, recommended_opening_float_bdt: 4500, peak_date: '2026-10-12' }} />));
    expect(html).toContain('Not enough history for agent-specific advice');
    expect(html).toContain('only 3');
    expect(html).toContain('peer estimate');
    expect(html).not.toContain('×');
    expect(html).not.toContain('1621');
  });
});

describe('extended benchmark view', () => {
  const r = (n, d) => ({ numerator: n, denominator: d, rate: n / d, ci95: [0, 0.05] });
  const method = (label, recall) => ({ label, recall, honest_high_volume_false_flags: r(0, 240) });
  const scenario = (name, base, cand) => ({ scenario: name, skimmers: 120, methods: {
    rule_baseline: method('Rule baseline', r(0, 120)), ensemble_v1: method('Deployed ensemble', base),
    ensemble_v2_shortfall: method('Candidate (dev-selected, NOT deployed)', cand) } });
  const data = {
    version: 'agent-benchmark-v2.0', replications: 3, agents_generated_total: 9000,
    final_held_out: { agents: 3600, skimmers: 120, honest_agents: 3480, honest_high_volume: 240 },
    protocol_sha256: 'a'.repeat(64), final_results_sha256: 'b'.repeat(64),
    canonical_comparison: 'The canonical held-out cohort has 60 agents, 2 skimmers.',
    scenarios: [scenario('moderate', r(120, 120), r(120, 120)), scenario('subtle', r(0, 120), r(0, 120)),
      scenario('unchanged_fee_shortfall_moderate', r(0, 120), r(119, 120))],
  };
  it('shows held-out denominators, the 0/120 subtle result and the undeployed candidate', () => {
    const html = clean(renderToString(<ExtendedBenchmarkView data={data} />));
    expect(html).toContain('3,600');
    expect(html).toContain('120 / 3,480');
    expect(html).toContain('0/120 (0.0%)');
    expect(html).toContain('NOT deployed');
    expect(html).toContain('not the held-out denominator');
    expect(html).toContain('unchanged_fee_shortfall_moderate');
    expect(html).toContain('119/120');
  });
});

describe('browser voice for the handset', () => {
  it('reports no support outside a browser and never invents a confidence', async () => {
    const { voiceSupport, listenOnce, speechLang } = await import('./voice');
    expect(voiceSupport()).toEqual({ speak: false, listen: false });
    expect(speechLang('en')).toBe('en-IN');
    expect(speechLang('bn')).toBe('bn-BD');
    let message = '';
    listenOnce('bn', { onResult() {}, onSilence() {}, onError: (m) => { message = m; }, onEnd() {} });
    expect(message).toContain('keypad');
  });
});

describe('speech recognition errors', () => {
  it('turns service-not-allowed into a keypad instruction and blocks retries', async () => {
    const { recognitionProblem } = await import('./voice');
    const blocked = recognitionProblem('service-not-allowed');
    expect(blocked.blocked).toBe(true);
    expect(blocked.message).toContain('Use the keypad');
    expect(recognitionProblem('network').blocked).toBe(false);
  });
});

describe('safari message', () => {
  it('explains Dictation and Chrome for Safari, and still blocks retries', async () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { userAgent: 'Mozilla/5.0 (Macintosh) AppleWebKit/605 Version/17.0 Safari/605.1.15' } });
    const { recognitionProblem } = await import('./voice');
    const r = recognitionProblem('service-not-allowed');
    if (original) Object.defineProperty(globalThis, 'navigator', original);
    expect(r.blocked).toBe(true);
    expect(r.message).toContain('Dictation');
    expect(r.message).toContain('Chrome or Edge');
  });
});
