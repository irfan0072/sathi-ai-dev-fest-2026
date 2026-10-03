import { useCallback, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import DemoLogin, { roleMeta } from './DemoLogin';
import { AgentCallPanel, IncomingCall, RiskCard, SmsInbox } from './LiveCall';
import { statusLabel } from '../copy';

const money = (value) =>
  value == null ? 'Not available' : `৳ ${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BDT`;

const steps = [
  { label: 'Agent enters amount', role: 'agent' },
  { label: 'Customer confirms', role: 'customer_channel' },
  { label: 'Agent gets code', role: 'agent' },
  { label: 'Agent gives cash', role: 'agent' },
  { label: 'Customer checks cash', role: 'customer_channel' },
];

const statusTone = {
  requested: 'badge-info',
  verified: 'badge-secondary',
  active: 'badge-primary',
  redeemed: 'badge-success',
  rejected: 'badge-error',
  expired: 'badge-warning',
  revoked: 'badge-neutral',
};

// Index of the step that should happen next, derived only from server-observed status.
const currentStep = (flow) => {
  if (!flow.mandateId) return 0;
  const byStatus = { requested: 1, verified: 2, active: 3, redeemed: flow.cashReported ? 5 : 4 };
  return byStatus[flow.status] ?? 1;
};

const nextHint = {
  0: 'The agent types how much cash the customer wants.',
  1: 'The customer confirms the amount on a phone call or in the app.',
  2: 'The agent gets a one-time code.',
  3: 'The agent types the code and gives the cash.',
  4: 'The customer says how much cash they got and checks the receipt.',
  5: 'All done. You can start a new cash-out.',
};

function Section({ title, step, active, done, children }) {
  return (
    <section
      className={`rounded-box border p-4 transition-colors sm:p-5 ${
        active ? 'border-primary bg-primary/5' : 'border-base-300 bg-base-100'
      }`}
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`grid size-6 place-items-center rounded-full text-xs font-bold transition-colors ${
            done
              ? 'bg-success text-success-content'
              : active
                ? 'bg-primary text-primary-content'
                : 'bg-base-200 text-base-content/70'
          }`}
        >
          {done ? <Icon name="check" className="size-3.5" /> : step}
        </span>
        <h3 className="text-sm font-semibold sm:text-base">{title}</h3>
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
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await operation();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const request = () =>
    run(async () => {
      const result = await api.requestMandate({ userId: session.allowed_users[0], agentId: session.subject, amount });
      setFlow({ mandateId: result.mandate_id, requested: result, status: result.status });
      setIssuedCode('');
      setCode('');
      setExpiresAt('');
      setReceipt(null);
      setMessage('Request sent. Now the customer needs to confirm the amount.');
    });
  const verify = () =>
    run(async () => {
      const result = await api.verifyMandate({ mandateId: flow.mandateId, statedAmount: stated });
      setFlow((prev) => ({ ...prev, status: result.status }));
      setMessage(
        result.outcome === 'match'
          ? 'The amount matches. The agent can now get the one-time code.'
          : `The amount did not match, so a supervisor will check it (case #${result.case_id}).`
      );
    });
  const issue = () =>
    run(async () => {
      const result = await api.issueCode(flow.mandateId);
      setIssuedCode(result.code);
      setCode(result.code);
      setExpiresAt(result.expires_at);
      setFlow((prev) => ({ ...prev, status: result.status }));
      setMessage('Here is the one-time code. It works only once. If it gets lost, cancel and start again.');
    });
  const redeem = () =>
    run(async () => {
      const result = await api.redeemMandate({ mandateId: flow.mandateId, code });
      setFlow((prev) => ({ ...prev, transactionId: result.txn_id, status: result.status }));
      setMessage(
        `Cash-out complete: ${money(result.amount)} paid, fee ${money(result.fee)}. Receipt number ${result.txn_id}. The customer can now check the receipt.`
      );
      setIssuedCode('');
      setCode('');
    });
  const reportCash = () =>
    run(async () => {
      const result = await api.confirmCash({ mandateId: flow.mandateId, cashReceived: cash });
      setFlow((prev) => ({ ...prev, cashReported: true }));
      setMessage(
        result.flagged
          ? `You reported ${money(result.gap)} less cash. A supervisor will check it (case #${result.case_id}).`
          : 'Thank you. The cash amount looks right.'
      );
    });
  const loadReceipt = () =>
    run(async () => {
      setReceipt(null);
      setReceipt(await api.getReceipt(flow.transactionId));
    });
  const revoke = () =>
    run(async () => {
      const result = await api.revokeMandate(flow.mandateId);
      setFlow((prev) => ({ ...prev, status: result.status }));
      setMessage('Cash-out cancelled.');
    });
  const callVerified = useCallback(() => {
    setFlow((prev) => ({ ...prev, status: 'verified' }));
    setMessage('The customer confirmed on the call. You can now get the one-time code.');
  }, [setFlow]);
  const callNotVerified = useCallback(() => {
    setFlow((prev) => ({ ...prev, status: 'rejected' }));
    setError('The customer did not confirm this cash-out, so no code can be given.');
  }, [setFlow]);
  const callFinished = useCallback(
    (status) => {
      if (status === 'verified') setFlow((prev) => ({ ...prev, status: 'verified' }));
      if (status === 'not_verified') setFlow((prev) => ({ ...prev, status: 'rejected' }));
    },
    [setFlow]
  );
  const reset = () => {
    setFlow({});
    setIssuedCode('');
    setCode('');
    setExpiresAt('');
    setReceipt(null);
    setStated('');
    setMessage('');
    setError('');
  };

  const step = currentStep(flow);
  const stopped = ['rejected', 'expired', 'revoked'].includes(flow.status);
  const nextRole = steps[step]?.role;
  const needsSwitch = session && nextRole && !stopped && session.role !== nextRole;
  const role = session?.role;
  const title = role === 'customer_channel' ? 'Customer phone · গ্রাহকের নিশ্চিতকরণ' : 'Agent counter';

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="page-title">Safe cash-out</h2>
          <p className="page-lead mt-1">
            The customer never shares their PIN. They confirm the amount themselves, and the agent gets a
            code that works only once.
          </p>
        </div>
        {flow.mandateId && (
          <button className="btn btn-ghost btn-sm focus-ring" onClick={reset}>
            <Icon name="refresh" className="size-4" />
            Start new cash-out
          </button>
        )}
      </div>

      {/* Progress */}
      <div className="panel shadow-sm">
        <div className="panel-body">
          <ul className="steps steps-vertical w-full sm:steps-horizontal">
            {steps.map((item, index) => (
              <li
                key={item.label}
                data-content={index < step ? '✓' : index + 1}
                className={`step text-xs sm:text-sm ${
                  index < step ? 'step-success' : index === step && !stopped ? 'step-primary' : ''
                }`}
              >
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
              <span>
                This cash-out is <strong>{statusLabel(flow.status).toLowerCase()}</strong>. No money can be paid. Please start a new one.
              </span>
            </div>
          ) : (
            <div className="flex flex-col gap-2 rounded-box bg-base-200 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span className="flex items-center gap-2">
                <Icon name="arrow" className="size-4 shrink-0 text-primary" />
                <span>
                  <strong>Next:</strong> {nextHint[step]}
                </span>
              </span>
              {needsSwitch && (
                <button className="btn btn-primary btn-sm focus-ring" onClick={() => onSwitchRole(nextRole)}>
                  <Icon name="switch" className="size-4" />
                  Switch to {roleMeta[nextRole].label}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Role action panel */}
        <div className="panel shadow-sm lg:col-span-2">
          <div className="panel-body">
            <div className="flex items-center gap-3 border-b border-base-300 pb-3">
              {session && (
                <span className={`grid size-9 place-items-center rounded-lg ${roleMeta[role].tone}`}>
                  <Icon name={roleMeta[role].icon} />
                </span>
              )}
              <div className="min-w-0">
                <h2 className="card-title text-base sm:text-lg">{title}</h2>
                {role === 'agent' && (
                  <p className="muted">
                    Agent {session.subject} · serving customer {session.allowed_users[0]}
                  </p>
                )}
              </div>
            </div>

            {!session && (
              <>
                <p className="text-sm text-base-content/70">
                  Sign in to start.
                </p>
                <DemoLogin />
              </>
            )}

            {role === 'agent' && (
              <div className="flex flex-col gap-4">
                <Section title="Enter amount" step={1} active={step === 0} done={step > 0}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">How much cash? (Taka)</span>
                    <div className="join w-full">
                      <span className="join-item grid place-items-center border border-base-300 bg-base-200 px-3 font-mono">
                        ৳
                      </span>
                      <input
                        aria-label="Requested cash-out (BDT)"
                        className="input input-bordered join-item w-full focus-ring"
                        value={amount}
                        onChange={(e) => setAmount(e.target.value)}
                        inputMode="decimal"
                      />
                      <button
                        className="btn btn-primary join-item focus-ring"
                        disabled={busy}
                        onClick={request}
                      >
                        Send request
                      </button>
                    </div>
                  </label>
                </Section>

                <Section title="Customer confirms" step={2} active={step === 1} done={step > 1}>
                  <AgentCallPanel
                    mandateId={flow.mandateId}
                    status={flow.status}
                    busy={busy}
                    onVerified={callVerified}
                    onNotVerified={callNotVerified}
                  />
                </Section>

                <Section title="Get one-time code" step={3} active={step === 2} done={step > 2}>
                  <button
                    className="btn btn-outline btn-primary w-full focus-ring sm:w-auto"
                    disabled={busy || !flow.mandateId}
                    onClick={issue}
                  >
                    Get one-time code
                  </button>
                  {issuedCode && (
                    <div className="flex flex-wrap items-center gap-3 rounded-box border border-base-300 bg-neutral p-3 text-neutral-content">
                      <span className="text-xs opacity-70">One-time code</span>
                      <strong className="font-mono text-2xl tracking-[0.3em]">{issuedCode}</strong>
                      <span className="text-xs opacity-70">valid until {new Date(expiresAt).toLocaleTimeString()}</span>
                    </div>
                  )}
                </Section>

                <Section title="Give cash" step={4} active={step === 3} done={step > 3}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Type the one-time code</span>
                    <div className="join w-full">
                      <input
                        aria-label="Terminal redemption code"
                        className="input input-bordered join-item w-full font-mono tracking-widest focus-ring"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        inputMode="numeric"
                        autoComplete="off"
                      />
                      <button
                        className="btn btn-primary join-item focus-ring"
                        disabled={busy || !flow.mandateId || !code}
                        onClick={redeem}
                      >
                        Complete cash-out
                      </button>
                    </div>
                  </label>
                  <p className="muted">
                    Each code works only once and expires. Too many wrong codes stops the cash-out.
                  </p>
                </Section>
              </div>
            )}

            {role === 'customer_channel' && (
              <div className="grid gap-4 md:grid-cols-2">
                <Section title="Confirm amount" step={1} active={step === 1} done={step > 1}>
                  <div className="join w-full" role="group" aria-label="Confirmation channel">
                    <button
                      className={`btn btn-sm join-item flex-1 focus-ring ${
                        confirmVia === 'call' ? 'btn-primary' : ''
                      }`}
                      onClick={() => setConfirmVia('call')}
                    >
                      Phone call
                    </button>
                    <button
                      className={`btn btn-sm join-item flex-1 focus-ring ${
                        confirmVia === 'app' ? 'btn-primary' : ''
                      }`}
                      onClick={() => setConfirmVia('app')}
                    >
                      In app
                    </button>
                  </div>
                  {confirmVia === 'call' ? (
                    <IncomingCall mandateId={flow.mandateId} onFinished={callFinished} />
                  ) : (
                    <div className="mx-auto w-full max-w-xs rounded-[1.75rem] border-4 border-neutral bg-base-100 p-4 shadow-md">
                      <p lang="bn" className="text-center text-sm leading-relaxed">
                        আপনি কত টাকা উত্তোলন করতে চান? ফি আলাদা। আপনার পিন কাউকে দেবেন না।
                      </p>
                      <label className="mt-3 block">
                        <span className="sr-only">Confirm amount / নিশ্চিত টাকা</span>
                        <input
                          aria-label="Confirm amount"
                          className="input input-bordered input-lg w-full text-center font-bangla text-2xl focus-ring"
                          value={stated}
                          onChange={(e) => setStated(e.target.value)}
                          inputMode="decimal"
                          placeholder="০"
                        />
                      </label>
                      <div className="mt-3 grid grid-cols-3 gap-2">
                        {['১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯'].map((digit) => (
                          <button
                            key={digit}
                            type="button"
                            className="btn btn-ghost bg-base-200 font-bangla text-lg focus-ring"
                            onClick={() => setStated((prev) => prev + digit)}
                          >
                            {digit}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="btn btn-ghost bg-base-200 text-xs focus-ring"
                          onClick={() => setStated('')}
                        >
                          Clear
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost bg-base-200 font-bangla text-lg focus-ring"
                          onClick={() => setStated((prev) => prev + '০')}
                        >
                          ০
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost bg-base-200 focus-ring"
                          aria-label="Delete last digit"
                          onClick={() => setStated((prev) => prev.slice(0, -1))}
                        >
                          ⌫
                        </button>
                      </div>
                      <button
                        className="btn btn-primary mt-3 w-full focus-ring"
                        disabled={busy || !flow.mandateId || !stated}
                        onClick={verify}
                      >
                        Confirm amount
                      </button>
                    </div>
                  )}
                  <p className="muted">
                    You never get a code. If the amount is wrong twice, the cash-out is stopped.
                  </p>
                </Section>

                <Section title="After you get cash" step={4} active={step === 4} done={step > 4}>
                  <label className="w-full">
                    <span className="mb-1 block text-sm">
                      How much cash did you get? / <span lang="bn">প্রাপ্ত টাকা</span>
                    </span>
                    <input
                      aria-label="Cash actually received"
                      className="input input-bordered w-full focus-ring"
                      value={cash}
                      onChange={(e) => setCash(e.target.value)}
                      inputMode="decimal"
                    />
                  </label>
                  <button
                    className="btn btn-primary focus-ring"
                    disabled={busy || !flow.mandateId}
                    onClick={reportCash}
                  >
                    Send cash amount
                  </button>
                  <div className="divider my-0" />
                  <label className="w-full">
                    <span className="mb-1 block text-sm">Receipt number</span>
                    <input
                      aria-label="Redeemed transaction ID"
                      className="input input-bordered w-full font-mono text-sm focus-ring"
                      value={flow.transactionId || ''}
                      onChange={(e) => setFlow((prev) => ({ ...prev, transactionId: e.target.value }))}
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="btn btn-outline btn-sm focus-ring"
                      disabled={busy || !flow.transactionId}
                      onClick={loadReceipt}
                    >
                      <Icon name="receipt" className="size-4" />
                      Show receipt
                    </button>
                    <button
                      className="btn btn-outline btn-error btn-sm focus-ring"
                      disabled={busy || !flow.mandateId}
                      onClick={revoke}
                    >
                      Cancel this cash-out
                    </button>
                  </div>
                  <div className="divider my-0" />
                  <SmsInbox />
                </Section>
              </div>
            )}

            {role === 'analyst' && (
              <div className="alert alert-info alert-soft text-sm">
                <Icon name="info" />
                <span>Supervisors check problems from the “Cases to review” page. They cannot pay out cash.</span>
              </div>
            )}

            {busy && (
              <p role="status" className="flex items-center gap-2 text-sm text-base-content/70">
                <span className="loading loading-spinner loading-sm" />
                Please wait…
              </p>
            )}
            {error && (
              <div role="alert" className="alert alert-error alert-soft text-sm">
                <Icon name="warning" />
                <span>{error}</span>
              </div>
            )}
            {message && (
              <div role="status" className="alert alert-success alert-soft text-sm">
                <Icon name="check" />
                <span>{message}</span>
              </div>
            )}
            {receipt && (
              <div className="rounded-box border border-success/40 bg-success/5 p-4">
                <h3 className="mb-1 flex items-center gap-2 font-semibold">
                  <Icon name="receipt" className="size-4" />
                  Receipt
                </h3>
                <p lang="bn" className="text-sm">
                  {receipt.receipt_text_bn}
                </p>
                <p className="muted mt-1">
                  Receipt number {receipt.txn_id}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Mandate summary */}
        <aside className="panel h-fit shadow-sm">
          <div className="panel-body">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">This cash-out</h3>
              {flow.status ? (
                <span className={`badge ${statusTone[flow.status] || 'badge-ghost'}`}>{statusLabel(flow.status)}</span>
              ) : (
                <span className="badge badge-ghost">Not started</span>
              )}
            </div>
            {session ? (
              <label className="w-full">
                <span className="muted mb-1 block">Reference number</span>
                <input
                  aria-label="Mandate ID"
                  className="input input-bordered input-sm w-full font-mono focus-ring"
                  value={flow.mandateId || ''}
                  onChange={(e) => setFlow((prev) => ({ ...prev, mandateId: e.target.value }))}
                />
              </label>
            ) : (
              <p className="muted">Sign in to start.</p>
            )}
            <p className="sr-only">Status: {flow.status ? statusLabel(flow.status) : 'Not started'}</p>
            {flow.requested && (
              <dl className="divide-y divide-base-300 text-sm">
                <div className="flex justify-between py-2">
                  <dt className="text-base-content/70">Cash to customer</dt>
                  <dd className="font-semibold">{money(flow.requested.payout)}</dd>
                </div>
                <div className="flex justify-between py-2">
                  <dt className="text-base-content/70">Fee (estimate)</dt>
                  <dd className="font-semibold">{money(flow.requested.fee)}</dd>
                </div>
                <div className="flex justify-between py-2">
                  <dt className="text-base-content/70">Taken from account</dt>
                  <dd className="font-semibold">{money(flow.requested.total_debit)}</dd>
                </div>
              </dl>
            )}
            {role === 'agent' && <RiskCard risk={flow.requested?.risk} />}
            <p className="muted border-t border-base-300 pt-3">
              This checks the amount only. It cannot prove the cash was handed over, so the customer reports how much
              cash they got.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}