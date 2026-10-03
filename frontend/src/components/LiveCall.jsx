import { useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';

const LIVE = ['queued', 'ringing', 'in_progress'];

const callLabel = {
  queued: 'Placing call…', ringing: 'Ringing customer…', in_progress: 'Customer is on the call',
  verified: 'Customer confirmed the amount', not_verified: 'Customer did not confirm',
  no_answer: 'No answer', failed: 'Call failed',
};
const callTone = {
  verified: 'badge-success', not_verified: 'badge-error', no_answer: 'badge-warning', failed: 'badge-error',
};

const bandTone = { low: 'badge-success', medium: 'badge-warning', high: 'badge-error' };
const stepUpText = {
  keypad_or_call: 'App keypad or phone call',
  call_required: 'Phone call to registered number required',
  call_and_review: 'Phone call required + analyst review case opened',
};

export function RiskCard({ risk }) {
  if (!risk) return null;
  const pct = Math.round(risk.score * 100);
  return (
    <div className="flex flex-col gap-2 border-t border-base-300 pt-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">Real-time risk</h4>
        <span className={`badge badge-sm ${bandTone[risk.band] || 'badge-ghost'}`}>{risk.band}</span>
      </div>
      <div className="flex items-center gap-2">
        <progress className="progress w-full" value={pct} max="100" aria-label="Risk score" />
        <span className="font-mono text-xs">{pct}</span>
      </div>
      <p className="text-xs"><strong>Verification:</strong> {stepUpText[risk.step_up] || risk.step_up}</p>
      {/* Signal details stay with analysts so agents cannot tune requests around them. */}
      <p className="muted">Risk sets verification strength only. It never approves or denies a cash-out.</p>
    </div>
  );
}

export function AgentCallPanel({ mandateId, status, onVerified, onNotVerified, busy }) {
  const [call, setCall] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!call || !LIVE.includes(call.status)) return undefined;
    let live = true;
    const timer = setInterval(async () => {
      try {
        const next = await api.getCall(mandateId);
        if (!live) return;
        setCall(next);
        if (next.status === 'verified') onVerified();
        if (next.status === 'not_verified') onNotVerified();
      } catch { /* keep polling */ }
    }, 2000);
    return () => { live = false; clearInterval(timer); };
  }, [call, mandateId, onVerified, onNotVerified]);

  const place = async () => {
    setError('');
    try { setCall(await api.placeCall(mandateId)); } catch (err) { setError(err.message); }
  };
  const canCall = mandateId && status === 'requested' && !(call && LIVE.includes(call.status));

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm opacity-80">The server calls the customer&apos;s <strong>registered</strong> phone. The prompt never says the amount; the customer types it on their own keypad.</p>
      <button className="btn btn-primary w-full sm:w-auto" disabled={busy || !canCall} onClick={place}>
        <Icon name="phone" className="size-4" />Call customer to confirm
      </button>
      {call && (
        <div className="flex flex-wrap items-center gap-2 rounded-box bg-base-200 p-3 text-sm">
          {LIVE.includes(call.status) && <span className="loading loading-ring loading-sm text-primary" />}
          <span className={`badge ${callTone[call.status] || 'badge-info'}`}>{call.status.replace('_', ' ')}</span>
          <span>{callLabel[call.status] || call.status}</span>
          <span className="muted ml-auto">{call.provider === 'twilio' ? `Live call · ${call.to}` : 'Simulated handset'}</span>
        </div>
      )}
      {error && <div role="alert" className="alert alert-error alert-soft text-sm">{error}</div>}
    </div>
  );
}

const dialKeys = [
  ['1', '১'], ['2', '২'], ['3', '৩'], ['4', '৪'], ['5', '৫'], ['6', '৬'],
  ['7', '৭'], ['8', '৮'], ['9', '৯'], ['*', ''], ['0', '০'], ['#', ''],
];

