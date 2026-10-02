import { useState, useEffect } from 'react';
import { api } from '../api';

export default function OutreachList() {
  const [outreachData, setOutreachData] = useState(null);
  const [selectedUser, setSelectedUser] = useState(null);
  const [scoreData, setScoreData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getOutreachList().then(setOutreachData).catch(console.error);
  }, []);

  const loadUserScore = async (userId) => {
    setLoading(true);
    setSelectedUser(userId);
    try {
      const data = await api.getUserAssistedScore(userId);
      setScoreData(data);
    } catch (err) {
      console.error('Failed to load user score:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="card-title-row" style={{ marginBottom: '1.5rem' }}>
        <div>
          <h2 className="card-title">
            <span>👥</span> Assisted User Outreach List
          </h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
            Proactive outreach demonstration list. illustrative sample, not a result. Placeholder score profiles for workflow review.
          </p>
        </div>
        <span style={{ fontSize: '0.78rem', color: '#f59e0b', fontWeight: 600, padding: '0.3rem 0.7rem', background: 'rgba(245,158,11,0.1)', borderRadius: '999px', border: '1px solid rgba(245,158,11,0.3)' }}>
          illustrative sample, not a result
        </span>
      </div>

      <div className="simulation-grid">
        {/* Outreach Ranked List */}
        <div className="glass-card" style={{ padding: 0 }}>
          <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-subtle)' }}>
            <h3 style={{ fontSize: '0.95rem', fontFamily: 'var(--font-display)' }}>Ranked Outreach Candidates</h3>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
              Sample candidates for proactive mandate onboarding (illustrative sample, not a result)
            </p>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Customer ID</th>
                <th>Sample Score</th>
                <th>Primary Agent</th>
                <th>Monthly Vol.</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {outreachData?.items?.map((item, idx) => (
                <tr
                  key={item.user_id}
                  style={{
                    cursor: 'pointer',
                    background: selectedUser === item.user_id ? 'rgba(16, 185, 129, 0.08)' : undefined,
                  }}
                  onClick={() => loadUserScore(item.user_id)}
                >
                  <td>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: idx < 2 ? 'var(--amber)' : 'var(--text-dim)' }}>
                      #{idx + 1}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{item.user_id}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <div style={{
                        width: `${item.assisted_score * 60}px`,
                        height: '6px',
                        background: `linear-gradient(90deg, #10b981, #f59e0b)`,
                        borderRadius: '9999px',
                        minWidth: '4px',
                      }} />
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#f59e0b' }}>
                        {(item.assisted_score * 100).toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td style={{ color: 'var(--text-dim)', fontSize: '0.85rem' }}>{item.primary_agent_id}</td>
                  <td style={{ fontSize: '0.85rem' }}>{item.monthly_volume_bdt?.toLocaleString()} BDT</td>
                  <td>
                    <button
                      type="button"
                      className="chip-btn"
                      style={{ borderColor: 'var(--emerald)', color: 'var(--emerald)' }}
                      onClick={(e) => { e.stopPropagation(); loadUserScore(item.user_id); }}
                    >
                      🔍 View Factors
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Behavioral Explanation Panel */}
        <div className="glass-card">
          {scoreData ? (
            <div>
              <div style={{ marginBottom: '1.25rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1.05rem' }}>
                    Sample Profile — {scoreData.user_id}
                  </h3>
                  <span className="badge badge-med">
                    illustrative sample, not a result
                  </span>
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '0.35rem' }}>
                  Profile template: {scoreData.model_version || 'sample'} • illustrative sample, not a result
                </p>
              </div>

              {/* Big Score Gauge */}
              <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
                <div style={{
                  fontSize: '3rem',
                  fontFamily: 'var(--font-display)',
                  fontWeight: 800,
                  color: scoreData.score > 0.75 ? '#f59e0b' : '#10b981',
                  lineHeight: 1,
                }}>
                  {(scoreData.score * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
                  Illustrative Sample Score (illustrative sample, not a result)
                </div>
                <div style={{ marginTop: '0.75rem', background: 'rgba(255,255,255,0.05)', borderRadius: '9999px', height: '8px', overflow: 'hidden' }}>
                  <div style={{
                    height: '100%',
                    width: `${scoreData.score * 100}%`,
                    background: `linear-gradient(90deg, #10b981, #f59e0b, #f43f5e)`,
                    borderRadius: '9999px',
                    transition: 'width 0.6s ease',
                  }} />
                </div>
              </div>

              {/* Factor Breakdown */}
              <h4 style={{ fontSize: '0.8rem', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600, marginBottom: '0.75rem' }}>
                Sample Behavioral Factors (illustrative sample, not a result)
              </h4>

              {scoreData.top_reasons?.map((reason, _i) => (
                <div key={reason.feature} style={{
                  marginBottom: '1rem',
                  padding: '0.9rem',
                  background: 'rgba(15, 23, 42, 0.6)',
                  borderRadius: '8px',
                  border: '1px solid var(--border-subtle)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-dim)', fontWeight: 600 }}>
                      {reason.display_name || reason.feature}
                    </span>
                    <span className={`badge ${reason.direction === 'positive' ? 'badge-high' : 'badge-low'}`}>
                      Sample Weight {reason.sample_weight || reason.shap_impact || ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.82rem' }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Customer Value: </span>
                      <strong style={{ color: 'var(--text-main)', fontFamily: 'var(--font-mono)' }}>{reason.value}</strong>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Peer Median: </span>
                      <strong style={{ color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>{reason.peer_median}</strong>
                    </div>
                  </div>

                  {/* Visual bar for the value vs median */}
                  {typeof reason.value === 'number' && reason.value <= 1 && (
                    <div style={{ marginTop: '0.4rem', position: 'relative', height: '4px', background: 'rgba(255,255,255,0.08)', borderRadius: '2px' }}>
                      <div style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                        height: '100%',
                        width: `${Math.min(reason.value * 100, 100)}%`,
                        background: reason.direction === 'positive' ? '#f59e0b' : '#10b981',
                        borderRadius: '2px',
                      }} />
                      <div style={{
                        position: 'absolute',
                        left: `${Math.min(reason.peer_median * 100, 100)}%`,
                        top: '-3px',
                        width: '2px',
                        height: '10px',
                        background: '#06b6d4',
                        borderRadius: '1px',
                      }} />
                    </div>
                  )}
                </div>
              ))}

              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.5rem', padding: '0.5rem', background: 'rgba(255,255,255,0.02)', borderRadius: '4px' }}>
                ℹ illustrative sample, not a result. Placeholder features for interface demonstration; not a model inference result. No demographic features used.
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
              {loading ? (
                <div>Loading sample explanations...</div>
              ) : (
                <div>
                  <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>👥</div>
                  <p>Select a customer from the outreach list to view their sample behavioral profile (illustrative sample, not a result).</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
