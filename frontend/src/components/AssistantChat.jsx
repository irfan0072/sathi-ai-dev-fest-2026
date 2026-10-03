import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import Icon from './Icon';

const LANGS = [
  { id: 'bn', label: 'বাংলা' },
  { id: 'banglish', label: 'Banglish' },
  { id: 'en', label: 'English' },
];
const START = {
  bn: ['আমার ব্যালেন্স কত?', 'শেষ ক্যাশ-আউট', 'এজেন্ট কম টাকা দিয়েছে', 'মানুষের সাথে কথা বলতে চাই'],
  banglish: ['Amar balance koto?', 'Last cash-out', 'Agent kom taka diyeche', 'Manusher sathe kotha bolte chai'],
  en: ['What is my balance?', 'Last cash-out', 'The agent gave me less cash', 'Talk to a person'],
};
const guardNote = {
  injection: 'Blocked: that message tried to change the assistant’s rules.',
  other_people: 'Blocked: the assistant only shares your own account.',
  secret: 'Safety: Sathi never needs your PIN or OTP.',
  internal: 'Internal checks are never shared, for your safety.',
};

/** Call language picker: the verification call speaks this language. */
export function CallLanguage() {
  const [pref, setPref] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.getMyLanguage().then(setPref).catch((e) => setError(e.message)); }, []);
  const choose = async (language) => {
    try { setPref(await api.setMyLanguage(language)); } catch (e) { setError(e.message); }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="text-sm font-semibold">Call language</div>
      <div className="join">
        {LANGS.map((l) => (
          <button key={l.id} className={`btn btn-sm join-item ${pref?.language === l.id ? 'btn-primary' : ''}`} onClick={() => choose(l.id)}>
            {l.label}
          </button>
        ))}
      </div>
      <p className="muted text-xs">
        {pref ? (pref.source === 'explicit' ? 'You chose this.' : pref.source === 'default' ? 'Default.' : `Learned from how you ${pref.source === 'chat' ? 'write' : 'answer calls'}.`) : ''}
        {' '}Press 8 during a call to switch.
      </p>
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}

export default function AssistantChat({ onAction }) {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [lang, setLang] = useState('bn');
  const [suggestions, setSuggestions] = useState(START.bn);
  const bottom = useRef(null);

  useEffect(() => {
    api.getAssistantHistory().then((r) => {
      setMessages(r.messages.map((m) => ({ role: m.role === 'assistant' ? 'bot' : 'me', text: m.text })));
      const last = r.messages[r.messages.length - 1];
      if (last) { setLang(last.language); setSuggestions(START[last.language] || START.bn); }
    }).catch(() => {});
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView?.({ block: 'nearest' }); }, [messages]);

  const send = async (message) => {
    const clean = message.trim();
    if (!clean || busy) return;
    setText(''); setBusy(true);
    setMessages((m) => [...m, { role: 'me', text: clean }]);
    try {
      const r = await api.assistantChat(clean);
      setMessages((m) => [...m, { role: 'bot', text: r.reply, guard: r.guard, provider: r.provider }]);
      setLang(r.language);
      setSuggestions(r.suggestions?.length ? r.suggestions : START[r.language] || START.bn);
      if (r.action) onAction?.(r.action);
    } catch (err) {
      setMessages((m) => [...m, { role: 'bot', text: err.message, guard: 'error' }]);
    } finally { setBusy(false); }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-semibold"><Icon name="shield" className="size-4" />Sathi Sahayak</h3>
        <span className="badge badge-ghost badge-sm">{LANGS.find((l) => l.id === lang)?.label}</span>
      </div>
      <p className="muted text-xs">Ask in Bangla, English or Banglish. It only knows your own account and never asks for your PIN.</p>
      <div className="flex max-h-72 min-h-32 flex-col gap-2 overflow-y-auto rounded-box bg-base-200/60 p-2" aria-live="polite">
        {messages.length === 0 && <p className="muted p-2 text-sm">আসসালামু আলাইকুম! কীভাবে সাহায্য করতে পারি?</p>}
        {messages.map((m, i) => (
          <div key={i} className={`chat ${m.role === 'me' ? 'chat-end' : 'chat-start'}`}>
            <div className={`chat-bubble whitespace-pre-line text-sm ${m.role === 'me' ? 'chat-bubble-primary' : ''}`}>{m.text}</div>
            {m.guard && guardNote[m.guard] && <div className="chat-footer muted text-[11px]">{guardNote[m.guard]}</div>}
          </div>
        ))}
        {busy && <span className="loading loading-dots loading-sm ml-2" />}
        <div ref={bottom} />
      </div>
      <div className="flex flex-wrap gap-1">
        {suggestions.map((s) => (
          <button key={s} className="btn btn-xs btn-ghost border-base-300" onClick={() => send(s)} disabled={busy}>{s}</button>
        ))}
      </div>
      <form className="join w-full" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input className="input input-bordered input-sm join-item w-full focus-ring" maxLength={500} value={text}
          onChange={(e) => setText(e.target.value)} placeholder="Type a message…" aria-label="Message to Sathi Sahayak" />
        <button className="btn btn-sm btn-primary join-item" disabled={busy || !text.trim()}>Send</button>
      </form>
    </div>
  );
}
