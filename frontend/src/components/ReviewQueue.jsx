import { useState, useEffect } from 'react';
import { api } from '../api';

export default function ReviewQueue() {
  const [cases, setCases] = useState([]);
  const [selectedCase, setSelectedCase] = useState(null);
  const [decisionNote, setDecisionNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState(null);

  const fetchCases = async () => {
    try {
      const data = await api.getCases();
      setCases(data.cases || []);
      if (!selectedCase && data.cases && data.cases.length > 0) {
        setSelectedCase(data.cases[0]);
      }
    } catch (err) {
      console.error('Failed to load review cases:', err);
    }
  };

  useEffect(() => {
    fetchCases();
  }, []);

  const handleDecision = async (decision) => {
    if (!selectedCase) return;
    setLoading(true);
    setActionMessage(null);
    try {
      const res = await api.decideCase({
        caseId: selectedCase.case_id,
        decision,
        reviewer: 'analyst_lead',
        note: decisionNote || `Decision ${decision.toUpperCase()} by human supervisor.`,
      });

      setActionMessage({
        type: 'success',
        text: `Case #${res.case_id} successfully marked as ${res.decision.toUpperCase()}. Recorded in tamper-evident audit log.`,
      });

      // Refresh cases list
      await fetchCases();
      setSelectedCase((prev) => prev ? { ...prev, status: decision } : null);
      setDecisionNote('');
    } catch (err) {
      setActionMessage({ type: 'error', text: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="review-queue-container">
      <div className="card-title-row">
        <div>
          <h2 className="card-title">
            <span>🛡️</span> Supervisor Review Queue (Human-in-the-Loop)
          </h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
            Responsible AI Principle: The AI never denies or penalizes automatically. High-risk mismatches are queued for human review.
          </p>
        </div>
        <button
          type="button"
          className="api-toggle-btn"
          onClick={fetchCases}
        >
          🔄 Refresh Cases
        </button>
      </div>

      {actionMessage && (
        <div style={{
          padding: '0.75rem 1rem',
          borderRadius: '8px',
          marginBottom: '1rem',
          background: actionMessage.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
          border: `1px solid ${actionMessage.type === 'success' ? '#10b981' : '#f43f5e'}`,
          color: actionMessage.type === 'success' ? '#34d399' : '#fb7185',
        }}>
          {actionMessage.text}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '1.5rem' }}>
        {/* Cases Table */}
        <div className="glass-card" style={{ padding: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Customer</th>
                <th>Agent</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {cases.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                    No pending review cases.
                  </td>
                </tr>
              ) : (
                cases.map((c) => {
                  const isSelected = selectedCase?.case_id === c.case_id;
                  return (
                    <tr
                      key={c.case_id}
                      style={{ cursor: 'pointer', background: isSelected ? 'rgba(16, 185, 129, 0.08)' : undefined }}
                      onClick={() => setSelectedCase(c)}
                    >
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--cyan)' }}>
                        #{c.case_id}
                        {c.is_sample && (
                          <span className="badge badge-med" style={{ fontSize: '0.65rem', marginLeft: '0.3rem', padding: '0.1rem 0.35rem' }}>
                            SAMPLE
                          </span>
                        )}
                      </td>
                      <td>{c.user_id}</td>
                      <td>{c.agent_id}</td>
                      <td style={{ fontSize: '0.8rem', maxWidth: '220px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {c.reason}
                      </td>
                      <td>
                        <span className={`badge ${c.status === 'approved' ? 'badge-low' : c.status === 'denied' ? 'badge-high' : 'badge-med'}`}>
                          {c.status?.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="chip-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedCase(c);
                          }}
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Case Detail & Adjudication Panel */}
        <div className="glass-card">
          {selectedCase ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.75rem' }}>
                <h3 style={{ fontSize: '1.1rem', fontFamily: 'var(--font-display)' }}>
                  Case #{selectedCase.case_id} Evidence
                </h3>
                <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                  {selectedCase.is_sample && (
                    <span className="badge badge-med" style={{ fontSize: '0.75rem' }}>
                      illustrative sample, not a result
                    </span>
                  )}
                  <span className={`badge ${selectedCase.status === 'open' ? 'badge-med' : selectedCase.status === 'approved' ? 'badge-low' : 'badge-high'}`}>
                    {selectedCase.status?.toUpperCase()}
                  </span>
                </div>
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600 }}>Reason for Flag:</div>
                <div style={{ fontSize: '0.9rem', color: '#f8fafc', marginTop: '0.2rem', padding: '0.6rem', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                  {selectedCase.reason}
                </div>
              </div>

              {/* Structured Evidence Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '0.75rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>AGENT REQUESTED</div>
                  <div style={{ fontSize: '1.25rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#f43f5e' }}>
                    {selectedCase.evidence?.requested_amount ?? selectedCase.evidence?.expected_amount ?? '—'} BDT
                  </div>
                </div>

                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '0.75rem', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>CUSTOMER STATED</div>
                  <div style={{ fontSize: '1.25rem', fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#38bdf8' }}>
                    {selectedCase.evidence?.stated_amount ?? selectedCase.evidence?.cash_received ?? '—'} BDT
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: '1.25rem', fontSize: '0.82rem', color: 'var(--text-dim)' }}>
                <div>• Customer ID: <strong style={{ color: 'var(--text-main)' }}>{selectedCase.user_id}</strong></div>
                <div>• Agent Terminal: <strong style={{ color: 'var(--text-main)' }}>{selectedCase.agent_id}</strong></div>
                <div>• Provenance: <strong style={{ color: selectedCase.is_sample ? '#f59e0b' : '#10b981' }}>{selectedCase.is_sample ? 'illustrative sample, not a result' : 'Runtime Audit Record'}</strong></div>
                {selectedCase.evidence?.gap != null && (
                  <div>• Discrepancy Gap: <strong style={{ color: '#f43f5e' }}>{selectedCase.evidence.gap} BDT</strong></div>
                )}
                {selectedCase.evidence?.mode && (
                  <div>• Verification Mode: <strong style={{ color: 'var(--text-main)' }}>{selectedCase.evidence.mode}</strong></div>
                )}
              </div>

              {/* Human Decision Controls */}
              {selectedCase.status === 'open' && (
                <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '1rem' }}>
                  <label className="form-label" htmlFor="decision-note">Supervisor Reviewer Note</label>
                  <input
                    id="decision-note"
                    className="text-input"
                    placeholder="Enter verification notes (e.g. called customer, confirmed 3000 BDT)..."
                    value={decisionNote}
                    onChange={(e) => setDecisionNote(e.target.value)}
                    style={{ marginBottom: '0.75rem' }}
                  />

                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      type="button"
                      className="btn-primary"
                      style={{ flex: 1, padding: '0.65rem' }}
                      onClick={() => handleDecision('approved')}
                      disabled={loading}
                    >
                      ✓ Approve Mandate
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      style={{ flex: 1, padding: '0.65rem' }}
                      onClick={() => handleDecision('denied')}
                      disabled={loading}
                    >
                      ✕ Deny & Block
                    </button>
                    <button
                      type="button"
                      className="chip-btn"
                      style={{ padding: '0.65rem', borderColor: '#f59e0b', color: '#fbbf24' }}
                      onClick={() => handleDecision('escalated')}
                      disabled={loading}
                    >
                      🚩 Escalate
                    </button>
                  </div>
                </div>
              )}

              {selectedCase.status !== 'open' && (
                <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.03)', borderRadius: '6px', fontSize: '0.85rem' }}>
                  <div style={{ color: 'var(--text-dim)' }}>Adjudicated by: <strong>{selectedCase.reviewer || 'analyst_lead'}</strong></div>
                  <div style={{ color: 'var(--text-dim)', marginTop: '0.2rem' }}>Note: <em>"{selectedCase.note || 'Resolved by supervisor'}"</em></div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
              Select a case from the queue to view evidence and adjudicate.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
