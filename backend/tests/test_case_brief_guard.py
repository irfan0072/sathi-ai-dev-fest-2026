"""Regression tests for the case-brief output guard (judge audit finding 3).

A valid fact ID only proves a reference exists. These cases reproduce briefs that the old
validator accepted (invented money, accusations, phone numbers, PIN questions) and prove the
guard rejects them in every text field, in English, Bangla and Banglish, while a grounded
brief still passes (valid-path check).
"""

from __future__ import annotations

import json

import pytest
from app.copilot.guard import external_facts, redact_value
from app.copilot.investigator import (
    BriefValidationError,
    CaseInvestigator,
    evidence_facts,
    template_brief,
    validate_brief,
)

MISMATCH = {
    "case": {"case_id": 7, "reason": "post_txn_amount_mismatch", "status": "open",
             "opened_at": "2026-10-07T03:00:00+00:00",
             "details": {"note": "call 01712345678, PIN is 1234"}},
    "transaction": {"txn_id": 9, "ledger_amount_bdt": 5000.0, "customer_typed_bdt": 3000.0,
                    "call_outcome": "mismatch", "attempts": 2},
    "agent": {"agent_id": "A_P_8801712345678", "cases_7d": 3, "open_cases_7d": 2},
}
FACTS = evidence_facts(MISMATCH)
SHARED = external_facts(FACTS)
BY_FIELD = {f["field"]: f["id"] for f in SHARED}
LEDGER = BY_FIELD["transaction.ledger_amount_bdt"]
TYPED = BY_FIELD["transaction.customer_typed_bdt"]
REASON = BY_FIELD["case.reason"]

GOOD = {
    "headline": "Customer typed less than the ledger amount",
    "what_happened": "The ledger shows 5000 and the customer typed 3000 after the cash-out.",
    "why_risky": [{"point": "Customer typed 3000 against a ledger amount of 5000.",
                   "evidence": [LEDGER, TYPED]}],
    "recommended_next_step": "call_customer_on_registered_number",
    "questions_for_customer": ["How much cash did you receive?"],
    "summary_bn": "গ্রাহকের বলা টাকা লেজারের সাথে মেলেনি।",
}


def check(**changes):
    return validate_brief(json.dumps({**GOOD, **changes}), SHARED, MISMATCH)


def test_grounded_brief_passes():
    assert check()["headline"].startswith("Customer typed")


@pytest.mark.parametrize("field", ["headline", "what_happened", "summary_bn"])
@pytest.mark.parametrize("text", [
    "Total of 99999 taka was taken",            # invented amount
    "The agent stole the money",               # accusation
    "এজেন্ট চোর",                               # Bangla accusation
    "agent ta churi koreche",                  # Banglish accusation
    "Call the customer on 01712345678",        # phone number
    "Call 880 1712 345678 now",                # spaced +880 number
    "Ask for the PIN and OTP",                 # secret request
    "গ্রাহকের পিন চান",                          # Bangla secret request
    "Fraud is confirmed fraud",                # certainty about misconduct
    "three thousand taka is missing",          # spelled-out money
    "details at https://evil.example.com/x",   # link
])
def test_every_narrative_field_is_guarded(field, text):
    with pytest.raises(BriefValidationError):
        check(**{field: text})


@pytest.mark.parametrize("point", [
    "Customer typed 99999 against the ledger",          # number not in cited facts
    "Customer typed 5000 and ledger shows 3000",        # right numbers, but fact 5000 is cited
    "The agent is a thief",
    "Customer must share their OTP",
    "Contact on +8801712345678",
])
def test_why_risky_points_are_guarded(point):
    # A point may only use numbers from the facts it cites.
    cited = [REASON] if "5000" in point and "3000" in point else [LEDGER]
    with pytest.raises(BriefValidationError):
        check(why_risky=[{"point": point, "evidence": cited}])


@pytest.mark.parametrize("question", [
    "What is your PIN?",
    "আপনার পিন কত?",
    "apnar otp ta bolun",
    "Did you receive 5000 taka?",                # discloses the ledger amount
    "Did the agent make you press the secret help signal?",
    "Is this case flagged as suspicious?",
    "Call me on 01812345678",
])
def test_customer_questions_are_guarded(question):
    with pytest.raises(BriefValidationError):
        check(questions_for_customer=[question])


def test_non_text_question_is_rejected():
    with pytest.raises(BriefValidationError):
        check(questions_for_customer=[{"q": "x"}])
    with pytest.raises(BriefValidationError):
        check(why_risky=[{"point": "p", "evidence": [{"x": 1}]}])


