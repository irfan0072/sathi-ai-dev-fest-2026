"""The future ASR evaluation harness: rules and metrics, exercised on TYPED text only.

These tests prove the harness logic. They are not an ASR result and not dialect validation.
"""

from __future__ import annotations

import pytest
from app.evaluation import asr_eval as asr


def manifest(n=120, speakers=12, test_speakers_from=0):
    rows = []
    for i in range(n):
        rows.append({"utt_id": f"u{i}", "speaker_id": f"s{(i % speakers) + test_speakers_from}",
                     "split": "test", "dialect": "sylheti", "noise": "clean",
                     "reference_text": "তিন হাজার টাকা", "reference_amount": 3000})
    return rows


def hyps(rows, system, text, conf=0.9, latency=800):
    return [{"utt_id": r["utt_id"], "system": system, "text": text, "confidence": conf,
             "latency_ms": latency} for r in rows]


def test_edit_distance_wer_cer():
    assert asr.wer("তিন হাজার টাকা", "তিন হাজার টাকা") == (0, 3)
    assert asr.wer("তিন হাজার টাকা", "তিন টাকা") == (1, 3)
    errors, total = asr.cer("abc", "axc")
    assert (errors, total) == (1, 3)


def test_manifest_must_be_speaker_disjoint_and_free_of_ledger_amounts():
    rows = manifest()
    rows.append({**rows[0], "utt_id": "t", "split": "train"})
    assert any("not speaker-disjoint" in p for p in asr.validate_manifest(rows))
    rows = manifest()
    rows[0]["ledger_amount"] = 3000
    assert any("biased with the expected ledger amount" in p for p in asr.validate_manifest(rows))
    with pytest.raises(ValueError):
        asr.evaluate(rows, [])
    assert asr.validate_manifest(manifest()) == []


def test_wrong_amount_is_counted_separately_from_abstention():
    rows = manifest()
    good = hyps(rows, "baseline", "তিন হাজার টাকা")
    wrong = hyps(rows, "wrong", "চার হাজার টাকা")
    unsure = hyps(rows, "unsure", "তিন হাজার টাকা", conf=0.2)
    approx = hyps(rows, "approx", "প্রায় তিন হাজার")
    missing_conf = hyps(rows, "noconf", "তিন হাজার টাকা", conf=None)
    result = asr.evaluate(rows, good + wrong + unsure + approx + missing_conf)["systems"]
    key = "all|all"
    assert result["baseline"][key]["exact_amount_accuracy"]["rate"] == 1.0
    assert result["wrong"][key]["wrong_amount_acceptance"]["rate"] == 1.0
    assert result["unsure"][key]["abstention"]["rate"] == 1.0           # low confidence abstains
    assert result["approx"][key]["abstention"]["rate"] == 1.0           # approximate never exact
    assert result["noconf"][key]["abstention"]["rate"] == 1.0           # missing confidence policy
    assert result["baseline"][key]["p95_latency_ms"] == 800


def test_small_slices_are_not_reported_as_numbers():
    rows = manifest(n=20, speakers=4)
    result = asr.evaluate(rows, hyps(rows, "baseline", "তিন হাজার"))
    assert result["systems"]["baseline"]["all|all"]["status"] == "too small to report"
    assert "NOT RUN ON REAL AUDIO" in result["status"]


def test_gates_require_gain_safety_and_no_slice_regression():
    rows = manifest()
    base = hyps(rows[:80], "baseline", "তিন হাজার") + hyps(rows[80:], "baseline", "চার হাজার")
    better = hyps(rows, "tuned", "তিন হাজার")
    result = asr.evaluate(rows, base + better)
    verdict = asr.check_gates(result, "baseline", "tuned")
    assert verdict["exact_gain_pp"] > 5 and verdict["passes"] is True
    worse = asr.evaluate(rows, hyps(rows, "baseline", "তিন হাজার") + hyps(rows, "tuned", "চার হাজার"))
    assert asr.check_gates(worse, "baseline", "tuned")["passes"] is False
