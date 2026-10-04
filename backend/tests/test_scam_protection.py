"""Send money, receiver-risk engine (personal accounts used as shops or scams), community."""

from __future__ import annotations

import json

import pytest
from app.main import app
from app.mandates.service import MandateService
from app.scam.community import clean_description
from app.scam.identifiers import IdentifierError, normalize, reporter_hash
from app.scam.service import ScamService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
SUP = {"Authorization": f"Bearer {create_test_token('supervisor_777', 'supervisor')}"}
ADMIN = {"Authorization": f"Bearer {create_test_token('admin_777', 'super_admin')}"}


def num(i: int) -> str:
    return f"0171{i:07d}"


def cust(i: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_test_token(f'U_T_{i}', 'customer_channel')}"}


@pytest.fixture(autouse=True)
def wallets(durable_service: MandateService):
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (user_id, group_label, created_at, msisdn)
            SELECT 'U_T_' || g, 'independent_urban',
                   CASE WHEN g = 900 THEN now() - interval '5 days'
                        ELSE now() - interval '400 days' END,
                   '0171' || lpad(g::text, 7, '0')
            FROM generate_series(1, 950) g;
            INSERT INTO transactions (user_id, txn_type, credit_source, amount, balance_after,
                                      channel, ts)
            SELECT 'U_T_' || g, 'credit', 'salary', 20000, 20000, 'app',
                   now() - interval '10 days' FROM generate_series(1, 950) g;
        """)
        conn.commit()
    return durable_service


def _send(sender: int, receiver: int, amount, ack=True):
    return client.post("/api/v1/payments/send", headers=cust(sender), json={
        "number": num(receiver), "amount": amount, "acknowledged_warning": ack})


def test_identifier_normalisation():
    assert normalize("upay_number", "+880 1712-345678") == ("upay_number:01712345678",
                                                           "01712345678")
    assert normalize("upay_number", "০১৭১২৩৪৫৬৭৮")[1] == "01712345678"
    assert normalize("facebook", "https://www.facebook.com/Dhaka.Gadget.Deals/")[0] == \
        "facebook:dhaka.gadget.deals"
    assert normalize("website", "https://www.Best-Deal.com/x")[0] == "website:best-deal.com"
    with pytest.raises(IdentifierError):
        normalize("upay_number", "12345")


def test_send_money_moves_both_balances(wallets):
    res = _send(1, 2, 1500)
    assert res.status_code == 201, res.text
    assert res.json()["balance_after"] == 18500.0 and res.json()["to"] == "017•••••002"
    wallet = client.get("/api/v1/me/wallet", headers=cust(2)).json()
    assert wallet["transfers"][0]["direction"] == "received"
    assert wallet["transfers"][0]["other"] == "017•••••001"
    assert _send(1, 1, 100).json()["error"]["code"] == "SELF_TRANSFER"
    assert _send(1, 2, 999999).status_code == 422
    assert client.post("/api/v1/payments/send", headers=cust(1), json={
        "number": "01999999999", "amount": 10}).status_code == 404


def test_scam_pattern_opens_case_and_warns_next_payer(wallets):
    seller = 900  # new account
    for i in range(1, 13):
        assert _send(i, seller, 1250).status_code == 201
    with wallets.get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO transactions (user_id, agent_id, txn_type, amount, fee, "
                    "balance_after, channel, ts) VALUES ('U_T_900', 'A_001', 'cash_out', 13500, "
                    "202.5, 21297.5, 'agent_initiated', now());")
        conn.commit()
    flags = ScamService(wallets.get_connection).evaluate(["U_T_900"])
    assert flags[0]["level"] == "high" and flags[0]["kind"] == "possible_scam"
    with wallets.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason, evidence FROM cases WHERE case_id = %s;",
                    (flags[0]["case_id"],))
        reason, evidence = cur.fetchone()
    assert reason == "p2p_scam_seller_suspected"
    assert any("1,250" in r for r in evidence["reasons"])
    check = client.post("/api/v1/payments/check-recipient", headers=cust(50),
                        json={"number": num(seller)}).json()
    assert check["warning_level"] == "high" and check["warnings"]
    blocked = _send(50, seller, 1250, ack=False)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "WARNING_NOT_ACKNOWLEDGED"
    assert _send(50, seller, 1250, ack=True).status_code == 201  # warn, never block
    board = client.get("/api/v1/p2p/flagged", headers=SUP).json()
    assert board["receivers"][0]["user_id"] == "U_T_900"


def test_honest_shop_is_caution_not_scam(wallets):
    for i in range(100, 109):
        _send(i, 901, 650)
    flags = ScamService(wallets.get_connection).evaluate(["U_T_901"])
    assert flags[0]["kind"] == "unregistered_business"
    assert flags[0]["level"] in ("caution", "watch") and flags[0]["case_id"] is None


def test_family_transfers_are_not_flagged(wallets):
    for amount in (500, 1200, 3000, 750):
        _send(200, 201, amount)
        _send(202, 201, amount + 100)
    assert ScamService(wallets.get_connection).evaluate(["U_T_201"]) == []


def test_community_report_is_anonymous_redacted_and_searchable(wallets):
    res = client.post("/api/v1/community/reports", headers=cust(10), json={
        "identifier": num(902), "category": "not_delivered", "amount_lost": 1250,
        "description": f"Paid {num(902)} for shoes. Call me on 01812345678 or "
                       "me@mail.com. My id U_42_000010.", "paid_via_upay": True})
    assert res.status_code == 201, res.text
    dup = client.post("/api/v1/community/reports", headers=cust(10), json={
        "identifier": num(902), "category": "not_delivered", "description": "again again"})
    assert dup.status_code == 409
    found = client.get(f"/api/v1/community/search?q={num(902)}", headers=cust(11)).json()
    assert found["report_count"] == 1 and found["level"] == "caution"
    text = found["reports"][0]["description"]
    assert num(902) in text and "01812345678" not in text and "me@mail.com" not in text
    assert "U_42_000010" not in text and "reporter" not in str(found).lower()
    feed = client.get("/api/v1/community/feed", headers=cust(11)).json()
    assert feed["reports"][0]["identifier"] == "017•••••902"
    report_id = found["reports"][0]["report_id"]
    assert client.post(f"/api/v1/community/reports/{report_id}/me-too",
                       headers=cust(10)).status_code == 409
    assert client.post(f"/api/v1/community/reports/{report_id}/me-too",
                       headers=cust(11)).json()["me_too"] == 1
    assert client.post(f"/api/v1/community/reports/{report_id}/me-too",
                       headers=cust(11)).json()["me_too"] == 1  # once per customer


def test_moderation_and_verified_reports_raise_warning(wallets):
    client.post("/api/v1/community/reports", headers=cust(20), json={
        "identifier": num(903), "category": "advance_fee",
        "description": "Took advance and blocked me on WhatsApp."})
    queue = client.get("/api/v1/community/moderation", headers=SUP).json()["reports"]
    assert queue[0]["wallet_user_id"] == "U_T_903"
    assert client.post(f"/api/v1/community/reports/{queue[0]['report_id']}/moderate",
                       headers=cust(20), json={"decision": "verified"}).status_code == 403
    client.post(f"/api/v1/community/reports/{queue[0]['report_id']}/moderate", headers=SUP,
                json={"decision": "verified", "note": "Two victims confirmed by phone"})
    check = client.post("/api/v1/payments/check-recipient", headers=cust(21),
                        json={"number": num(903)}).json()
    assert check["verified_reports"] == 1 and check["warning_level"] == "high"
    advisory = check["advisory"]
    assert advisory["source"] == "template"  # no LLM key in tests
    assert "scam" not in json.dumps(advisory).lower() and "প্রতারক" not in json.dumps(advisory)
    assert num(903) not in json.dumps(advisory)
    plain = client.post("/api/v1/payments/check-recipient", headers=cust(21),
                        json={"number": num(904)}).json()
    assert plain["advisory"] is None


class _FakeLLM:
    name = "gemini"

    def __init__(self, reply: dict):
        self.reply, self.timeout, self.prompts = reply, 20.0, []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return json.dumps(self.reply)


GOOD = {"title": "Please check first", "message": "Some customers reported problems after paying.",
        "message_bn": "কিছু গ্রাহক টাকা দেওয়ার পর সমস্যার কথা বলেছেন।",
        "tips": ["Pay only people you know."], "tips_bn": ["চেনা মানুষকেই টাকা দিন।"]}
CHECK = {"number": "01700000001", "community_reports": 2, "verified_reports": 0,
         "report_categories": ["not_delivered"], "warning_level": "high"}


def test_llm_advisory_is_used_only_when_it_does_not_accuse():
    from app.scam import advisor

    advisor._cache.clear()
    llm = _FakeLLM(GOOD)
    out = advisor.advise(CHECK, [llm])
    assert out["source"] == "gemini" and out["message"] == GOOD["message"]
    assert llm.timeout <= advisor.LLM_TIMEOUT_SECONDS
    # Only structured facts reach the model: no report text, no phone number.
    assert "01700000001" not in llm.prompts[0] and "not arrive" in llm.prompts[0]

    advisor._cache.clear()
    for bad in ({**GOOD, "message": "This seller is a scammer."},
                {**GOOD, "message_bn": "এই লোকটি প্রতারক।"},
                {**GOOD, "message": "Do not pay 01700000001."},
                {"title": "x"}):
        advisor._cache.clear()
        out = advisor.advise(CHECK, [_FakeLLM(bad)])
        assert out["source"] == "template", bad
    assert advisor.advise({**CHECK, "community_reports": 0}, [llm]) is None


def test_social_page_reports_and_rate_limit(wallets):
    for i in range(5):
        r = client.post("/api/v1/community/reports", headers=cust(30), json={
            "identifier": f"facebook.com/fake.shop.{i}", "category": "fake_product",
            "description": "Sent a fake product and blocked me."})
        assert r.status_code == 201
    sixth = client.post("/api/v1/community/reports", headers=cust(30), json={
        "identifier": "facebook.com/fake.shop.9", "category": "fake_product",
        "description": "Sent a fake product and blocked me."})
    assert sixth.status_code == 429
    found = client.get("/api/v1/community/search?q=https://facebook.com/Fake.Shop.1",
                       headers=cust(31)).json()
    assert found["type"] == "facebook" and found["report_count"] == 1


def test_helpers():
    assert reporter_hash("U_1") != reporter_hash("U_2") and len(reporter_hash("U_1")) == 64
    assert clean_description("call 01912345678 now please", "01712345678") == \
        "call [number hidden] now please"


def test_assistant_checks_a_seller_number_without_leaking(wallets):
    from app.assistant import router as assistant_router
    from app.assistant.engine import Assistant

    assistant_router.set_assistant(Assistant(wallets.get_connection, []))
    try:
        for i in (40, 41):
            client.post("/api/v1/community/reports", headers=cust(i), json={
                "identifier": num(904), "category": "not_delivered",
                "description": "Paid for a phone, never delivered."})
        out = client.post("/api/v1/assistant/chat", headers=cust(42), json={
            "message": f"{num(904)} number e taka dibo, safe?"}).json()
        assert out["intent"] == "check_number" and "2" in out["reply"]
        assert num(904) not in out["reply"] and "017•••••904" in out["reply"]
        # A warning, never an accusation: reports are unproven claims.
        for word in ("scam", "fraud", "প্রতারক", "do not send", "pathaben na"):
            assert word not in out["reply"].lower(), word
        plain = client.post("/api/v1/assistant/chat", headers=cust(42), json={
            "message": f"balance of {num(905)}"}).json()
        assert plain["guard"] == "other_people"
    finally:
        assistant_router.set_assistant(None)
