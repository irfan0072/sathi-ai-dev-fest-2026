# Feature-phone access: channel capability table and rollout plan

Written 7 October 2026. **Nothing here has been run with a real handset, telco, IVR provider or
user.** Every "works" below means: implemented in this repository and tested locally against a
simulated or fake-signed provider.

## The intended production path (ordinary cellular voice)

cash-out event -> existing confirmation queue -> provisioned voice/IVR provider -> ordinary
cellular call -> short Bangla prompt -> spoken amount **or** keypad -> deterministic validation ->
neutral acknowledgement -> staff case / independent follow-up when needed.

A feature phone needs **cellular voice coverage** and nothing else: no app, browser, login or
handset mobile data. The provider and our backend need their own connectivity. "No mobile data" is
not "no coverage": with no voice coverage the check stays pending, is retried a bounded number of
times, then goes to a person. It is never shown as confirmed.

## Capability table

| Capability | Implemented locally and tested | Local simulation only | Needs a provider contract | Real-user validated |
|---|---|---|---|---|
| Outbound confirmation call, prompts in Bangla / Banglish / English, no amount spoken, no PIN/OTP ever requested | Yes (`voice/scripts.py`, `voice/twiml.py`, tests) | The browser "handset" panel and the simulated provider | A real outbound-voice/IVR service, Bangla audio, caller-number and routing permission | **No** |
| Speech **or** keypad on the first prompt (`input="dtmf speech"`) | Yes | - | Provider speech support for Bangla and a verified callback contract | **No** |
| **Keypad-only fallback** after unusable speech, low or missing confidence, approximate/conflicting amount, or a speech timeout. The next provider response is `input="dtmf"`; the mode is stored on the call row (migration 016) and survives a restart | Yes (`tests/test_feature_phone_voice.py` asserts the emitted TwiML) | - | Provider must honour `input="dtmf"` (Twilio documents it; a Bangladeshi gateway is unconfirmed) | **No** |
| **Empty callback is not a denial.** A signed Gather callback with no Digits, no SpeechResult and no FinishedOnKey is silence: re-prompt, bounded retries, then human follow-up. A bare `#` is also an empty answer | Yes | - | Confirm what the real provider sends on timeout | **No** |
| **Explicit denial = `*`** (then optional `#`), or a clear spoken phrase. No collision with amount digits, `9` (talk to a person), `8` (language) or a leading zero (secret help) | Yes | - | - | **No** |
| Secret help: amount typed with a leading zero (`0700#`). Customer hears the same neutral ending as any outcome; staff get an **urgent** task, kept urgent through resolution, retry and claim | Yes | - | - | **No** |
| Deterministic amount interpretation (no LLM in the decision, no expected-amount hint to any recogniser) | Yes (`callcenter/interpret.py`) | - | - | **No** |
| Retry budget, crash-lease recovery, duplicate/late callbacks cannot overwrite a terminal result, persisted attempts | Yes | - | - | **No** |
| Independent follow-up and the server gate that stops a case being cleared on a same-handset answer | Yes | The in-person contact is simulated in the demo | Supervised field contact process | **No** |
| Custom or fine-tuned Bangla ASR | **No** (provider transcript plus a word parser) | - | Consented audio, compute, speaker-disjoint test (`docs/bangla-asr-evaluation-spec.md`) | **No** |
| Conversational STT -> LLM -> TTS agent | **Not built** | - | A verified streaming voice transport and Bangla models. Would be bounded and separate from authorisation: it could never approve, block, clear or infer duress | **No** |
| **USSD** menu session | **Not built** (see plan below) | - | A separately provisioned operator/aggregator service and assigned code | **No** |
| Call capacity / throughput | Queue, retry and lease mechanisms exist; synthetic 5M-row table was a database performance test | - | Measured provider concurrency, rate caps and tariffs | **No** |

## Browser handset voice (local simulation)

The customer handset panel can **read each prompt aloud** (browser text-to-speech, `bn-BD` / `en-IN`,
with Repeat and an off switch) and **listen to a spoken answer** (browser speech recognition, one
attempt per press of "Speak your answer"). The transcript and the browser's own confidence go
through the same server path as a real provider's: a good confidence is parsed deterministically; a
missing, low or invalid confidence, or silence, switches the call to keypad-only. The browser never
invents a confidence. Support and Bangla quality depend on the browser and are **not validated**;
this is a demo of the call's voice, not the production voice path. Tested with a mocked Web Speech
API in Chromium (prompt spoken in `bn-BD`; confidence 0.9 completes; no confidence -> keypad only).

## Prompts (what a feature-phone customer hears, in words)

1. Greeting, "a cash-out was just made", "type the cash you received and press hash, or say it".
2. "If you did not make this cash-out, press star." "To talk to a person, press 9. For English, 8."
3. "We never ask for your PIN or OTP."
4. After speech fails: "Sorry, I did not understand. Please use the keypad only..." and the
   provider is told to collect DTMF only.
5. Same closing sentence for every outcome.

## USSD: separate optional service, **not implemented**

DTMF keypad input travels inside the same call. USSD is a different service: it needs an operator
or aggregator, an assigned short code and a callback, none of which exist here. The voice call
cannot turn into a USSD session automatically, and no upay code, operator partnership or callback
URL is claimed or invented.

If it is built after provisioning, reuse the same confirmation service and these rules:

- identity comes from the gateway's authenticated phone number, never a client-supplied number,
  check id or accumulated menu text; the server holds session state and expiry;
- one eligible pending check per session; several pending checks need an explicit, safe choice;
- authenticated gateway callbacks, replay/duplicate protection, rate limits, an audit record;
- menu depth and session length are limited; cancel, expiry, network loss and malformed input never
  confirm anything; no new cash-out or debit; the same server clearance gate applies;
- a same-handset USSD answer is not independent contact.

`CON`/`END` conventions are common but are **not** evidence of a Bangladeshi provider contract.
A local simulation panel was deferred; a truthful tested voice/keypad path was judged more valuable
than a non-functional USSD button.

## Rollout dependencies (none provisioned in this sprint)

Governed cash-out/KYC event feed; provisioned outbound voice/IVR with a verified callback and
media contract; Bangla audio and speech language support; caller-number and routing permissions;
optional assigned USSD code; field usability, privacy and security review; a consented pilot. No
paid service was used and no real call or SMS was sent.

## Sources and their limits

- Twilio Gather (speech/DTMF selection, first-input precedence, empty-result behaviour and the
  documented callback fields): https://www.twilio.com/docs/voice/twiml/gather. Recheck before
  changing the adapter. Our adapter never relies on `FinishedOnKey`.
- Media Streams (an example of a backend voice transport for a future agent, not our deployment):
  https://www.twilio.com/docs/voice/media-streams
- Africa's Talking USSD go-live (an example of separately assigned USSD service, not a Bangladeshi
  recommendation): https://help.africastalking.com/en/articles/9915125-how-do-i-go-live-with-ussd
