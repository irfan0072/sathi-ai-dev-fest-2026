export default function ArchitecturePage() {
  return (
    <div>
      <div className="card-title-row" style={{ marginBottom: '1.5rem' }}>
        <div>
          <h2 className="card-title">
            <span>💡</span> Problem, Solution & System Architecture
          </h2>
          <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)', marginTop: '0.2rem' }}>
            Current prototype limitations, simulation assumptions, and planned production controls.
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
        {/* Problem Statement */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1rem', color: '#fb7185' }}>
            ⚠ The Problem: PIN Disclosure Vulnerability
          </h3>
          <div style={{ fontSize: '0.88rem', lineHeight: 1.7, color: 'var(--text-dim)' }}>
            <p style={{ marginBottom: '0.75rem' }}>
              <strong style={{ color: '#f8fafc' }}>Simulation Scenario:</strong> Rahima Begum, 70, is modeled receiving an allowance via a mobile financial service. Because she cannot independently navigate complex USSD menus, she discloses her PIN to an agent — forfeiting account integrity.
            </p>
            <p style={{ marginBottom: '0.75rem' }}>
              This challenge affects elderly, rural, and low-literacy beneficiaries. In this research simulation, assisted-use is assumed to represent <strong style={{ color: '#f59e0b' }}>30-50% of rural transactions</strong> (simulation assumption, not measured upay production statistics).
            </p>
            <p style={{ fontFamily: 'var(--font-bangla)', fontSize: '1rem', padding: '0.75rem', background: 'rgba(244,63,94,0.1)', borderRadius: '8px', border: '1px solid rgba(244,63,94,0.3)', color: '#e2e8f0' }}>
              "রহিমা তার পিন নম্বর এজেন্টকে বলে দিলেন — কারণ তিনি একা USSD মেনু পরিচালনা করতে পারেন না।"
            </p>
          </div>
        </div>

        {/* Solution */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1rem', color: '#34d399' }}>
            ✓ Sathi: Scoped One-Time Mandate (No PIN Sharing)
          </h3>
          <div style={{ fontSize: '0.88rem', lineHeight: 1.7, color: 'var(--text-dim)' }}>
            <p style={{ marginBottom: '0.75rem' }}>
              Instead of disclosing her PIN, Rahima receives a <strong style={{ color: '#10b981' }}>verification prompt in Bangla</strong> (keypad). She states the withdrawal amount — if it matches the agent's request, a <strong>scoped one-time code</strong> is issued.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.75rem' }}>
              {[
                '🔒 Single-use, 15-min TTL, agent-bound code',
                '💬 Bangla keypad prototype; telecom channel integration remains future work',
                '🛡️ Amount mismatch → immediately flagged for human review',
                '📋 In-memory event audit log (durable persistence planned)',
                '🔍 Risk heuristics inform review; human supervisors decide',
              ].map((feat) => (
                <div key={feat} style={{ display: 'flex', gap: '0.5rem', padding: '0.4rem 0.6rem', background: 'rgba(16,185,129,0.08)', borderRadius: '6px', border: '1px solid rgba(16,185,129,0.15)', color: '#e2e8f0', fontSize: '0.83rem' }}>
                  {feat}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Mandate Lifecycle */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1rem' }}>
            🔄 Mandate Lifecycle
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {[
              { step: 'requested', desc: 'Agent requests cash-out for customer', color: '#06b6d4' },
              { step: 'verifying', desc: 'Customer enters Bangla amount through the simulated keypad', color: '#a855f7' },
              { step: 'active', desc: 'Amount matches → one-time code issued to agent terminal', color: '#10b981' },
              { step: 'redeemed', desc: 'Agent enters code → cash disbursed', color: '#10b981' },
              { step: 'review case', desc: 'Amount mismatch → human supervisor reviews evidence', color: '#f59e0b' },
              { step: 'expired / revoked', desc: 'TTL expired or customer revokes before redemption', color: '#64748b' },
            ].map((s) => (
              <div key={s.step} style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <div style={{ padding: '0.2rem 0.55rem', borderRadius: '4px', background: `${s.color}22`, border: `1px solid ${s.color}55`, color: s.color, fontFamily: 'var(--font-mono)', fontSize: '0.72rem', whiteSpace: 'nowrap', minWidth: '105px', textAlign: 'center', fontWeight: 600 }}>
                  {s.step}
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-dim)', paddingTop: '0.15rem' }}>{s.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Responsible AI & Planned Controls */}
        <div className="glass-card">
          <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1rem', color: '#06b6d4' }}>
            🛡️ Current Limitations & Planned Controls
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {[
              {
                principle: 'No Automated Penalties',
                detail: 'Signals inform supervisor triage only. No automated account blocking, agent penalty, or beneficiary denial.',
                icon: '👤',
              },
              {
                principle: 'Zero Demographic Inputs',
                detail: 'Demographic features (gender, age, region, urban/rural) are strictly excluded from model feature sets.',
                icon: '🚫',
              },
              {
                principle: 'Calibration Limitations (Planned Control)',
                detail: 'Calibration is an experimental objective on synthetic data. Real-world distribution shifts require ongoing validation; no calibration guarantees on live traffic.',
                icon: '📐',
              },
              {
                principle: 'Persistence & Auth (Current Limitation)',
                detail: 'Current prototype stores state in volatile memory without production authentication or cryptographic persistence. Approved scope: PostgreSQL transactions + signed scoped synthetic demo tokens, pending implementation.',
                icon: '📋',
              },
              {
                principle: 'Pilot Deployment Path',
                detail: 'All financial amounts, caps, and fee structures are simulation assumptions. Production deployment requires formal banking integration and regulatory compliance.',
                icon: '🚀',
              },
            ].map((p) => (
              <div key={p.principle} style={{ padding: '0.75rem', background: 'rgba(6,182,212,0.06)', borderRadius: '8px', border: '1px solid rgba(6,182,212,0.15)' }}>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.2rem' }}>
                  <span>{p.icon}</span>
                  <strong style={{ color: 'var(--text-main)', fontSize: '0.85rem' }}>{p.principle}</strong>
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', paddingLeft: '1.5rem' }}>{p.detail}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Architecture Overview */}
      <div className="glass-card" style={{ marginTop: '1.5rem' }}>
        <h3 style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', marginBottom: '1rem' }}>
          🏗️ Technical Architecture: INPUT → INTELLIGENCE → ACTION
        </h3>
        <div style={{ overflowX: 'auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.5rem', minWidth: '700px', alignItems: 'center' }}>
            {[
              { layer: 'Synthetic Data', desc: 'Simulation assumptions\nSynthetic population\nZero PII / live data', color: '#475569' },
              { layer: 'Feature Layer', desc: 'Behavioral aggregates\nLeakage assertion\n0 demographic inputs', color: '#6366f1' },
              { layer: 'AI Models', desc: 'Prototype classifiers\nBenchmark artifacts\nNo live inference claim', color: '#a855f7' },
              { layer: 'Policy Engine', desc: 'Deterministic rules\nConfigurable thresholds\nMandate lifecycle', color: '#06b6d4' },
              { layer: 'Human Review', desc: 'Supervisor console\nCase adjudication\nPrototype event log', color: '#10b981' },
            ].map((block, i) => (
              <div key={block.layer} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <div style={{
                  flex: 1,
                  padding: '0.75rem',
                  background: `${block.color}18`,
                  border: `1px solid ${block.color}40`,
                  borderRadius: '8px',
                  textAlign: 'center',
                }}>
                  <div style={{ color: block.color, fontSize: '0.8rem', fontWeight: 700, marginBottom: '0.3rem' }}>{block.layer}</div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dim)', whiteSpace: 'pre-line' }}>{block.desc}</div>
                </div>
                {i < 4 && <div style={{ color: 'var(--text-muted)', fontSize: '1.25rem' }}>→</div>}
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: '1rem', fontSize: '0.76rem', color: 'var(--text-muted)', textAlign: 'center' }}>
          Track 07 Submission — AI DEV FEST 2026 — DIU CPC × upay · All data and financial defaults are simulation assumptions. Not connected to actual upay production infrastructure.
        </div>
      </div>
    </div>
  );
}
