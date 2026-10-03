import { useState } from 'react';
import { api } from '../api';
const principals = {
  demo_agent: { label: 'Agent terminal', pin: '1234' },
  demo_customer: { label: 'Customer channel', pin: '5678' },
  demo_analyst: { label: 'Human analyst', pin: '9012' },
};
export default function DemoLogin({ session, onLogout }) {
  const [principal, setPrincipal] = useState('demo_agent');
  const [pin, setPin] = useState('1234');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const login = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await api.login({ principal, pin }); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return <section className="glass-card login-card">
    <div><strong>Synthetic demo login</strong><p>Public fixture PINs: agent 1234 · customer 5678 · analyst 9012.</p>
      <p>{session ? `${session.role} · ${session.subject}` : 'Sign in to start. Switch roles to demonstrate separate channels.'}</p></div>
    <form onSubmit={login} className="login-form">
      <label>Demo role<select value={principal} onChange={(e) => {
        setPrincipal(e.target.value); setPin(principals[e.target.value].pin);
      }}>{Object.entries(principals).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label>
      <label>Public demo PIN<input value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" /></label>
      <button disabled={busy} type="submit" className="primary-btn">{busy ? 'Signing in…' : 'Sign in / switch role'}</button>
      {session && <button type="button" onClick={onLogout} className="chip-btn">Sign out</button>}
    </form>{error && <p role="alert" className="error-box">{error}</p>}
  </section>;
}
