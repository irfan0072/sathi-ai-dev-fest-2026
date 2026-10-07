// Browser voice for the simulated handset: text-to-speech for the call prompts and speech
// recognition for the spoken amount. Uses the Web Speech API when the browser has it. This is a
// LOCAL SIMULATION of the call's voice: a real call is spoken and heard by the telephony provider.
// Browser recognition quality for Bangla varies by browser and is not validated by this project;
// the keypad is always available and is the safe path.

const w = typeof window === 'undefined' ? {} : window;

export const voiceSupport = () => ({
  speak: Boolean(w.speechSynthesis && w.SpeechSynthesisUtterance),
  listen: Boolean(w.SpeechRecognition || w.webkitSpeechRecognition),
});

export const speechLang = (language) => (language === 'en' ? 'en-IN' : 'bn-BD');

export function speak(text, language = 'bn') {
  if (!voiceSupport().speak || !text) return;
  try {
    w.speechSynthesis.cancel();
    const utterance = new w.SpeechSynthesisUtterance(text);
    utterance.lang = speechLang(language);
    const voices = w.speechSynthesis.getVoices?.() || [];
    const match = voices.find((v) => v.lang === utterance.lang) || voices.find((v) => v.lang.startsWith(utterance.lang.slice(0, 2)));
    if (match) utterance.voice = match;
    utterance.rate = 0.9;
    w.speechSynthesis.speak(utterance);
  } catch { /* a speech failure must never break the call screen; the text is still shown */ }
}

export function stopSpeaking() {
  if (voiceSupport().speak) w.speechSynthesis.cancel();
}

// One recognition attempt. Calls onResult(transcript, confidence), onSilence() when nothing was
// heard, onError(message) otherwise. A missing confidence is passed as null, never invented.
// Plain-language reasons for the browser's recognition errors. `blocked` means retrying cannot
// help in this browser or page (permission or service refused), so the caller disables the mic.
export const isSafari = () => /^((?!chrome|chromium|android|crios|fxios|edg).)*safari/i.test(globalThis.navigator?.userAgent || '');

export const recognitionProblem = (code) => {
  if (isSafari() && ['service-not-allowed', 'not-allowed', 'language-not-supported'].includes(code)) {
    return {
      message: 'Safari did not allow speech recognition. It needs macOS Dictation turned on (System Settings > Keyboard > Dictation) and the microphone allowed for this site, and Safari may not recognise Bangla at all. Chrome or Edge works better. Use the keypad.',
      blocked: true,
    };
  }
  const blocked = {
    'service-not-allowed': 'This browser blocks its speech-recognition service here (it needs Chrome or Edge, the page on https or localhost, and no privacy setting or extension blocking it).',
    'not-allowed': 'The microphone is blocked. Allow the microphone for this site, or use the keypad.',
    'language-not-supported': 'This browser cannot recognise Bangla speech.',
    'audio-capture': 'No microphone was found.',
  };
  if (blocked[code]) return { message: `${blocked[code]} Use the keypad.`, blocked: true };
  return { message: `Speech recognition problem (${code}). Try again or use the keypad.`, blocked: false };
};

export function listenOnce(language, { onResult, onSilence, onError, onEnd }) {
  const Recognition = w.SpeechRecognition || w.webkitSpeechRecognition;
  if (!Recognition) { onError('This browser has no speech recognition. Use the keypad.', true); return null; }
  const rec = new Recognition();
  rec.lang = speechLang(language);
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  let got = false;
  rec.onresult = (event) => {
    got = true;
    const alt = event.results[0][0];
    const c = Number.isFinite(alt.confidence) && alt.confidence > 0 ? alt.confidence : null;
    onResult(alt.transcript, c);
  };
  rec.onerror = (event) => {
    if (event.error === 'no-speech') onSilence();
    else onError(recognitionProblem(event.error).message, recognitionProblem(event.error).blocked);
  };
  rec.onend = () => { if (!got) onSilence(); onEnd(); };
  try { rec.start(); } catch { onError('Could not start the microphone. Use the keypad.', true); return null; }
  return rec;
}
