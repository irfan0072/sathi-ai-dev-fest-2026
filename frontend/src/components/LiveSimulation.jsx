import { useState } from 'react';
import { api } from '../api';
const money = (value) => value == null ? 'Unavailable' : `৳ ${Number(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})} BDT`;
export default function LiveSimulation({ session, flow = {}, setFlow = () => {} }) {
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
  return <div className="simulation-container">
    <div className="glass-card">
      <h2 className="card-title">{session?.role === 'customer_channel' ? 'Customer Phone Simulator · গ্রাহকের নিশ্চিতকরণ' : 'Agent Point-of-Sale Terminal'}</h2>
      <p>Independent amount confirmation only; it cannot establish coercion, honesty or actual physical delivery. Keypad first; no speech recognition.</p>
      {!session && <p>Sign in with a synthetic demo role above.</p>}
      {session && <>
        <label>Mandate ID<input aria-label="Mandate ID" value={flow.mandateId || ''} onChange={(e) => setFlow((prev) => ({ ...prev, mandateId: e.target.value }))} /></label>
        <p>Observed status: {flow.status || 'No response yet'}</p>
        {flow.requested && <div className="amount-summary">
          <p>Full payout: <strong>{money(flow.requested.payout)}</strong></p>
          <p>ASSUMED fee: <strong>{money(flow.requested.fee)}</strong></p>
          <p>Total ledger debit: <strong>{money(flow.requested.total_debit)}</strong></p>
        </div>}
      </>}
      {session?.role === 'agent' && <>
        <p>Bound agent: {session.subject} · permitted customer: {session.allowed_users[0]}</p>
        <label>Requested cash-out (BDT)<input aria-label="Requested cash-out (BDT)" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" /></label>
        <button className="primary-btn" disabled={busy} onClick={request}>Request mandate</button>
        <div className="terminal-actions">
          <button className="primary-btn" disabled={busy || !flow.mandateId} onClick={issue}>Issue terminal code once</button>
          {issuedCode && <p>One-time terminal code: <strong className="terminal-code">{issuedCode}</strong> · expires {expiresAt}</p>}
          <label>Terminal redemption code<input aria-label="Terminal redemption code" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="off" /></label>
          <button className="primary-btn" disabled={busy || !flow.mandateId || !code} onClick={redeem}>Redeem mandate</button>
          <p>Repeated issuance, replay, expired code and lockout are rejected by the server.</p>
        </div>
      </>}
      {session?.role === 'customer_channel' && <>
        <p lang="bn">আপনি কত টাকা উত্তোলন করতে চান? ফি আলাদা। আপনার পিন কাউকে দেবেন না।</p>
        <label>Confirm amount / নিশ্চিত টাকা<input aria-label="Confirm amount" value={stated} onChange={(e) => setStated(e.target.value)} inputMode="decimal" /></label>
        <div className="keypad-grid">{['১','২','৩','৪','৫','৬','৭','৮','৯','০'].map((digit) => <button key={digit} onClick={() => setStated((prev) => prev + digit)}>{digit}</button>)}<button onClick={() => setStated('')}>Clear</button></div>
        <button className="primary-btn" disabled={busy || !flow.mandateId || !stated} onClick={verify}>Confirm amount</button>
        <p>Customer channel receives no terminal code. Amount mismatch uses bounded server-side attempts.</p>
        <div className="terminal-actions">
          <label>Cash actually received / প্রাপ্ত টাকা<input aria-label="Cash actually received" value={cash} onChange={(e) => setCash(e.target.value)} inputMode="decimal" /></label>
          <button className="primary-btn" disabled={busy || !flow.mandateId} onClick={() => run(async () => {
            const result = await api.confirmCash({ mandateId: flow.mandateId, cashReceived: cash });
            setMessage(result.flagged ? `Reported gap ${money(result.gap)}; human review case #${result.case_id}.` : 'Cash report recorded. No gap flag at the assumed tolerance.');
          })}>Report cash received</button>
          <label>Redeemed transaction ID<input aria-label="Redeemed transaction ID" value={flow.transactionId || ''} onChange={(e) => setFlow((prev) => ({ ...prev, transactionId: e.target.value }))} /></label>
          <button className="chip-btn" disabled={busy || !flow.transactionId} onClick={() => run(async () => {
            setReceipt(null); setReceipt(await api.getReceipt(flow.transactionId));
          })}>View ledger receipt</button>
          <button className="chip-btn" disabled={busy || !flow.mandateId} onClick={() => run(async () => {
            const result = await api.revokeMandate(flow.mandateId);
            setFlow((prev) => ({ ...prev, status: result.status })); setMessage('Mandate revoked.');
          })}>Revoke mandate</button>
        </div>
      </>}
      {session?.role === 'analyst' && <p>Analysts review cases and evidence in the tabs. This role cannot redeem.</p>}
      {busy && <p role="status">Waiting for the real API…</p>}
      {error && <p role="alert" className="error-box">{error}</p>}
      {message && <p role="status" className="result-box">{message}</p>}
      {receipt && <div className="result-box"><h3>Verified database ledger receipt</h3><p lang="bn">{receipt.receipt_text_bn}</p><p>{receipt.provenance} · transaction {receipt.txn_id}</p></div>}
    </div>
  </div>;
}