export function IncomingCall({ mandateId, onFinished }) {
  const [incoming, setIncoming] = useState(null);
  const [answered, setAnswered] = useState(false);
  const [digits, setDigits] = useState('');
  const [spoken, setSpoken] = useState([]);
  const [ended, setEnded] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (answered) return undefined;
    let live = true;
    const poll = async () => {
      try {
        const { calls } = await api.getIncomingCalls();
        if (live) setIncoming(calls[0] || null);
      } catch { /* offline or signed out */ }
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => { live = false; clearInterval(timer); };
  }, [answered]);

  const send = async () => {
    setError('');
    try {
      const result = await api.answerSimulatedCall({ callId: incoming.call_id, digits });
      setSpoken(result.spoken_bn); setDigits('');
      if (result.call_ended) {
        setEnded(true);
        try {
          const call = await api.getCall(incoming.mandate_id);
          onFinished(call.status);
        } catch { onFinished(null); }
      }
    } catch (err) { setError(err.message); }
  };
  const press = (key) => {
    if (key === '#') { send(); return; }
    if (key !== '*') setDigits((prev) => (prev + key).slice(0, 8));
  };

  if (!incoming && !answered) {
    return <p className="muted">No incoming call. When the agent taps “Call customer”, the phone rings here{mandateId ? '' : ' (simulated handset)'}.</p>;
  }

  return (
    <div className="mx-auto w-full max-w-xs rounded-[1.75rem] border-4 border-neutral bg-base-100 p-4 shadow-sm">
      <div className="text-center">
        <div className="text-xs opacity-60">{ended ? 'Call ended' : answered ? 'On call' : 'Incoming call'}</div>
        <div lang="bn" className="text-lg font-semibold">সাথী নিরাপত্তা কল</div>
        {!answered && <div className="muted">Agent {incoming.agent_id}</div>}
      </div>
      {!answered ? (
        <div className="mt-4 flex justify-center gap-6">
          <button className="btn btn-circle btn-success btn-lg" aria-label="Answer call" onClick={() => setAnswered(true)}>
            <Icon name="phone" />
          </button>
        </div>
      ) : (
        <>
          <p lang="bn" className="mt-3 rounded-box bg-base-200 p-2 text-sm leading-relaxed">
            {spoken.length ? spoken.join(' ') : incoming.prompt_bn}
          </p>
          {!ended && <>
            <div className="mt-3 rounded-box border border-base-300 p-2 text-center font-mono text-2xl tracking-widest" aria-live="polite">{digits || ' '}</div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {dialKeys.map(([key, bn]) => (
                <button key={key} type="button" className="btn btn-ghost h-12 flex-col gap-0 bg-base-200" onClick={() => press(key)}>
                  <span className="text-lg leading-none">{key}</span>
                  {bn && <span lang="bn" className="text-[10px] leading-none opacity-60">{bn}</span>}
                </button>
              ))}
            </div>
            <p className="muted mt-2">Type the amount, then press #. Press # alone if you did not ask for this.</p>
          </>}
        </>
      )}
      {error && <div role="alert" className="alert alert-error alert-soft mt-2 text-xs">{error}</div>}
    </div>
  );
}

export function SmsInbox() {
  const [items, setItems] = useState(null);
  useEffect(() => {
    let live = true;
    const load = () => api.getNotifications().then((v) => { if (live) setItems(v.items); }).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    return () => { live = false; clearInterval(timer); };
  }, []);
  return (
    <div className="flex flex-col gap-2">
      <h4 className="flex items-center gap-2 text-sm font-semibold"><Icon name="phone" className="size-4" />SMS inbox</h4>
      {!items?.length ? <p className="muted">No messages yet. A receipt SMS arrives after every cash-out.</p> : (
        <ul className="flex max-h-56 flex-col gap-2 overflow-y-auto">
          {items.map((m) => (
            <li key={m.notification_id} className="chat chat-start">
              <div className="chat-bubble chat-bubble-primary text-sm" lang="bn">{m.body}</div>
              <div className="chat-footer muted">{new Date(m.created_at).toLocaleTimeString()} · {m.status === 'simulated' ? 'simulated SMS' : m.status}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
