import { api } from '../../api';
import { Alert, Empty, Kpi, LiveDot, PageHead, Panel, num, pct, usePoll, when } from './kit';

const rate = (r) => (r && r.denominator ? `${num(r.numerator)} / ${num(r.denominator)} (${pct(r.rate)})` : 'no data');
const money = (v) => `${v < 0 ? '−' : ''}৳${num(Math.abs(Math.round(v)))}`;

function Row({ label, value, note }) {
  return (
    <tr>
      <td className="text-sm">{label}{note && <div className="muted text-xs">{note}</div>}</td>
      <td className="whitespace-nowrap text-right font-mono text-sm tabular-nums">{value}</td>
    </tr>
  );
}

export function EvidenceTables({ ev }) {
  const c = ev.calls;
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="Calls (numerators over denominators)">
        <table className="table table-sm"><tbody>
          <Row label="Call attempts" value={num(c.attempted)} note={c.definition} />
          <Row label="Answered" value={rate(c.answered)} />
          <Row label="Completed with a clear outcome" value={rate(c.completed_with_a_clear_outcome)} />
          <Row label="Clear outcome, of answered calls" value={rate(c.completed_of_answered)} />
          <Row label="Not understood (unclear)" value={rate(c.unclear)} />
          <Row label="No answer" value={rate(c.no_answer)} />
          <Row label="Could not be placed" value={rate(c.failed_to_place)} />
          <Row label="Checks that needed more than one call" value={rate(ev.retries.of_checks_called)} />
          <Row label="Tasks with a provider failure" value={rate(ev.delivery_recovery.tasks_with_a_placement_failure)} />
          <Row label="Handed to a person after provider failure" value={num(ev.delivery_recovery.handed_to_a_person_after_provider_failure)} />
        </tbody></table>
      </Panel>
      <Panel title="Cases and independent follow-up">
        <table className="table table-sm"><tbody>
          <Row label="Cases opened" value={num(ev.cases.total)} />
          <Row label="Suspicious checks that have a case" value={rate(ev.cases.suspicious_checks_with_case)} />
          <Row label="Decided by a person" value={num(ev.cases.decided_by_a_person)} note={ev.cases.meaning} />
          <Row label="Cleared (no wrongdoing found)" value={num(ev.cases.cleared_no_wrongdoing_found)} />
          <Row label="Confirmed problem" value={num(ev.cases.confirmed_problem)} />
          <Row label="Escalated" value={num(ev.cases.escalated)} />
          <Row label="Independent follow-up still unresolved" value={num(ev.independent_followup.unresolved)} note={ev.independent_followup.note} />
          <Row label="Manual tasks resolved by a person" value={num(ev.manual_handling.resolved_by_a_person)} />
          <Row label="Transcripts held / audio stored" value={`${num(ev.privacy.transcripts_held)} / ${ev.privacy.audio_stored ? 'yes' : 'no'}`} />
          <Row label="Audit events" value={num(ev.audit_trail.events)} />
        </tbody></table>
      </Panel>
    </div>
  );
}

export function EconomicsTable({ eco }) {
  const b = eco.baseline;
  const a = eco.same_scenarios_corrected_delivery_and_explicit_intervention;
  return (
    <Panel title="Cost and break-even (assumptions only, per 1,000 cash-outs)">
      <p className="muted mb-2">{eco.status}</p>
      <table className="table table-sm"><tbody>
        <Row label="Workflow cost (calls incl. failed attempts, SMS, manual review, case follow-up, hosting)" value={money(b.cost.total)} />
        <Row label="Incidents reached by a call (simulated incidence)" value={num(b.benefit.incidents_reached_by_call)} />
        <Row label="Loss returned by a separate intervention (rate 0 = detection only)" value={money(b.benefit.total)} />
        <Row label="Net with detection only" value={money(b.net)} />
        {Object.entries(a).map(([name, v]) => (
          <Row key={name} label={`${name.replaceAll('_', ' ')}: net at 0% / 25% / 50% intervention`}
            value={`${money(v.intervention_0pct)} / ${money(v.intervention_25pct)} / ${money(v.intervention_50pct)}`} />
        ))}
      </tbody></table>
      <p className="muted mt-2">Flagged cash gaps and closed cases are never counted as recovered or prevented money. The first report's scenarios (-506 / +740 / +475) assumed 50% of incidents are prevented; the primary cash-out has already completed, so that needs a separate supported intervention.</p>
    </Panel>
  );
}

export default function WorkflowEvidence() {
  const [ev, error] = usePoll(() => api.getWorkflowEvidence(), 10000);
  const [eco] = usePoll(() => api.getEconomics(), 600000);
  return (
    <div className="flex flex-col gap-5">
      <PageHead title="Workflow evidence" lead="What the confirmation workflow actually did in this database. Synthetic or simulated unless real partner data was loaded: this is workflow evidence, not field impact.">
        <LiveDot />
      </PageHead>
      <Alert>{error}</Alert>
      {!ev ? <Empty title="Loading…" /> : (
        <>
          <div className="rounded-box border border-warning/40 bg-warning/10 p-3 text-sm" role="note" data-testid="evidence-source">
            <strong>Source:</strong> {ev.source}. <strong>Provider:</strong> {ev.environment?.voice_provider || 'unknown'}. <strong>Field impact:</strong> none measured. {ev.field_impact_note}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi icon="phone" label="Call attempts" value={num(ev.calls.attempted)} note={`${rate(ev.calls.answered)} answered`} />
            <Kpi icon="check" label="Clear outcome" value={pct(ev.calls.completed_with_a_clear_outcome.rate)} note={rate(ev.calls.completed_with_a_clear_outcome)} />
            <Kpi icon="cases" label="Cases" value={num(ev.cases.total)} note={`${num(ev.cases.decided_by_a_person)} decided by a person`} />
            <Kpi icon="warning" label="Follow-up unresolved" value={num(ev.independent_followup.unresolved)} note="uncertain stays open" />
          </div>
          <EvidenceTables ev={ev} />
          <p className="muted">Window {when(ev.window.first_check_at)} to {when(ev.window.last_check_at)}. Generated {when(ev.window.generated_at)}.</p>
        </>
      )}
      {eco && <EconomicsTable eco={eco} />}
    </div>
  );
}
