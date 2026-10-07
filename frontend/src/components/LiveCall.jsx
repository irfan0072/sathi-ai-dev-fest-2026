import { useEffect, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';
import { callStatus, checkNeeded, riskLevel } from '../copy';
import { phone } from '../ids';

const LIVE = ['queued', 'ringing', 'in_progress'];

const callLabel = callStatus;
const callTone = {
  verified: 'badge-success', not_verified: 'badge-error', no_answer: 'badge-warning', failed: 'badge-error',
};

const bandTone = { low: 'badge-success', medium: 'badge-warning', high: 'badge-error' };
const stepUpText = checkNeeded;

export function RiskCard({ risk }) {
  if (!risk) return null;
  const pct = Math.round(risk.score * 100);
  return (
    <div className="flex flex-col gap-2 border-t border-base-300 pt-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold">Safety check</h4>
        <span className={`badge badge-sm ${bandTone[risk.band] || 'badge-ghost'}`}>{riskLevel[risk.band] || risk.band}</span>
      </div>
      <div className="flex items-center gap-2">
        <progress className="progress w-full" value={pct} max="100" aria-label="Review score (not a fraud probability)" />
        <span className="font-mono text-xs">{pct}</span>
      </div>
      <p className="text-xs">{stepUpText[risk.step_up] || risk.step_up}</p>
      {/* Signal details stay with analysts so agents cannot tune requests around them. */}
      <p className="muted">This only decides how the customer confirms. It never approves or denies a cash-out by itself.</p>
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
      <p className="text-sm text-base-content/80">
        We call the customer&apos;s <strong>registered</strong> phone number. The call does not say the amount; the
        customer types it on their own phone.
      </p>
      <button
        className="btn btn-primary w-full focus-ring sm:w-auto"
        disabled={busy || !canCall}
        onClick={place}
      >
        <Icon name="phone" className="size-4" />
        Call customer to confirm
      </button>
      {call && (
        <div className="flex flex-wrap items-center gap-2 rounded-box bg-base-200 p-3 text-sm">
          {LIVE.includes(call.status) && (
            <span className="loading loading-ring loading-sm text-primary" />
          )}
          <span className={`badge ${callTone[call.status] || 'badge-info'}`}>
            {callLabel[call.status] || call.status}
          </span>
          <span className="muted ml-auto">
            {call.provider === 'simulated' ? 'Demo phone' : `Real call · ${call.to}`}
          </span>
        </div>
      )}
      {error && (
        <div role="alert" className="alert alert-error alert-soft text-sm">
          {error}
        </div>
      )}
    </div>
  );
}

const dialKeys = [
  ['1', '১'], ['2', '২'], ['3', '৩'], ['4', '৪'], ['5', '৫'], ['6', '৬'],
  ['7', '৭'], ['8', '৮'], ['9', '৯'], ['*', ''], ['0', '০'], ['#', ''],
];

export function IncomingCall({ onFinished }) {
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

  const [said, setSaid] = useState('');
  const [keypadOnly, setKeypadOnly] = useState(false);
  const send = async (speech = null, { confidence = 0.32, noInput = false } = {}) => {
    setError('');
    try {
      const result = noInput
        ? await api.answerSimulatedCall({ callId: incoming.call_id, digits: '', noInput: true })
        : speech
          ? await api.answerSimulatedSpeech({ callId: incoming.call_id, speech, confidence })
          : await api.answerSimulatedCall({ callId: incoming.call_id, digits });
      setSpoken(result.spoken_bn); setDigits('');
      if (result.input_mode === 'dtmf_only') setKeypadOnly(true);
      if (result.call_ended) {
        setEnded(true);
        if (!incoming.mandate_id) { onFinished(null); return; }
        try {
          const call = await api.getCall(incoming.mandate_id);
          onFinished(call.status);
        } catch { onFinished(null); }
      }
    } catch (err) { setError(err.message); }
  };
  const press = (key) => {
    if (key === '#') { send(); return; }
    // "*" alone is the explicit "I did not make this cash-out" key; it is not an amount digit.
    if (key === '*') { setDigits('*'); return; }
    setDigits((prev) => (prev === '*' ? key : prev + key).slice(0, 8));
  };

  if (!incoming && !answered) {
    return (
      <p className="muted">
        No call right now. After a cash-out, Sathi calls you here.
      </p>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xs rounded-[1.75rem] border-4 border-neutral bg-base-100 p-4 shadow-md">
      <div className="text-center">
        <div className="text-xs text-base-content/60">
          {ended ? 'Call ended' : answered ? 'On call' : 'Incoming call…'}
        </div>
        <div lang="bn" className="text-lg font-semibold">সাথী নিরাপত্তা কল</div>
        {!answered && <div className="muted">Agent {phone(incoming.agent_id)}</div>}
      </div>
      {!answered ? (
        <div className="mt-4 flex justify-center gap-6">
          <button
            className="btn btn-circle btn-success btn-lg focus-ring"
            aria-label="Answer call"
            onClick={() => setAnswered(true)}
          >
            <Icon name="phone" />
          </button>
        </div>
      ) : (
        <>
          <p
            lang={incoming?.language === 'en' ? 'en' : 'bn'}
            className="mt-3 rounded-box bg-base-200 p-2 text-sm leading-relaxed"
          >
            {spoken.length ? spoken.join(' ') : (incoming.prompt || incoming.prompt_bn)}
          </p>
          {!ended && (
            <>
              <div
                className="mt-3 rounded-box border border-base-300 p-2 text-center font-mono text-2xl tracking-widest"
                aria-live="polite"
              >
                {digits || ' '}
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2">
                {dialKeys.map(([key, bn]) => (
                  <button
                    key={key}
                    type="button"
                    className="btn btn-ghost h-12 flex-col gap-0 bg-base-200 focus-ring"
                    onClick={() => press(key)}
                  >
                    <span className="text-lg leading-none">{key}</span>
                    {bn && (
                      <span lang="bn" className="text-[10px] leading-none opacity-60">
                        {bn}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <p className="muted mt-2">
                Type the cash you got, then press #. If you did not make this cash-out, press * then #. Pressing only # does nothing.
              </p>
              {keypadOnly && <p className="muted mt-1 text-center text-[11px]" data-testid="keypad-only">Keypad only now: speech is switched off for this call.</p>}
              {!incoming.mandate_id && !keypadOnly && (
                <>
                  <p className="muted mt-1 text-center text-[11px]">9 # talk to a person · 8 # English / বাংলা</p>
                  <form
                    className="join mt-2 w-full"
                    onSubmit={(e) => { e.preventDefault(); if (said.trim()) { send(said.trim(), { confidence: 0.9 }); setSaid(''); } }}
                  >
                    <input
                      className="input input-bordered input-sm join-item w-full focus-ring"
                      placeholder="Or say it: আড়াই হাজার / tin hajar / 3000"
                      value={said}
                      onChange={(e) => setSaid(e.target.value)}
                      aria-label="Say your answer"
                    />
                    <button className="btn btn-sm join-item" type="submit">Say</button>
                  </form>
                  <div className="mt-1 grid grid-cols-2 gap-1">
                    <button type="button" className="btn btn-ghost btn-xs border-dashed border-base-300 focus-ring"
                      onClick={() => send('উম... আমি ঠিক বুঝতে পারছি না')}
                      title="Say something the call cannot understand. Twice sends the call to a supervisor.">
                      Mumble (unclear)
                    </button>
                    <button type="button" className="btn btn-ghost btn-xs border-dashed border-base-300 focus-ring"
                      onClick={() => send(null, { noInput: true })}
                      title="Stay silent. Sathi asks again once, then calls back later.">
                      Stay silent
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
      {error && (
        <div role="alert" className="alert alert-error alert-soft mt-2 text-xs">
          {error}
        </div>
      )}
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
      <h4 className="flex items-center gap-2 text-sm font-semibold"><Icon name="phone" className="size-4" />Messages</h4>
      {!items?.length ? <p className="muted">No messages yet. You get an SMS notice after every cash-out; it never shows the amount.</p> : (
        <ul className="flex max-h-56 flex-col gap-2 overflow-y-auto">
          {items.map((m) => (
            <li key={m.notification_id} className="chat chat-start">
              <div className="chat-bubble chat-bubble-primary text-sm" lang="bn">{m.body}</div>
              <div className="chat-footer muted">{new Date(m.created_at).toLocaleTimeString()} · {m.status === 'simulated' ? 'demo SMS' : m.status === 'sent' ? 'sent' : 'not delivered'}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
