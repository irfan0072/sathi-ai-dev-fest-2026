import Icon from './Icon';

const lifecycle = [
  { step: '1. Cash-out', desc: 'The agent gives the cash and records it. The money leaves the account.', tone: 'badge-info' },
  { step: '2. Call', desc: 'Sathi calls the customer right away. The call never says the amount.', tone: 'badge-secondary' },
  { step: '3. Customer types', desc: 'The customer types the cash they got and presses #.', tone: 'badge-primary' },
  { step: 'Verified', desc: 'Same amount as the transaction: marked verified.', tone: 'badge-success' },
  { step: 'Suspicious', desc: 'Different amount, “I didn’t do this”, or the secret help signal: marked suspicious with reasons, and a supervisor reviews it.', tone: 'badge-warning' },
  { step: 'No answer', desc: 'A supervisor can call the customer again.', tone: 'badge-neutral' },
];

const principles = [
  {
    title: 'People decide, not the AI',
    detail: 'The AI only points out what to check. It never blocks an account or punishes an agent by itself.',
  },
  {
    title: 'Fair to everyone',
    detail: 'The AI never uses gender, age or where someone lives. We only use them to check it treats everyone fairly.',
  },
  {
    title: 'Honest about limits',
    detail: 'The AI was tested on made-up data. It must be checked again with real data before real use.',
  },
  {
    title: 'Safe path to real use',
    detail: 'Amounts, limits and fees here are estimates. Real use needs approval and a link to the real payment system.',
  },
];

const trackMap = [
  {
    track: 'Safe cash-out · Track 07',
    what: 'Customers get cash without sharing their PIN. They confirm the amount on their own phone.',
  },
  {
    track: 'Fraud protection · Track 01',
    what: 'Extra checks when something looks risky, a secret help signal, and AI summaries for supervisors.',
  },
  {
    track: 'Help for agents · Track 05',
    what: 'Tells each agent how much cash to keep ready for the next 7 days.',
  },
  {
    track: 'More people using Sathi · Track 04',
    what: 'Invites the customers who will really start using Sathi, within a fixed budget.',
  },
];

const pipeline = [
  { layer: 'Data', desc: 'Live PostgreSQL ledger of synthetic customers and agents. A 5-million-customer table was used once as a performance (scale) test; the counts on screen are the live runtime counts' },
  { layer: 'Patterns', desc: 'How people usually pay and cash out' },
  { layer: 'AI', desc: 'Spots unusual activity and predicts needs' },
  { layer: 'Rules', desc: 'Fixed safety rules for every cash-out' },
  { layer: 'People', desc: 'Supervisors make the final decision' },
];

export default function ArchitecturePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="page-title">How Sathi works</h2>
        <p className="page-lead mt-1">
          The problem we solve and how Sathi keeps cash-outs safe.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {trackMap.map((t) => (
          <div key={t.track} className="panel transition-colors hover:border-primary/40">
            <div className="panel-body gap-1 p-4">
              <div className="text-xs font-semibold text-primary">{t.track}</div>
              <div className="text-sm text-base-content/80">{t.what}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <div className="panel border-error/30 shadow-sm">
          <div className="panel-body">
            <h3 className="flex items-center gap-2 font-semibold text-error">
              <Icon name="warning" />
              The problem: people share their PIN
            </h3>
            <p className="text-sm text-base-content/80">
              Rahima, 70, gets a monthly allowance on her phone. She can&apos;t use the phone menus alone, so she tells her
              PIN to the agent. Now someone else can take her money.
            </p>
            <p className="text-sm text-base-content/80">
              Agent-assisted cash-out is a widely reported pattern, but <strong>we have no measured
              share for Bangladesh</strong>: no number here comes from upay or from a survey of our own.
            </p>
            <blockquote
              lang="bn"
              className="rounded-box border-l-4 border-error bg-error/5 p-3 text-sm text-base-content"
            >
              “রহিমা তার পিন নম্বর এজেন্টকে বলে দিলেন — কারণ তিনি একা USSD মেনু পরিচালনা করতে পারেন না।”
            </blockquote>
          </div>
        </div>
        <div className="panel border-success/30 shadow-sm">
          <div className="panel-body">
            <h3 className="flex items-center gap-2 font-semibold text-success">
              <Icon name="check" />
              Our answer: check every cash-out with the customer
            </h3>
            <p className="text-sm text-base-content/80">
              Right after the agent gives Rahima cash, Sathi calls her. She types the amount she actually got, in
              Bangla. If it is less than the transaction, the cash-out is marked suspicious for a supervisor.
            </p>
            <ul className="flex flex-col gap-2 text-sm">
              {[
                'Every cash-out is checked, not only risky ones',
                'We call her registered phone; the call never says the amount',
                'Secret help: if forced, she types 0 first (like 03000). It looks normal to anyone nearby. The money has already left the account, so Sathi cannot stop it; an urgent case goes to a supervisor, who needs an independent contact before anything is cleared',
                'A different amount is marked suspicious, never “fraud”',
                'Agents never see the result, so they cannot pressure the customer',
              ].map((item) => (
                <li key={item} className="flex gap-2">
                  <Icon name="check" className="mt-0.5 size-4 shrink-0 text-success" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="panel shadow-sm">
          <div className="panel-body">
            <h3 className="font-semibold">Step by step</h3>
            <ul className="flex flex-col gap-3">
              {lifecycle.map((item) => (
                <li key={item.step} className="flex items-start gap-3">
                  <span
                    className={`badge badge-soft ${item.tone} w-32 shrink-0 justify-center font-mono text-xs`}
                  >
                    {item.step}
                  </span>
                  <span className="text-sm text-base-content/80">{item.desc}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="panel shadow-sm">
          <div className="panel-body">
            <h3 className="font-semibold">Our promises</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {principles.map((item) => (
                <div key={item.title} className="rounded-box bg-base-200 p-3">
                  <div className="text-sm font-semibold">{item.title}</div>
                  <div className="mt-1 text-xs text-base-content/70">{item.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="panel shadow-sm">
        <div className="panel-body">
          <h3 className="font-semibold">How the system fits together</h3>
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
          <p className="muted text-center">
            AI DEV FEST 2026 — DIU CPC × upay · Runs on a synthetic upay-scale population; every screen reads the live database.
          </p>
        </div>
      </div>
    </div>
  );
}