import Icon from './Icon';

const lifecycle = [
  { step: 'requested', desc: 'Agent requests cash-out for customer', tone: 'badge-info' },
  { step: 'verified', desc: 'Customer enters Bangla amount through the simulated keypad', tone: 'badge-secondary' },
  { step: 'active', desc: 'Amount matches → one-time code issued to agent terminal', tone: 'badge-primary' },
  { step: 'redeemed', desc: 'Agent enters code → cash disbursed', tone: 'badge-success' },
  { step: 'review case', desc: 'Amount mismatch or cash gap → human supervisor reviews evidence', tone: 'badge-warning' },
  { step: 'expired / revoked', desc: 'TTL expired or customer revokes before redemption', tone: 'badge-neutral' },
];

const principles = [
  { title: 'No automated penalties', detail: 'Signals inform supervisor triage only. No automated account blocking, agent penalty, or beneficiary denial.' },
  { title: 'Zero demographic inputs', detail: 'Gender, age, region and urban/rural are excluded from model features and used only for fairness evaluation.' },
  { title: 'Calibration limits', detail: 'Calibration is an experimental objective on synthetic data. Live distribution shift needs ongoing validation.' },
  { title: 'Pilot deployment path', detail: 'Amounts, caps and fees are simulation assumptions. Production needs banking integration and regulatory compliance.' },
];

const trackMap = [
  { track: 'Track 07 · Open Innovation', what: 'Scoped one-time mandate confirmed on a call to the customer’s registered phone. No PIN sharing.' },
  { track: 'Track 01 · Trust & Risk', what: 'Real-time risk with step-up verification, silent duress signal, AI investigation briefs for analysts.' },
  { track: 'Track 05 · Merchant & Agent', what: '7-day cash-out demand forecast so agents open with enough cash; surge alerts.' },
  { track: 'Track 04 · Growth & Campaign', what: 'Uplift targeting: invite customers the outreach actually persuades, within a fixed budget.' },
];

const pipeline = [
  { layer: 'Synthetic data', desc: 'Zero PII or live data' },
  { layer: 'Features', desc: 'Behavioral aggregates, no demographics' },
  { layer: 'AI models', desc: 'Prototype classifiers, benchmark artifacts' },
  { layer: 'Policy engine', desc: 'Deterministic rules, mandate lifecycle' },
  { layer: 'Human review', desc: 'Supervisor console, audit log' },
];

export default function ArchitecturePage() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="page-title">How Sathi works</h2>
        <p className="page-lead">Problem, solution and principles. All data and financial defaults are simulation assumptions.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {trackMap.map((t) => (
          <div key={t.track} className="panel"><div className="panel-body gap-1 p-4">
            <div className="text-xs font-semibold text-primary">{t.track}</div>
            <div className="text-sm opacity-80">{t.what}</div>
          </div></div>
        ))}
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <div className="panel border-error/30">
          <div className="panel-body">
            <h3 className="flex items-center gap-2 font-semibold text-error"><Icon name="warning" />The problem: PIN disclosure</h3>
            <p className="text-sm opacity-80">In this simulation, Rahima Begum, 70, receives an allowance through a mobile financial service. She cannot navigate USSD menus alone, so she tells her PIN to an agent and loses control of her account.</p>
            <p className="text-sm opacity-80">Assisted use is assumed at <strong>30–50% of rural transactions</strong> (simulation assumption, not measured upay statistics).</p>
            <blockquote lang="bn" className="rounded-box border-l-4 border-error bg-error/5 p-3 text-sm">“রহিমা তার পিন নম্বর এজেন্টকে বলে দিলেন — কারণ তিনি একা USSD মেনু পরিচালনা করতে পারেন না।”</blockquote>
          </div>
        </div>
        <div className="panel border-success/30">
          <div className="panel-body">
            <h3 className="flex items-center gap-2 font-semibold text-success"><Icon name="check" />Sathi: scoped one-time mandate</h3>
            <p className="text-sm opacity-80">Rahima never shares her PIN. She confirms the amount on a Bangla keypad. If it matches the agent&apos;s request, the agent terminal gets a single-use code.</p>
            <ul className="flex flex-col gap-2 text-sm">
              {['Single-use, 15-minute, agent-bound code', 'Server calls the registered phone; Bangla prompt never says the amount', 'Silent duress: type the amount with a leading 0 (e.g. 03000) — sounds normal, holds the payout, alerts an analyst', 'Amount mismatch goes to human review', 'Risk raises verification strength; humans decide'].map((item) => (
                <li key={item} className="flex gap-2"><Icon name="check" className="mt-0.5 size-4 shrink-0 text-success" />{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="panel">
          <div className="panel-body">
            <h3 className="font-semibold">Mandate lifecycle</h3>
            <ul className="flex flex-col gap-3">
              {lifecycle.map((item) => (
                <li key={item.step} className="flex items-start gap-3">
                  <span className={`badge badge-soft ${item.tone} w-32 shrink-0 justify-center font-mono text-xs`}>{item.step}</span>
                  <span className="text-sm opacity-80">{item.desc}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="panel">
          <div className="panel-body">
            <h3 className="font-semibold">Responsible AI principles</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {principles.map((item) => (
                <div key={item.title} className="rounded-box bg-base-200 p-3">
                  <div className="text-sm font-semibold">{item.title}</div>
                  <div className="mt-1 text-xs opacity-70">{item.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-body">
          <h3 className="font-semibold">Architecture: input → intelligence → action</h3>
          <ul className="steps steps-vertical w-full md:steps-horizontal">
            {pipeline.map((item) => (
              <li key={item.layer} className="step step-primary">
                <span className="text-left md:text-center">
                  <span className="block text-sm font-semibold">{item.layer}</span>
                  <span className="block text-xs opacity-60">{item.desc}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted text-center">Track 07 Submission — AI DEV FEST 2026 — DIU CPC × upay · Not connected to actual upay production infrastructure.</p>
        </div>
      </div>
    </div>
  );
}
