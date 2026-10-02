import { useState, useEffect } from 'react';
import { api } from '../api';

const DEMO_AGENTS = [
  { id: 'A_000015', label: 'A_000015 (Sample High-Discrepancy Agent)' },
  { id: 'A_000016', label: 'A_000016 (Sample Elevated-Risk Agent)' },
  { id: 'A_000042', label: 'A_000042 (Sample High-Volume Agent)' },
  { id: 'A_000100', label: 'A_000100 (Sample Standard Agent)' },
];

export default function AgentRiskBoard() {
  const [selectedAgent, setSelectedAgent] = useState('A_000015');
  const [riskData, setRiskData] = useState(null);
  const [loading, setLoading] = useState(false);

  const loadRisk = async (agentId) => {
    setLoading(true);
    try {
      const data = await api.getAgentRisk(agentId);
      setRiskData(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadRisk(selectedAgent); }, [selectedAgent]);

  const riskColor = (level) =>
    level === 'HIGH' ? '#f43f5e' : level === 'MED' ? '#f59e0b' : '#10b981';

  const riskBgColor = (level) =>
    level === 'HIGH' ? 'rgba(244,63,94,0.12)' : level === 'MED' ? 'rgba(245,158,11,0.12)' : 'rgba(16,185,129,0.12)';

  return (
    <div>
      <div className="card-title-row" style={{ marginBottom: '1.5rem' }}>
        <div>
          <h2 className="card-title">
            <span>🔍</span> Agent Anomaly Risk Board
          </h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
            Agent anomaly detection demonstration. illustrative sample, not a result. Placeholder risk profiles for supervisor review workflows.
          </p>
        </div>
        <span style={{ fontSize: '0.78rem', color: '#f59e0b', fontWeight: 600, padding: '0.3rem 0.7rem', background: 'rgba(245,158,11,0.1)', borderRadius: '999px', border: '1px solid rgba(245,158,11,0.3)' }}>
          illustrative sample, not a result
        </span>
      </div>

      <div className="simulation-grid">
        {/* Agent Selector Panel */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '0.95rem', marginBottom: '1rem' }}>Select Agent</h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginBottom: '1.25rem' }}>
            {DEMO_AGENTS.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setSelectedAgent(a.id)}
                style={{
                  padding: '0.75rem 1rem',
                  border: `1px solid ${selectedAgent === a.id ? 'rgba(16,185,129,0.5)' : 'var(--border-subtle)'}`,
                  borderRadius: '8px',
                  background: selectedAgent === a.id ? 'rgba(16,185,129,0.08)' : 'rgba(15,23,42,0.4)',
                  color: selectedAgent === a.id ? 'var(--text-main)' : 'var(--text-dim)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-sans)',
                  fontSize: '0.85rem',
                  transition: 'all 0.15s',
                }}
              >
                {a.label}
              </button>
            ))}
          </div>

          {riskData && (
            <div style={{
              background: riskBgColor(riskData.level),
              border: `1px solid ${riskColor(riskData.level)}40`,
              borderRadius: '12px',
              padding: '1.5rem',
              textAlign: 'center',
            }}>
              {/* Risk Gauge */}
              <div style={{
                fontSize: '3.5rem',
                fontFamily: 'var(--font-display)',
                fontWeight: 800,
                color: riskColor(riskData.level),
                lineHeight: 1,
              }}>
                {(riskData.risk * 100).toFixed(0)}%
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
                Sample Anomaly Score (illustrative sample, not a result)
              </div>

              <div style={{ margin: '1rem 0', background: 'rgba(255,255,255,0.08)', borderRadius: '9999px', height: '10px', overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${riskData.risk * 100}%`,
                  background: riskData.level === 'HIGH'
                    ? 'linear-gradient(90deg, #f59e0b, #f43f5e)'
                    : 'linear-gradient(90deg, #10b981, #06b6d4)',
                  borderRadius: '9999px',
                  transition: 'width 0.7s ease',
                }} />
              </div>

              <span className={`badge badge-${riskData.level === 'HIGH' ? 'high' : riskData.level === 'MED' ? 'med' : 'low'}`}
                style={{ fontSize: '1rem', padding: '0.35rem 1rem' }}
              >
                {riskData.level} RISK (SAMPLE)
              </span>

              <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Cohort: {riskData.peer_group || 'sample_cohort'}<br/>
                Profile: {riskData.model_version || 'sample_template'} • illustrative sample, not a result
              </div>
            </div>
          )}
        </div>

        {/* Anomaly Evidence & Reasons */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '0.95rem', marginBottom: '1.25rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.75rem' }}>
            Sample Anomaly Indicators — {riskData?.agent_id || selectedAgent}
          </h3>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>Loading risk analysis...</div>
          ) : riskData?.reasons?.length > 0 ? (
            <div>
              {riskData.reasons.map((reason, _i) => (
                <div key={reason.feature} style={{
                  marginBottom: '1.1rem',
                  padding: '1rem',
                  background: 'rgba(15, 23, 42, 0.6)',
                  borderRadius: '10px',
                  border: `1px solid ${_i === 0 ? 'rgba(244,63,94,0.3)' : 'var(--border-subtle)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-main)' }}>
                      {reason.display_name || reason.feature}
                    </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.8rem',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                      background: 'rgba(244,63,94,0.15)',
                      color: '#fb7185',
                    }}>
                      Z={reason.z_score?.toFixed(2)}
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.82rem', marginBottom: '0.6rem' }}>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Agent Value: </span>
                      <strong style={{ color: '#f43f5e', fontFamily: 'var(--font-mono)' }}>{reason.value}x</strong>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Peer Median: </span>
                      <strong style={{ color: '#06b6d4', fontFamily: 'var(--font-mono)' }}>{reason.peer_median}x</strong>
                    </div>
                  </div>

                  {/* Comparison bar */}
                  <div style={{ position: 'relative', height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', marginTop: '0.3rem' }}>
                    <div style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      height: '100%',
                      width: `${Math.min((reason.peer_median / (reason.value || 1)) * 60, 100)}%`,
                      background: '#06b6d4',
                      borderRadius: '3px',
                    }} />
                    <div style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      height: '100%',
                      width: `${Math.min(Math.min(reason.value / (reason.value || 1), 1) * 95, 100)}%`,
                      background: '#f43f5e',
                      borderRadius: '3px',
                      opacity: 0.7,
                    }} />
                  </div>
                </div>
              ))}

              <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'rgba(30,41,59,0.4)', borderRadius: '8px', fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                <strong style={{ color: 'var(--text-dim)' }}>Notice:</strong> illustrative sample, not a result. Indicators shown are placeholder profiles for demonstration of supervisor review interface; not live model inference.
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: '2rem', marginBottom: '0.5rem' }}>✅</div>
              <p>No anomaly signals detected. Agent behavior within normal peer range.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
