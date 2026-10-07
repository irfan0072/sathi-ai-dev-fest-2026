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