def test_completed_cash_out_cannot_be_called_held_or_recovered():
    for text in ("The cash-out was held before payout", "Funds were recovered from the agent",
                 "Sathi blocked the transaction", "টাকা আটকে রাখা হয়েছে"):
        with pytest.raises(BriefValidationError):
            check(what_happened=text)


def test_contradicted_match_claim_is_rejected_but_negation_is_fine():
    with pytest.raises(BriefValidationError):
        check(what_happened="The amounts matched the ledger")
    assert check(what_happened="The amounts did not match the ledger")["what_happened"]


def test_close_as_customer_error_is_blocked_for_duress():
    evidence = {"case": {"reason": "duress_signal"}, "transaction": {"ledger_amount_bdt": 5000.0}}
    shared = external_facts(evidence_facts(evidence))
    brief = {**GOOD, "what_happened": "The customer used the help code.",
             "why_risky": [{"point": "Reason recorded.", "evidence": [shared[0]["id"]]}],
             "recommended_next_step": "close_as_customer_error"}
    with pytest.raises(BriefValidationError):
        validate_brief(brief, shared, evidence)


def test_external_facts_exclude_identifiers_timestamps_and_free_text():
    shared_fields = {f["field"] for f in SHARED}
    assert "agent.agent_id" not in shared_fields
    assert "transaction.txn_id" not in shared_fields
    assert not any(f.startswith("case.details") for f in shared_fields)
    assert "case.opened_at" not in shared_fields
    assert "case.reason" in shared_fields and "transaction.ledger_amount_bdt" in shared_fields
    assert redact_value("A_P_8801712345678 at 01712345678") == "[hidden] at [hidden]"


class _Recorder:
    name, model = "gemini", "m"

    def __init__(self, reply):
        self.reply, self.seen = reply, ""

    def complete(self, system, user):
        self.seen = user
        return self.reply


def test_external_model_never_receives_identifiers_or_phone_numbers():
    client = _Recorder(json.dumps(GOOD))
    result = CaseInvestigator([client]).brief(MISMATCH)
    assert result["mode"] == "llm_guarded" and result["facts_shared_externally"] == len(SHARED)
    for secret in ("A_P_8801712345678", "01712345678", "PIN is 1234", "T03:00"):
        assert secret not in client.seen
    # The analyst view still has the complete facts.
    assert any(f["field"] == "agent.agent_id" for f in result["facts"])


def test_unsafe_model_output_falls_back_to_deterministic_brief():
    bad = {**GOOD, "headline": "Agent stole 99999", "questions_for_customer": ["What is your PIN?"]}
    result = CaseInvestigator([_Recorder(json.dumps(bad))]).brief(MISMATCH)
    assert result["provider"] == "template" and result["mode"] == "deterministic"
    assert result["generated"] is False and result["fallbacks"][0]["guard"]
    assert "stole" not in json.dumps(result["brief"]).lower()


def test_duress_template_does_not_claim_a_mandate_was_held_after_cash_out():
    after = {"case": {"reason": "duress_signal"}, "transaction": {"ledger_amount_bdt": 5000.0}}
    brief = template_brief(after, evidence_facts(after))
    assert "mandate was held" not in brief["what_happened"]
    assert "already completed" in brief["what_happened"]
    assert "does not move money" in brief["what_happened"]
    before = {"case": {"reason": "duress_signal"}, "mandate": {"status": "rejected"}}
    assert "mandate was held" in template_brief(before, evidence_facts(before))["what_happened"]


MANDATE_REASONS = {"repeated_code_failures_lockout", "high_risk_request",
                   "customer_denied_request", "stated_amount_mismatch"}


TEMPLATE_CASES = [
    (reason, flow)
    for reason in ("duress_signal", "stated_amount_mismatch", "customer_denied_request",
                   "cash_gap_tolerance_exceeded", "repeated_code_failures_lockout",
                   "post_txn_amount_mismatch", "customer_denied_transaction",
                   "high_risk_request", "something_new")
    for flow in ("mandate", "transaction")
    # these reasons only arise on the mandate flow
    if not (flow == "transaction" and reason in ("repeated_code_failures_lockout",
                                                  "high_risk_request"))
]


@pytest.mark.parametrize(("reason", "flow"), TEMPLATE_CASES)
def test_deterministic_templates_themselves_pass_the_guard(reason, flow):
    evidence = {"case": {"reason": reason}}
    evidence["mandate" if flow == "mandate" else "transaction"] = (
        {"status": "rejected"} if flow == "mandate" else {"ledger_amount_bdt": 5000.0})
    facts = evidence_facts(evidence)
    brief = template_brief(evidence, facts)
    # Same guard as model text, applied to the code-written sentences (valid-path check).
    validate_brief(brief, facts, evidence)
