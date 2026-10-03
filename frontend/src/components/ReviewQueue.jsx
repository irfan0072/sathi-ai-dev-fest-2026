import { useState, useEffect } from 'react';
import { api } from '../api';
export default function ReviewQueue() {
  const [cases, setCases] = useState(null);
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setError(''); setCases(null); setSelected(null);
    try { const result = await api.getCases(); setCases(result.cases); }
    catch (err) { setError(err.message); }
  };
  useEffect(() => {
    let live = true;
    api.getCases().then((value) => { if (live) setCases(value.cases); }).catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, []);
  const decide = async (decision) => {
    setBusy(true); setError(''); setMessage('');
    try { const result = await api.decideCase({ caseId: selected.case_id, decision, note });
      await refresh(); setNote(''); setMessage(`Case #${result.case_id}: ${result.decision}. Recorded in durable database audit. No redemption granted.`);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  return <div><h2 className="card-title">Supervisor Review Queue</h2>
    <p>Actual synthetic runtime cases from PostgreSQL. Human decisions update cases and audit only; models and review decisions never grant cash-out.</p>
    <button className="chip-btn" onClick={refresh}>Refresh cases</button>
    {error && <p role="alert" className="error-box">Unavailable: {error}</p>}
    {message && <p role="status" className="result-box">{message}</p>}
    {cases === null ? <p>Unavailable — waiting for the database queue.</p> : <div className="glass-card">
      {cases.length === 0 ? <p>No review cases in the current database.</p> : <table className="data-table"><thead><tr><th>Case</th><th>Mandate</th><th>Reason</th><th>Status</th><th>Review</th></tr></thead>
        <tbody>{cases.map((item) => <tr key={item.case_id}><td>#{item.case_id}</td><td>{item.mandate_id}</td><td>{item.reason}</td><td>{item.status}</td><td><button className="chip-btn" onClick={() => { setSelected(item); setNote(''); }}>View case</button></td></tr>)}</tbody></table>}
    </div>}
    {selected && <div className="glass-card"><h3>Case #{selected.case_id} · {selected.reason}</h3>
      <pre>{JSON.stringify(selected.evidence, null, 2)}</pre>
      <label>Human review note<textarea value={note} onChange={(e) => setNote(e.target.value)} /></label>
      {['approved','denied','escalated'].map((decision) => <button className="chip-btn" key={decision} disabled={busy} onClick={() => decide(decision)}>{decision}</button>)}
    </div>}
  </div>;
}
