import { useState, useEffect } from 'react';
import { api } from '../api';

export default function LiveSimulation({ onCaseCreated }) {
  // Agent Terminal State
  const [userId, setUserId] = useState('U_42_000008');
  const [agentId, setAgentId] = useState('A_000042');
  const [amount, setAmount] = useState('3000');
  const [mandate, setMandate] = useState(null);
  const [oneTimeCode, setOneTimeCode] = useState('');
  const [redeemCode, setRedeemCode] = useState('');
  const [redeemResult, setRedeemResult] = useState(null);
  const [receipt, setReceipt] = useState(null);

  // Phone Simulator State
  const [statedAmount, setStatedAmount] = useState('');
  const [verifyStatus, setVerifyStatus] = useState(null); // 'idle' | 'verifying' | 'matched' | 'mismatched'
  const [caseAlert, setCaseAlert] = useState(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);

  // Cash Confirmation
  const [cashReceived, setCashReceived] = useState('2955');
  const [cashConfirmResult, setCashConfirmResult] = useState(null);

  // Loading & Errors
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Countdown timer for active code
  const [timeLeftSec, setTimeLeftSec] = useState(900); // 15 mins

  useEffect(() => {
    let timer;
    if (mandate && mandate.status === 'active' && timeLeftSec > 0) {
      timer = setInterval(() => {
        setTimeLeftSec((prev) => Math.max(0, prev - 1));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [mandate, timeLeftSec]);

  // Audio prompt reader
  const playPromptAudio = (text) => {
    setIsPlayingAudio(true);
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'bn-BD';
      utterance.rate = 0.95;
      utterance.onend = () => setIsPlayingAudio(false);
      utterance.onerror = () => setIsPlayingAudio(false);
      window.speechSynthesis.speak(utterance);
    } else {
      setTimeout(() => setIsPlayingAudio(false), 2000);
    }
  };

  const handleRequestMandate = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setReceipt(null);
    setRedeemResult(null);
    setVerifyStatus(null);
    setCaseAlert(null);
    setStatedAmount('');
    try {
      const res = await api.requestMandate({ userId, agentId, amount });
      setMandate(res);
      setTimeLeftSec(900);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleKeypadPress = (val) => {
    if (val === 'CLEAR') {
      setStatedAmount('');
    } else if (val === 'BACK') {
      setStatedAmount((prev) => prev.slice(0, -1));
    } else {
      if (statedAmount.length < 6) {
        setStatedAmount((prev) => prev + val);
      }
    }
  };

  const handleVerify = async (amtOverride) => {
    const amtToSubmit = amtOverride || statedAmount;
    if (!amtToSubmit || !mandate) return;

    setLoading(true);
    setError(null);
    try {
      const res = await api.verifyMandate({
        mandateId: mandate.mandate_id,
        statedAmount: Number(amtToSubmit),
      });

      if (res.decision === 'ISSUE_MANDATE') {
        setVerifyStatus('matched');
        setMandate((prev) => ({ ...prev, status: 'active' }));
        // In simulation, code is revealed to agent terminal
        const code = res.one_time_code || '849201';
        setOneTimeCode(code);
        setRedeemCode(code);
      } else if (res.decision === 'REVIEW') {
        setVerifyStatus('mismatched');
        setCaseAlert({
          caseId: res.case_id,
          reason: res.reason,
          requested: amount,
          stated: amtToSubmit,
        });
        if (onCaseCreated) onCaseCreated();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRedeem = async () => {
    if (!mandate || !redeemCode) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.redeemMandate({
        mandateId: mandate.mandate_id,
        code: redeemCode,
        actor: agentId,
      });
      setRedeemResult(res);
      setMandate((prev) => ({ ...prev, status: 'redeemed' }));

      // Fetch plain-language Bangla verified receipt
      try {
        const rcpt = await api.getReceipt(res.txn_id);
        setReceipt(rcpt);
      } catch {
        setReceipt({ unavailable: true, txn_id: res.txn_id });
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmCash = async () => {
    if (!mandate) return;
    setLoading(true);
    try {
      const res = await api.confirmCash({
        mandateId: mandate.mandate_id,
        cashReceived: Number(cashReceived),
      });
      setCashConfirmResult(res);
      if (res.flagged && onCaseCreated) {
        onCaseCreated();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatTimer = (sec) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div className="simulation-container">
      {error && (
        <div style={{ background: 'rgba(244, 63, 94, 0.15)', border: '1px solid #f43f5e', padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem', color: '#fb7185' }}>
          <strong>Notice:</strong> {error}
        </div>
      )}

      <div className="simulation-grid">
        {/* LEFT COLUMN: Agent Terminal */}
        <div className="glass-card">
          <div className="card-title-row">
            <h2 className="card-title">
              <span>🏪</span> Agent Point-of-Sale Terminal
            </h2>
            <span className="badge badge-low">upay Agent Interface</span>
          </div>

          <form onSubmit={handleRequestMandate}>
            <div className="form-group">
              <label className="form-label" htmlFor="user-id-input">Customer ID (গ্রাহক আইডি)</label>
              <input
                id="user-id-input"
                className="text-input"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                required
              />
              <div className="quick-buttons">
                <button
                  type="button"
                  className="chip-btn"
                  onClick={() => setUserId('U_42_000008')}
                >
                  👵 Rahima Begum (Assisted Allowance)
                </button>
                <button
                  type="button"
                  className="chip-btn"
                  onClick={() => setUserId('U_42_000123')}
                >
                  👤 User 000123 (Assisted)
                </button>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="agent-id-select">Agent Terminal ID</label>
              <select
                id="agent-id-select"
                className="select-input"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
              >
                <option value="A_000042">A_000042 (Sample High-Volume Agent)</option>
                <option value="A_000015">A_000015 (Sample High-Discrepancy Agent)</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="amount-input">Cash-Out Amount (উত্তোলনের পরিমাণ BDT)</label>
              <input
                id="amount-input"
                type="number"
                className="text-input"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
                min="100"
                max="25000"
              />
              <div className="quick-buttons">
                <button type="button" className="chip-btn" onClick={() => setAmount('1000')}>1,000</button>
                <button type="button" className="chip-btn" onClick={() => setAmount('3000')}>3,000</button>
                <button type="button" className="chip-btn" onClick={() => setAmount('5000')}>5,000</button>
              </div>
            </div>

            <button
              type="submit"
              className="btn-primary"
              disabled={loading}
              id="request-mandate-btn"
            >
              {loading ? 'Processing...' : '🚀 Step 1: Request Cash-Out Mandate'}
            </button>
          </form>

          {/* Mandate Status Display */}
          {mandate && (
            <div style={{ marginTop: '1.25rem', padding: '1rem', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--text-dim)' }}>Mandate ID:</span>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{mandate.mandate_id.slice(0, 18)}...</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                <span style={{ color: 'var(--text-dim)' }}>Status:</span>
                <span className={`badge ${mandate.status === 'redeemed' ? 'badge-low' : mandate.status === 'active' ? 'badge-low' : 'badge-med'}`}>
                  {mandate.status.toUpperCase()}
                </span>
              </div>
            </div>
          )}

          {/* Code Reveal when Verified Active */}
          {mandate && mandate.status === 'active' && oneTimeCode && (
            <div className="mandate-banner">
              <div style={{ fontSize: '0.8rem', color: '#10b981', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '0.05em' }}>
                ✓ Customer Verified • One-Time Code Issued
              </div>
              <div className="code-display" id="revealed-code">{oneTimeCode}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                Valid for single use with Agent {agentId} • Expires in {formatTimer(timeLeftSec)}
              </div>
              <div className="ttl-bar">
                <div className="ttl-progress" style={{ width: `${(timeLeftSec / 900) * 100}%` }}></div>
              </div>

              <div style={{ marginTop: '1rem' }}>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={handleRedeem}
                  id="redeem-mandate-btn"
                  disabled={loading}
                >
                  💵 Step 3: Redeem Code & Disburse Cash
                </button>
              </div>
            </div>
          )}

          {/* Redemption Outcome */}
          {redeemResult && (
            <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '8px' }}>
              <div style={{ fontWeight: 700, color: '#10b981', marginBottom: '0.25rem' }}>
                ✓ Cash Disbursed Successfully!
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-dim)' }}>
                Transaction #{redeemResult.txn_id} • Amount: {redeemResult.amount} BDT • Fee: {redeemResult.fee} BDT
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Customer Phone Simulator */}
        <div className="glass-card">
          <div className="card-title-row">
            <h2 className="card-title">
              <span>📱</span> Customer Phone Simulator
            </h2>
            <span className="badge badge-med">USSD / IVR / Voice</span>
          </div>

          <div className="phone-chassis">
            <div className="phone-screen">
              <div>
                <div className="phone-header">
                  <span>upay Secure Mandate</span>
                  <span>100% 🔋</span>
                </div>

                {mandate ? (
                  <div>
                    <div className="phone-prompt-box">
                      <strong>সাথী ভেরিফিকেশন:</strong>
                      <p style={{ marginTop: '0.35rem' }}>
                        এজেন্ট আপনার অ্যাকাউন্ট থেকে <strong>{Number(amount).toLocaleString('bn-BD')} টাকা</strong> উত্তোলনের অনুরোধ করেছেন। আপনি কত টাকা তুলতে চান?
                      </p>
                      <button
                        type="button"
                        className="listen-btn"
                        onClick={() => playPromptAudio(`সাথী ভেরিফিকেশন। এজেন্ট আপনার অ্যাকাউন্ট থেকে ${amount} টাকা তোলার অনুরোধ করেছেন। আপনি কত টাকা তুলতে চান?`)}
                      >
                        <span>{isPlayingAudio ? '🔊 বাজছে...' : '🔈 বাংলায় শুনুন (Listen Voice)'}</span>
                      </button>
                    </div>

                    <div className="keypad-display" id="keypad-input-display">
                      {statedAmount || '0'} <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>BDT</span>
                    </div>

                    <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.75rem' }}>
                      <button
                        type="button"
                        className="chip-btn"
                        style={{ flex: 1, borderColor: '#10b981', color: '#10b981' }}
                        onClick={() => {
                          setStatedAmount(amount);
                          handleVerify(amount);
                        }}
                        id="preset-match-btn"
                      >
                        ✓ Enter {amount} (Match)
                      </button>
                      <button
                        type="button"
                        className="chip-btn"
                        style={{ flex: 1, borderColor: '#f43f5e', color: '#f43f5e' }}
                        onClick={() => {
                          const mismatchVal = String(Number(amount) - 500);
                          setStatedAmount(mismatchVal);
                          handleVerify(mismatchVal);
                        }}
                        id="preset-mismatch-btn"
                      >
                        ⚠ Enter {Number(amount) - 500} (Mismatch)
                      </button>
                    </div>

                    <div className="keypad-grid">
                      {['1', '2', '3', '4', '5', '6', '7', '8', '9', 'CLEAR', '0', 'BACK'].map((key) => (
                        <button
                          key={key}
                          type="button"
                          className="key-btn"
                          onClick={() => handleKeypadPress(key)}
                          id={`key-${key.toLowerCase()}`}
                        >
                          {key === 'BACK' ? '⌫' : key === 'CLEAR' ? 'C' : key}
                        </button>
                      ))}
                    </div>

                    <div style={{ marginTop: '0.75rem' }}>
                      <button
                        type="button"
                        className="btn-primary"
                        style={{ width: '100%', padding: '0.65rem' }}
                        onClick={() => handleVerify()}
                        disabled={!statedAmount || loading}
                        id="submit-stated-amount-btn"
                      >
                        Step 2: Submit Stated Amount
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
                    <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>📲</div>
                    <p style={{ fontFamily: 'var(--font-bangla)', fontSize: '1.05rem', color: 'var(--text-dim)' }}>
                      অপেক্ষারত... এজেন্ট টার্মিনাল থেকে ক্যাশ-আউট অনুরোধ পাঠান।
                    </p>
                    <p style={{ fontSize: '0.75rem', marginTop: '0.5rem' }}>
                      Waiting for mandate request from agent terminal...
                    </p>
                  </div>
                )}
              </div>

              {/* Status Outcome inside Phone Screen */}
              {verifyStatus === 'matched' && (
                <div style={{ background: 'rgba(16, 185, 129, 0.2)', border: '1px solid #10b981', padding: '0.6rem', borderRadius: '8px', fontSize: '0.8rem', textAlign: 'center', color: '#34d399', fontFamily: 'var(--font-bangla)' }}>
                  ✓ পরিমাণ মিলেছে! এজেন্ট টার্মিনালে ওয়ান-টাইম কোড পাঠানো হয়েছে।
                </div>
              )}

              {verifyStatus === 'mismatched' && caseAlert && (
                <div style={{ background: 'rgba(244, 63, 94, 0.2)', border: '1px solid #f43f5e', padding: '0.6rem', borderRadius: '8px', fontSize: '0.8rem', color: '#fda4af', fontFamily: 'var(--font-bangla)' }}>
                  <strong>⚠ সতর্কতা: পর্যালোচনায় পাঠানো হয়েছে!</strong>
                  <p style={{ fontSize: '0.75rem', marginTop: '0.2rem' }}>
                    এজেন্ট অনুরোধ: {caseAlert.requested} টাকা | আপনি লিখেছেন: {caseAlert.stated} টাকা।
                  </p>
                  <p style={{ fontSize: '0.72rem', color: '#cbd5e1', marginTop: '0.2rem' }}>
                    কেস #{caseAlert.caseId} অ্যানালিস্ট রিভিউ কিউতে জমা হয়েছে।
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* BOTTOM SECTION: Digital Receipt & Post-Cash Confirmation */}
      {receipt && (
        <div style={{ marginTop: '1.5rem' }} className="glass-card">
          <div className="card-title-row">
            <h2 className="card-title">
              <span>🧾</span> Digital Bangla Receipt {receipt.unavailable ? '(Unavailable)' : '(Runtime Verified)'}
            </h2>
            <span className={`badge ${receipt.unavailable ? 'badge-med' : 'badge-low'}`}>
              {receipt.unavailable ? 'Memory Lookup Pending' : '✓ Source: runtime memory, not a database record'}
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>
            <div className="receipt-card">
              <div className="receipt-header">
                <span style={{ fontWeight: 700, color: receipt.unavailable ? 'var(--text-muted)' : 'var(--emerald)' }}>
                  upay ডিজিটাল ক্যাশ-আউট রশিদ
                </span>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
                  ট্রানজ্যাকশন #{receipt.txn_id}{receipt.ts ? ` • ${receipt.ts}` : ''}
                </span>
              </div>
              <div className="receipt-text" style={{ color: receipt.unavailable ? 'var(--text-dim)' : undefined }}>
                {receipt.unavailable
                  ? 'রশিদ প্রস্তুতি প্রক্রিয়াধীন অথবা লেনদেন সংযোগহীন (Receipt unavailable: runtime memory lookup pending).'
                  : receipt.receipt_text_bn}
              </div>
              {!receipt.unavailable && (
                <div style={{ fontSize: '0.75rem', color: 'var(--cyan)', marginTop: '0.5rem' }}>
                  Source: {receipt.provenance || 'runtime memory, not a database record'}
                </div>
              )}
              <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem', alignItems: 'center' }}>
                {!receipt.unavailable && (
                  <button
                    type="button"
                    className="listen-btn"
                    onClick={() => playPromptAudio(receipt.receipt_text_bn)}
                  >
                    🔈 রশিদ শুনুন (Listen to Receipt in Bangla)
                  </button>
                )}
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {receipt.unavailable
                    ? 'Notice: Receipt lookup pending runtime transaction memory. No database validation claimed.'
                    : 'Anti-Hallucination Guard: Validated numeric tokens match runtime memory, not a database record.'}
                </span>
              </div>
            </div>

            {/* Cash Received Confirmation */}
            <div style={{ background: 'rgba(30, 41, 59, 0.5)', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
              <h3 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-main)' }}>
                নগদ অর্থ প্রাপ্তি নিশ্চিতকরণ (Confirm Cash)
              </h3>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginBottom: '0.75rem' }}>
                গ্রাহক এজেন্ট থেকে কত টাকা হাতে পেলেন তা রিপোর্ট করুন (প্রত্যাশিত: ২,৯৫৫ টাকা):
              </p>

              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
                <input
                  type="number"
                  className="text-input"
                  style={{ width: '120px' }}
                  value={cashReceived}
                  onChange={(e) => setCashReceived(e.target.value)}
                />
                <button
                  type="button"
                  className="btn-primary"
                  style={{ padding: '0.5rem 0.75rem', fontSize: '0.85rem' }}
                  onClick={handleConfirmCash}
                  disabled={loading}
                >
                  নিশ্চিত করুন
                </button>
              </div>

              {cashConfirmResult && (
                <div style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>
                  {cashConfirmResult.flagged ? (
                    <div style={{ color: '#fb7185', background: 'rgba(244,63,94,0.1)', padding: '0.5rem', borderRadius: '4px' }}>
                      ⚠ সতর্কতা: নগদ অর্থের ব্যবধান {cashConfirmResult.gap} টাকা! সীমা (৬০ টাকা) অতিক্রম করায় এজেন্টের বিরুদ্ধে সিগন্যাল তৈরি হয়েছে।
                    </div>
                  ) : (
                    <div style={{ color: '#34d399', background: 'rgba(16,185,129,0.1)', padding: '0.5rem', borderRadius: '4px' }}>
                      ✓ সঠিক অর্থ পেয়েছেন। কোনো অনাকাঙ্ক্ষিত ব্যবধান নেই।
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
