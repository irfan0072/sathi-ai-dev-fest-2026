"""Live scam-seller scenarios on the synthetic population.

Runs through the real send-money path, so ledger rows, transfers, risk scores, flags and
cases are produced exactly as in production. Idempotent per run marker; the live traffic
simulator keeps the 24-hour signals fresh afterwards.
"""

from __future__ import annotations

import random
from typing import Any, Callable

from app.scam.community import CommunityService
from app.scam.service import ScamService, TransferError

SCAM_SELLER = "U_9_0000500"      # "Dhaka Gadget Deals" – takes money, never delivers
SHOP_SELLER = "U_9_0000600"      # honest home bakery selling through a personal account
SCAM_PAGE = "facebook.com/dhaka.gadget.deals"


def _exists(get_connection: Callable, user_id: str) -> str | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT msisdn FROM users WHERE user_id = %s;", (user_id,))
        row = cur.fetchone()
    return row[0] if row else None


def payer(n: int) -> str:
    return f"U_9_{1_000_000 + n:07d}"


def scam_burst(get_connection: Callable, payments: int = 12, amount: int = 1250,
               offset: int | None = None, source: str = "simulator") -> int:
    """Strangers pay the scam page's number the same 'price' in a short time."""
    scam = ScamService(get_connection)
    number = _exists(get_connection, SCAM_SELLER)
    if not number:
        return 0
    start = offset if offset is not None else random.randint(1, 900_000)
    made = 0
    for i in range(payments):
        try:
            scam.send(payer(start + i), number, amount, "gadget order", acknowledged=True,
                      source=source)
            made += 1
        except TransferError:
            continue
    with get_connection() as conn, conn.cursor() as cur:
        # Scam pattern: most of the money leaves almost immediately.
        cur.execute("SELECT balance_after FROM transactions WHERE user_id = %s "
                    "ORDER BY ts DESC, txn_id DESC LIMIT 1;", (SCAM_SELLER,))
        balance = float(cur.fetchone()[0] or 0)
        out = round(made * amount * 0.9, 2)
        if made and balance >= out:
            cur.execute("INSERT INTO transactions (user_id, agent_id, txn_type, amount, fee, "
                        "balance_after, channel, ts) SELECT %s, agent_id, 'cash_out', %s, "
                        "round(%s::numeric * 0.015, 2), %s, 'agent_initiated', now() FROM agents "
                        "WHERE agent_id LIKE 'A_9_%%' ORDER BY agent_id LIMIT 1;",
                        (SCAM_SELLER, out, out, balance - out - round(out * 0.015, 2)))
            conn.commit()
    scam.evaluate([user_id for user_id in (SCAM_SELLER,)])
    return made


def shop_orders(get_connection: Callable, orders: int = 9, offset: int | None = None,
                source: str = "simulator") -> int:
    """An honest seller: identical prices from strangers, money stays; no complaints."""
    scam = ScamService(get_connection)
    number = _exists(get_connection, SHOP_SELLER)
    if not number:
        return 0
    start = offset if offset is not None else random.randint(1, 900_000)
    made = 0
    for i in range(orders):
        try:
            scam.send(payer(start + i), number, 650, "cake order", acknowledged=True,
                      source=source)
            made += 1
        except TransferError:
            continue
    scam.evaluate([SHOP_SELLER])
    return made


def family_transfers(get_connection: Callable, count: int = 5) -> int:
    """Normal P2P: people sending varied amounts to the same few relatives."""
    scam = ScamService(get_connection)
    made = 0
    for _ in range(count):
        a = random.randint(2, 900_000)
        b = a + 1
        number = _exists(get_connection, payer(b))
        if not number:
            continue
        try:
            scam.send(payer(a), number, random.choice([300, 750, 1200, 2000, 3500, 5000]),
                      "family", acknowledged=True, source="simulator")
            made += 1
        except TransferError:
            continue
    return made


MINIMAL_USERS = (SCAM_SELLER, SHOP_SELLER, "U_9_1000002")  # alerted, shop, normal receiver


