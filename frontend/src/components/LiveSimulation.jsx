import { useCallback, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import DemoLogin, { roleMeta } from './DemoLogin';
import { AgentCallPanel, IncomingCall, RiskCard, SmsInbox } from './LiveCall';

const money = (value) => value == null ? 'Unavailable' : `৳ ${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BDT`;

const steps = [
  { label: 'Agent requests', role: 'agent' },
  { label: 'Customer confirms', role: 'customer_channel' },
  { label: 'Agent issues code', role: 'agent' },
  { label: 'Agent redeems', role: 'agent' },
  { label: 'Customer reports cash', role: 'customer_channel' },
];

const statusTone = {
  requested: 'badge-info', verified: 'badge-secondary', active: 'badge-primary', redeemed: 'badge-success',
  rejected: 'badge-error', expired: 'badge-warning', revoked: 'badge-neutral',
};

// Index of the step that should happen next, derived only from server-observed status.
const currentStep = (flow) => {
  if (!flow.mandateId) return 0;
  const byStatus = { requested: 1, verified: 2, active: 3, redeemed: flow.cashReported ? 5 : 4 };
  return byStatus[flow.status] ?? 1;
};

const nextHint = {
  0: 'Agent requests a cash-out amount for the bound customer.',
  1: 'Customer confirms the amount on a verification call or in the app.',
  2: 'Agent issues the one-time terminal code.',
  3: 'Agent enters the code to redeem and pay out cash.',
  4: 'Customer reports cash received and checks the receipt.',
  5: 'Flow complete. Start a new mandate any time.',
};

function Section({ title, step, active, done, children }) {
  return (
    <section className={`rounded-box border p-4 transition ${active ? 'border-primary bg-primary/5' : 'border-base-300'}`}>
      <div className="mb-3 flex items-center gap-2">
        <span className={`grid size-6 place-items-center rounded-full text-xs font-bold ${done ? 'bg-success text-success-content' : active ? 'bg-primary text-primary-content' : 'bg-base-300'}`}>
          {done ? <Icon name="check" className="size-3.5" /> : step}
        </span>
        <h3 className="font-semibold">{title}</h3>
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

export default function LiveSimulation({ session, flow = {}, setFlow = () => {}, onSwitchRole = () => {} }) {
  const [amount, setAmount] = useState('3000');
  const [stated, setStated] = useState('');
  const [cash, setCash] = useState('3000');
  const [code, setCode] = useState('');
  const [issuedCode, setIssuedCode] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [receipt, setReceipt] = useState(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmVia, setConfirmVia] = useState('call');

  const run = async (operation) => {
    setBusy(true); setError(''); setMessage('');
    try { await operation(); } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const request = () => run(async () => {
    const result = await api.requestMandate({ userId: session.allowed_users[0], agentId: session.subject, amount });
    setFlow({ mandateId: result.mandate_id, requested: result, status: result.status });
    setIssuedCode(''); setCode(''); setExpiresAt(''); setReceipt(null);
    setMessage('Request recorded. Switch to the customer channel to confirm the amount.');
  });
  const verify = () => run(async () => {
    const result = await api.verifyMandate({ mandateId: flow.mandateId, statedAmount: stated });
    setFlow((prev) => ({ ...prev, status: result.status }));
    setMessage(result.outcome === 'match' ? 'Amount matched. Switch to the bound agent terminal for one-time issuance.' : `Amount mismatch: ${result.status}. Human review case #${result.case_id}.`);
  });
  const issue = () => run(async () => {
    const result = await api.issueCode(flow.mandateId);
    setIssuedCode(result.code); setCode(result.code); setExpiresAt(result.expires_at);
    setFlow((prev) => ({ ...prev, status: result.status }));
    setMessage('Terminal code issued once. Lost delivery requires revocation and a new request.');
  });
  const redeem = () => run(async () => {
    const result = await api.redeemMandate({ mandateId: flow.mandateId, code });
    setFlow((prev) => ({ ...prev, transactionId: result.txn_id, status: result.status }));
    setMessage(`Redeemed transaction ${result.txn_id}. Payout ${money(result.amount)}, assumed fee ${money(result.fee)}. Switch to customer for receipt and cash report.`);
    setIssuedCode(''); setCode('');
  });
  const reportCash = () => run(async () => {
    const result = await api.confirmCash({ mandateId: flow.mandateId, cashReceived: cash });
    setFlow((prev) => ({ ...prev, cashReported: true }));
    setMessage(result.flagged ? `Reported gap ${money(result.gap)}; human review case #${result.case_id}.` : 'Cash report recorded. No gap flag at the assumed tolerance.');
  });
  const loadReceipt = () => run(async () => {
    setReceipt(null); setReceipt(await api.getReceipt(flow.transactionId));
  });
  const revoke = () => run(async () => {
    const result = await api.revokeMandate(flow.mandateId);
    setFlow((prev) => ({ ...prev, status: result.status })); setMessage('Mandate revoked.');
  });
  const callVerified = useCallback(() => {
    setFlow((prev) => ({ ...prev, status: 'verified' }));
    setMessage('Customer confirmed on the call. Issue the one-time terminal code.');
  }, [setFlow]);
  const callNotVerified = useCallback(() => {
    setFlow((prev) => ({ ...prev, status: 'rejected' }));
    setError('Customer did not confirm this cash-out. No code can be issued.');
  }, [setFlow]);
  const callFinished = useCallback((status) => {
    if (status === 'verified') setFlow((prev) => ({ ...prev, status: 'verified' }));
    if (status === 'not_verified') setFlow((prev) => ({ ...prev, status: 'rejected' }));
  }, [setFlow]);
  const reset = () => {
    setFlow({}); setIssuedCode(''); setCode(''); setExpiresAt(''); setReceipt(null); setStated(''); setMessage(''); setError('');
  };

  const step = currentStep(flow);
  const stopped = ['rejected', 'expired', 'revoked'].includes(flow.status);
  const nextRole = steps[step]?.role;
  const needsSwitch = session && nextRole && !stopped && session.role !== nextRole;
  const role = session?.role;
  const title = role === 'customer_channel' ? 'Customer Phone Simulator · গ্রাহকের নিশ্চিতকরণ' : 'Agent Point-of-Sale Terminal';

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="page-title">Cash-out mandate flow</h2>
          <p className="page-lead">Customer never shares a PIN. Each cash-out needs the customer&apos;s own amount confirmation and a single-use, agent-bound code.</p>
        </div>
        {flow.mandateId && <button className="btn btn-ghost btn-sm" onClick={reset}><Icon name="refresh" className="size-4" />New mandate</button>}
      </div>

      {/* Progress */}
      <div className="panel">
        <div className="panel-body">
          <ul className="steps steps-vertical w-full sm:steps-horizontal">
            {steps.map((item, index) => (
              <li key={item.label} data-content={index < step ? '✓' : index + 1}
                className={`step text-xs sm:text-sm ${index < step ? 'step-success' : index === step && !stopped ? 'step-primary' : ''}`}>
                <span className="text-left sm:text-center">
                  <span className="block font-medium">{item.label}</span>
                  <span className="block text-[11px] opacity-60">{roleMeta[item.role].label}</span>
                </span>
              </li>
            ))}
          </ul>
          {stopped ? (
            <div role="status" className="alert alert-warning alert-soft text-sm">
              <Icon name="warning" />
              <span>Mandate is <strong>{flow.status}</strong>. No cash-out can happen on it. Start a new mandate.</span>
            </div>
          ) : (
            <div className="flex flex-col gap-2 rounded-box bg-base-200 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span className="flex items-center gap-2"><Icon name="arrow" className="size-4 shrink-0 text-primary" /><span><strong>Next:</strong> {nextHint[step]}</span></span>
              {needsSwitch && (
                <button className="btn btn-primary btn-sm" onClick={() => onSwitchRole(nextRole)}>
                  <Icon name="switch" className="size-4" />Switch to {roleMeta[nextRole].label}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Role action panel */}
        <div className="panel lg:col-span-2">
          <div className="panel-body">
            <div className="flex items-center gap-3">
              {session && <span className={`grid size-9 place-items-center rounded-lg ${roleMeta[role].tone}`}><Icon name={roleMeta[role].icon} /></span>}
              <div>
                <h2 className="card-title text-base sm:text-lg">{title}</h2>
                {role === 'agent' && <p className="muted">Bound agent: {session.subject} · permitted customer: {session.allowed_users[0]}</p>}
              </div>
            </div>

            {!session && (
              <>
                <p className="text-sm opacity-70">Sign in with a synthetic demo role to start. Switch roles to act as each separate channel.</p>
                <DemoLogin />
              </>
            )}

            {role === 'agent' && (
              <div className="flex flex-col gap-4">
                <Section title="Request mandate" step={1} active={step === 0} done={step > 0}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Requested cash-out (BDT)</span>
                    <div className="join w-full">
                      <span className="join-item grid place-items-center border border-base-300 bg-base-200 px-3">৳</span>
                      <input aria-label="Requested cash-out (BDT)" className="input input-bordered join-item w-full" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
                      <button className="btn btn-primary join-item" disabled={busy} onClick={request}>Request mandate</button>
                    </div>
                  </label>
                </Section>

                <Section title="Get customer confirmation" step={2} active={step === 1} done={step > 1}>
                  <AgentCallPanel mandateId={flow.mandateId} status={flow.status} busy={busy}
                    onVerified={callVerified} onNotVerified={callNotVerified} />
                </Section>

                <Section title="Issue one-time code" step={3} active={step === 2} done={step > 2}>
                  <button className="btn btn-outline btn-primary w-full sm:w-auto" disabled={busy || !flow.mandateId} onClick={issue}>Issue terminal code once</button>
                  {issuedCode && (
                    <div className="flex flex-wrap items-center gap-3 rounded-box bg-neutral p-3 text-neutral-content">
                      <span className="text-xs opacity-70">One-time terminal code</span>
                      <strong className="font-mono text-2xl tracking-[0.3em]">{issuedCode}</strong>
                      <span className="text-xs opacity-70">expires {expiresAt}</span>
                    </div>
                  )}
                </Section>

                <Section title="Redeem and pay out" step={4} active={step === 3} done={step > 3}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Terminal redemption code</span>
                    <div className="join w-full">
                      <input aria-label="Terminal redemption code" className="input input-bordered join-item w-full font-mono tracking-widest" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off" />
                      <button className="btn btn-primary join-item" disabled={busy || !flow.mandateId || !code} onClick={redeem}>Redeem mandate</button>
                    </div>
                  </label>
                  <p className="muted">Repeated issuance, replay, expired code and lockout are rejected by the server.</p>
                </Section>
              </div>
            )}

            {role === 'customer_channel' && (
              <div className="grid gap-4 md:grid-cols-2">
                <Section title="Confirm amount" step={1} active={step === 1} done={step > 1}>
                  <div className="join w-full" role="group" aria-label="Confirmation channel">
                    <button className={`btn btn-sm join-item flex-1 ${confirmVia === 'call' ? 'btn-primary' : ''}`} onClick={() => setConfirmVia('call')}>Phone call</button>
                    <button className={`btn btn-sm join-item flex-1 ${confirmVia === 'app' ? 'btn-primary' : ''}`} onClick={() => setConfirmVia('app')}>In app</button>
                  </div>
                  {confirmVia === 'call' ? <IncomingCall mandateId={flow.mandateId} onFinished={callFinished} /> : <>
                  <div className="mx-auto w-full max-w-xs rounded-[1.75rem] border-4 border-neutral bg-base-100 p-4 shadow-sm">
                    <p lang="bn" className="text-center text-sm leading-relaxed">আপনি কত টাকা উত্তোলন করতে চান? ফি আলাদা। আপনার পিন কাউকে দেবেন না।</p>
                    <label className="mt-3 block">
                      <span className="sr-only">Confirm amount / নিশ্চিত টাকা</span>
                      <input aria-label="Confirm amount" className="input input-bordered input-lg w-full text-center font-bangla text-2xl" value={stated}
                        onChange={(e) => setStated(e.target.value)} inputMode="decimal" placeholder="০" />
                    </label>
                    <div className="mt-3 grid grid-cols-3 gap-2">
                      {['১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯'].map((digit) => (
                        <button key={digit} type="button" className="btn btn-ghost bg-base-200 font-bangla text-lg" onClick={() => setStated((prev) => prev + digit)}>{digit}</button>
                      ))}
                      <button type="button" className="btn btn-ghost bg-base-200 text-xs" onClick={() => setStated('')}>Clear</button>
                      <button type="button" className="btn btn-ghost bg-base-200 font-bangla text-lg" onClick={() => setStated((prev) => prev + '০')}>০</button>
                      <button type="button" className="btn btn-ghost bg-base-200" aria-label="Delete last digit" onClick={() => setStated((prev) => prev.slice(0, -1))}>⌫</button>
                    </div>
                    <button className="btn btn-primary mt-3 w-full" disabled={busy || !flow.mandateId || !stated} onClick={verify}>Confirm amount</button>
                  </div>
                  </>}
                  <p className="muted">Customer channel receives no terminal code. Amount mismatch uses bounded server-side attempts.</p>
                </Section>

                <Section title="After cash-out" step={4} active={step === 4} done={step > 4}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Cash actually received / <span lang="bn">প্রাপ্ত টাকা</span></span>
                    <input aria-label="Cash actually received" className="input input-bordered w-full" value={cash} onChange={(e) => setCash(e.target.value)} inputMode="decimal" />
                  </label>
                  <button className="btn btn-primary" disabled={busy || !flow.mandateId} onClick={reportCash}>Report cash received</button>
                  <div className="divider my-0" />
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Redeemed transaction ID</span>
                    <input aria-label="Redeemed transaction ID" className="input input-bordered w-full font-mono text-sm" value={flow.transactionId || ''} onChange={(e) => setFlow((prev) => ({ ...prev, transactionId: e.target.value }))} />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-outline btn-sm" disabled={busy || !flow.transactionId} onClick={loadReceipt}><Icon name="receipt" className="size-4" />View ledger receipt</button>
                    <button className="btn btn-outline btn-error btn-sm" disabled={busy || !flow.mandateId} onClick={revoke}>Revoke mandate</button>
                  </div>
                  <div className="divider my-0" />
                  <SmsInbox />
                </Section>
              </div>
            )}

            {role === 'analyst' && (
              <div className="alert alert-info alert-soft text-sm">
                <Icon name="info" />
                <span>Analysts review cases and evidence in the tabs. This role cannot redeem.</span>
              </div>
            )}

            {busy && <p role="status" className="flex items-center gap-2 text-sm opacity-70"><span className="loading loading-spinner loading-sm" />Waiting for the real API…</p>}
            {error && <div role="alert" className="alert alert-error alert-soft text-sm"><Icon name="warning" /><span>{error}</span></div>}
            {message && <div role="status" className="alert alert-success alert-soft text-sm"><Icon name="check" /><span>{message}</span></div>}
            {receipt && (
              <div className="rounded-box border border-success/40 bg-success/5 p-4">
                <h3 className="mb-1 flex items-center gap-2 font-semibold"><Icon name="receipt" className="size-4" />Verified database ledger receipt</h3>
                <p lang="bn" className="text-sm">{receipt.receipt_text_bn}</p>
                <p className="muted mt-1">{receipt.provenance} · transaction {receipt.txn_id}</p>
              </div>
            )}
          </div>
        </div>

        {/* Mandate summary */}
        <aside className="panel h-fit">
          <div className="panel-body">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">Mandate</h3>
              {flow.status ? <span className={`badge ${statusTone[flow.status] || 'badge-ghost'}`}>{flow.status}</span> : <span className="badge badge-ghost">No response yet</span>}
            </div>
            {session ? (
              <label className="w-full">
                <span className="muted mb-1 block">Mandate ID</span>
                <input aria-label="Mandate ID" className="input input-bordered input-sm w-full font-mono" value={flow.mandateId || ''}
                  onChange={(e) => setFlow((prev) => ({ ...prev, mandateId: e.target.value }))} />
              </label>
            ) : <p className="muted">Sign in to create or load a mandate.</p>}
            <p className="sr-only">Observed status: {flow.status || 'No response yet'}</p>
            {flow.requested && (
              <dl className="divide-y divide-base-300 text-sm">
                <div className="flex justify-between py-2"><dt className="opacity-70">Full payout</dt><dd className="font-semibold">{money(flow.requested.payout)}</dd></div>
                <div className="flex justify-between py-2"><dt className="opacity-70">ASSUMED fee</dt><dd className="font-semibold">{money(flow.requested.fee)}</dd></div>
                <div className="flex justify-between py-2"><dt className="opacity-70">Total ledger debit</dt><dd className="font-semibold">{money(flow.requested.total_debit)}</dd></div>
              </dl>
            )}
            {role === 'agent' && <RiskCard risk={flow.requested?.risk} />}
            <p className="muted border-t border-base-300 pt-3">Independent amount confirmation only; it cannot establish coercion, honesty or actual physical delivery. Keypad first; no speech recognition.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
