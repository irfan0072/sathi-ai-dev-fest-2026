# Bangla speech evaluation: capability label and future specification

## What Sathi does today (accurate label)

- **No custom ASR model.** The call provider (or the simulated channel) supplies a *transcript*.
  `backend/app/callcenter/interpret.py` is a **word parser** that runs *after* transcription and
  turns Bangla, Banglish or English number words into an amount. A parser is not ASR.
- **The keypad is the safe path.** Spoken answers that are approximate, alternative, conflicting,
  low-confidence, or that arrive without a usable confidence are treated as *unclear*: the customer
  is asked for the keypad, then a person calls. Provider confidence is not a calibrated probability
  that the amount is correct (the provider does not guarantee it is present or accurate).
- **Not validated for regional or noisy speech.** There is no consented audio, no training compute
  and no speaker-disjoint dialect/noise test set in this repository. Typed transcripts and
  text-to-speech audio are not dialect validation and are never presented as such.
- The label is returned by `GET /api/v1/voice/config` as `speech_input`.

## What would be needed (not done, not promised)

1. **Consent and data:** an opt-in research workflow, separate from the production privacy policy;
   recordings stay out of operational storage. Speakers recruited across dialect regions
   (for example Dhaka, Sylhet, Chittagong, Rangpur), age bands and noise conditions (clean, market,
   vehicle).
2. **Speaker-disjoint split:** no speaker in both training and dev/test. Enforced by
   `validate_manifest` in `backend/app/evaluation/asr_eval.py`.
3. **Systems compared:** the current provider transcript as the audio baseline versus a fine-tuned
   or adapted model, on the same held-out test utterances.
4. **Never bias transcription with the expected ledger amount.** The harness rejects any manifest
   column that carries a ledger or expected transaction amount.

## Metrics (all by dialect and by noise level, with Wilson intervals)

| Metric | Meaning |
|---|---|
| WER, CER | Word and character error rate against the reference text |
| Exact-amount accuracy | The production parser returns exactly the intended amount |
| **Wrong-amount acceptance** | The parser returns a *different* amount: the dangerous error |
| Abstention | The parser says "unclear" (safe, but costs a keypad prompt) |
| p95 latency | 95th percentile of provider/model latency in milliseconds |

A slice with fewer than 100 test utterances or 10 speakers is reported as "too small to report".

## Acceptance gates for a fine-tuned model over the baseline (test split only)

- wrong-amount acceptance at most 0.5% overall;
- exact-amount accuracy at least 5 percentage points higher overall;
- abstention at most 30%;
- p95 latency at most 2,500 ms;
- no reported dialect or noise slice worse than the baseline.

## Run it (once real, consented data exists)

```python
from app.evaluation.asr_eval import evaluate, check_gates
result = evaluate(manifest_rows, hypothesis_rows, split="test")   # raises on a bad manifest
verdict = check_gates(result, baseline="baseline", candidate="fine_tuned")
```

`backend/tests/test_asr_eval_spec.py` exercises the harness on **typed** text only, to prove the
rules and metrics work. It is not an ASR result. Status: **pending (external)**.