def seed_minimal_scam_demo(get_connection: Callable) -> dict[str, Any]:
    """Tiny, clearly synthetic receiver fixtures that work without the 5M scale population.

    Creates three synthetic wallets (alerted 01900000500, shop 01900000600, normal
    01901000002) and synthetic community alerts about the first one. Idempotent (an audit
    marker), never touches existing balances, ledgers or evaluation data (ON CONFLICT DO
    NOTHING; the scale seed uses the same ids with the same rule). Not about real people.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM audit_log WHERE action IN ('scam_demo_seeded', "
                    "'scam_demo_minimal_seeded') LIMIT 1;")
        if cur.fetchone():
            return {"seeded": False, "reason": "already seeded"}
        for user_id in MINIMAL_USERS:
            cur.execute("INSERT INTO users (user_id, group_label, gender, age_band, region, "
                        "urban_rural) VALUES (%s, 'independent_urban', 'other', '26-40', 'dhaka', "
                        "'urban') ON CONFLICT (user_id) DO NOTHING;", (user_id,))
        conn.commit()
    community = CommunityService(get_connection)
    number = _exists(get_connection, SCAM_SELLER)
    stories = [
        (payer(100), "upay_number", number, "not_delivered", 1250,
         "Synthetic demo alert: paid a social-media page, nothing was delivered."),
        (payer(101), "upay_number", number, "not_delivered", 1250,
         "Synthetic demo alert: same page, same price, no delivery after five days."),
        (payer(102), "facebook", SCAM_PAGE, "not_delivered", 1250,
         "Synthetic demo alert: page takes advance payment and deletes comments."),
    ]
    made = 0
    for reporter, kind, ident, category, lost, text in stories:
        try:
            community.create(reporter, kind, ident, category, text, lost, None, True)
            made += 1
        except Exception:
            continue
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES ('system', 'scam_demo_minimal_seeded', 'p2p', 'demo', "
                    "'v1.0', %s::jsonb, now());", (f'{{"reports": {made}}}',))
        conn.commit()
    return {"seeded": True, "mode": "minimal", "reports": made}


def seed_scam_demo(get_connection: Callable) -> dict[str, Any]:
    if not _exists(get_connection, SCAM_SELLER) or not _exists(get_connection, payer(1)):
        return seed_minimal_scam_demo(get_connection)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM audit_log WHERE action = 'scam_demo_seeded' LIMIT 1;")
        if cur.fetchone():
            return {"seeded": False, "reason": "already seeded"}
    random.seed(11)
    burst = scam_burst(get_connection, payments=14, offset=100, source="seed")
    shop = shop_orders(get_connection, orders=9, offset=300, source="seed")
    family = family_transfers(get_connection, count=8)
    community = CommunityService(get_connection)
    number = _exists(get_connection, SCAM_SELLER)
    stories = [
        (payer(100), "upay_number", number, "not_delivered", 1250,
         "Ordered a smartwatch from a Facebook page. Paid to this upay number, the page "
         "blocked me after payment."),
        (payer(101), "upay_number", number, "not_delivered", 1250,
         "Same page, same price. No delivery after 5 days, phone switched off."),
        (payer(102), "facebook", SCAM_PAGE, "not_delivered", 1250,
         "Page posts cheap earbuds, takes advance payment by upay, then deletes comments."),
        (payer(103), "facebook", SCAM_PAGE, "fake_product", 2500,
         "Received an empty box. Seller asked for more money for 'customs'."),
        (payer(104), "website", "best-iphone-deal-bd.com", "advance_fee", 5000,
         "Website asked for 50% advance through a personal number and disappeared."),
        (payer(105), "instagram", "@quick.loan.bd", "advance_fee", 1500,
         "Promised a loan if I paid a processing fee first."),
    ]
    for reporter, kind, ident, category, lost, text in stories:
        try:
            community.create(reporter, kind, ident, category, text, lost, None, True)
        except Exception:
            continue
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES ('system', 'scam_demo_seeded', 'p2p', 'demo', 'v1.0', "
                    "'{}'::jsonb, now());")
        conn.commit()
    return {"seeded": True, "scam_payments": burst, "shop_payments": shop,
            "family": family}
