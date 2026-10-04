import { useState, useEffect } from 'react';
import { api } from '../api';
import { featureLabel } from '../copy';
import { phone } from '../ids';
import PageGuide from './PageGuide';

// Show each signal in everyday units instead of raw model numbers.
const plainValue = (feature, v) => {
  if (v == null) return '—';
  if (/ratio|share|concentration|fraction/.test(feature)) return `${Math.round(v * 100)}%`;
  if (/seconds/.test(feature)) return `${v.toFixed(1)} s`;
  if (/hours/.test(feature)) return `${v.toFixed(1)} h`;
  if (/amount|balance|bdt/.test(feature)) return `৳${Math.round(v).toLocaleString('en-US')}`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
};

export function OutreachGuide() {
  return (
    <PageGuide
      what="Some customers (older people, people who cannot read well, students on allowance) let an agent do the cash-out for them. They are the people most often cheated. This page finds them, so upay can offer Sathi’s free confirmation call to them first."
      steps={[
        'Sathi takes every customer active in the last 30 days from the live database.',
        'It measures behaviour: how long the PIN takes, how many steps a payment needs, how often an agent does it for them, how much of the balance they withdraw at once.',
        'A trained LightGBM model turns these signals into a chance (0-100%) that the person needs help.',
        'For any customer, “Why?” shows which signals raised or lowered their score.',
      ]}
      actions={[
        'Start with the customers at the top of the list. Higher chance means more likely to need help.',
        'Offer them Sathi (SMS, call or agent visit). See “Invite planner” for the cheapest way.',
        'This score is used only to offer help. It never blocks or limits an account.',
      ]}
      terms={[
        { term: 'Chance', meaning: 'How likely the AI thinks this person needs help to pay. Above 50% counts as “likely”.' },
        { term: 'Relies on one agent', meaning: 'Share of their cash-outs done at the same agent. 100% means always the same agent.' },
        { term: 'Pushes the score up / down', meaning: 'How much a signal moved this person’s chance. Longer bar means a stronger effect.' },
      ]}
    />
  );
}

export function UserReasons({ data }) {
  return (
    <div className="panel shadow-sm">
      <div className="panel-body">
        <h3 className="font-semibold">Why {phone(data.user_id)} may need help</h3>
        <p className="text-sm">
          Chance this person needs help with payments: <strong>{(data.score * 100).toFixed(0)}%</strong>. Used only to offer help.
        </p>
        <p className="muted">
          The signals that mattered most for this person. A longer bar means a bigger effect on the chance (technical unit: raw log-odds).
        </p>
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>What we noticed</th>
                <th className="text-right">This person</th>
                <th>Effect</th>
              </tr>
            </thead>
            <tbody>
              {data.top_reasons.map((reason) => (
                <tr key={reason.feature}>
                  <td>{featureLabel(reason.feature)}</td>
                  <td className="text-right font-mono">{plainValue(reason.feature, reason.value)}</td>
                  <td className="min-w-36">
                    <div className="flex items-center gap-2">
                      <progress
                        className={`progress w-20 ${reason.attribution >= 0 ? 'progress-warning' : 'progress-info'}`}
                        value={Math.min(Math.abs(reason.attribution), 2.5)} max="2.5"
                      />
                      <span className="text-xs">{reason.attribution >= 0 ? 'pushes up' : 'pushes down'}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted">
          {data.score >= 0.5
            ? 'Suggested next step: offer this customer Sathi so every cash-out is confirmed with them by phone.'
            : 'This customer probably manages payments on their own. No outreach needed.'}
        </p>
      </div>
    </div>
  );
}

export default function OutreachList({ initialData = null }) {
  const [data, setData] = useState(initialData);
  const [score, setScore] = useState(null);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    if (initialData) return () => { live = false; };
    const load = () => api.getOutreachList().then((value) => { if (live) { setData(value); setError(''); } }).catch((err) => { if (live) setError(err.message); });
    load();
    const timer = setInterval(load, 60000);
    return () => { live = false; clearInterval(timer); };
  }, [initialData]);
  const select = async (id) => {
    setScore(null); setError(''); setSelected(id);
    try { setScore(await api.getUserAssistedScore(id)); } catch (err) { setError(err.message); }
  };

  return (
    <div className="flex flex-col gap-2">
      <div>
        <h2 className="page-title">Customers who may need help</h2>
        <p className="page-lead mt-1">
          Customers active in the last 30 days who may need someone to help them pay, so we can offer Sathi to them first.
          Scored live by the trained AI from their real activity
          {data?.computed_at ? ` · updated ${new Date(data.computed_at).toLocaleTimeString()}` : ''}.
        </p>
      </div>
      <OutreachGuide />
      {data && (
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ['Customers checked', (data.scored_customers ?? data.total)?.toLocaleString(), `active in the last ${data.window_days || 30} days`],
            ['Likely need help', data.likely_assisted?.toLocaleString() ?? '—', `chance above ${Math.round((data.threshold ?? 0.5) * 100)}%`],
            ['Shown here', data.items.length.toLocaleString(), 'highest chance first'],
          ].map(([label, value, note]) => (
            <div key={label} className="panel"><div className="panel-body gap-1 p-4">
              <span className="muted">{label}</span><span className="text-2xl font-bold">{value}</span><span className="muted">{note}</span>
            </div></div>
          ))}
        </div>
      )}
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          Unavailable: {error}
        </div>
      )}
      {!data ? (
        <p className="flex items-center gap-2 text-sm text-base-content/70">
          <span className="loading loading-dots loading-sm" />
          Scoring active customers…
        </p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="panel shadow-sm">
            <div className="panel-body p-2 sm:p-4">
              <p className="muted px-2">
                {data.scored_customers?.toLocaleString() ?? data.total} customers scored · {data.likely_assisted ?? '—'} likely need help · top {data.items.length} shown
              </p>
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Customer</th>
                      <th>Chance</th>
                      <th className="hidden text-right md:table-cell">Cash-outs (30 d)</th>
                      <th className="hidden text-right md:table-cell">Relies on one agent</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((item, index) => (
                      <tr
                        key={item.user_id}
                        className={`transition-colors hover:bg-base-200 ${
                          selected === item.user_id ? 'bg-primary/10' : ''
                        }`}
                      >
                        <td>{index + 1}</td>
                        <td className="font-mono text-xs">{phone(item.user_id)}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <progress
                              className="progress progress-primary hidden w-16 sm:block"
                              value={item.assisted_score * 100}
                              max="100"
                            />
                            <span className="font-mono text-xs">{(item.assisted_score * 100).toFixed(1)}%</span>
                          </div>
                        </td>
                        <td className="hidden text-right font-mono text-xs md:table-cell">{item.cashouts_30d ?? '—'}</td>
                        <td className="hidden text-right font-mono text-xs md:table-cell">{item.top_agent_share == null ? '—' : `${Math.round(item.top_agent_share * 100)}%`}</td>
                        <td className="text-right">
                          <button className="btn btn-ghost btn-xs focus-ring" onClick={() => select(item.user_id)}>
                            Why?
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          {score ? (
            <UserReasons data={score} />
          ) : (
            <div className="panel shadow-sm">
              <div className="panel-body items-center justify-center py-10 text-center text-sm text-base-content/60">
                Choose a customer to see why they are on this list.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
