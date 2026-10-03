"""Background call scheduler and live traffic simulator.

Runs inside the API process as one asyncio task (blocking DB work happens in a thread).
Every tick it:
1. marks simulated calls that rang too long as "no answer" (real providers report this
   themselves through their status webhooks),
2. places the automatic retry calls that are due (claimed with SKIP LOCKED, so several API
   replicas never call the same customer twice),
3. when the simulator is switched on, records new synthetic cash-outs and answers their
   calls with a realistic mix of behaviours.

Simulated traffic goes through exactly the same ledger, call, interpretation, case and
queue code as real traffic; it only replaces the agent's tap and the customer's keypad.
Disable with SATHI_WORKER_ENABLED=false (tests do this).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import time
from typing import Any

log = logging.getLogger("sathi.worker")

TICK_SECONDS = 3.0
SIM_ACTOR = "sathi-simulator"
SCHEDULER_ACTOR = "sathi-scheduler"
SIM_USER_PREFIX = "U_9_"

# Behaviour mix for simulated customers (cumulative thresholds out of 1000).
BEHAVIOURS = (
    (560, "confirm"),        # types the right amount
    (620, "speak_amount"),   # says the amount in Bangla or Banglish words
    (760, "no_answer"),      # does not pick up (retries kick in)
    (790, "silent"),         # picks up but stays silent (asked again, then retried)
    (850, "unclear"),        # mumbles twice -> manual supervisor queue
    (870, "human"),          # presses 9 to talk to a person
    (930, "mismatch"),       # types a lower amount twice -> suspicious + case
    (970, "deny"),           # presses # alone: "I did not do this"
    (990, "confirm_retry"),  # wrong first, right second
    (1000, "duress"),        # secret help signal
)
_BN_NUM = {1: "এক", 2: "দুই", 3: "তিন", 4: "চার", 5: "পাঁচ", 6: "ছয়", 7: "সাত", 8: "আট",
           9: "নয়", 10: "দশ"}
_BL_NUM = {1: "ek", 2: "dui", 3: "tin", 4: "char", 5: "pach", 6: "choy", 7: "sat", 8: "aat",
           9: "noy", 10: "dosh"}


def spoken_amount(amount: int, call_id: str) -> str:
    """Say a round amount the way customers do: 'আড়াই হাজার', 'tin hajar pach sho'."""
    banglish = int(hashlib.sha256((call_id + "l").encode()).hexdigest()[:2], 16) % 2 == 0
    thousands, rest = divmod(amount, 1000)
    if not banglish and thousands in (1, 2) and rest == 500:
        return "দেড় হাজার টাকা" if thousands == 1 else "আড়াই হাজার টাকা"
    words = _BL_NUM if banglish else _BN_NUM
    scale, hundred = ("hajar", "sho") if banglish else ("হাজার", "শ")
    parts = []
    if thousands:
        parts.append(f"{words.get(thousands, str(thousands))} {scale}")
    if rest:
        parts.append(f"{words.get(rest // 100, str(rest // 100))} {hundred}")
    return " ".join(parts) + (" taka" if banglish else " টাকা")


MUMBLES = ("উম... আমি... ঠিক জানি না", "hello? hello?", "ki bolchen bujhi nai",
           "আমি পরে বলব", "taka... onek...")


def worker_enabled() -> bool:
    return os.environ.get("SATHI_WORKER_ENABLED", "true").strip().lower() != "false"


def behaviour_for(call_id: str) -> str:
    """Deterministic per call, so a retried call can behave differently from the first."""
    roll = int(hashlib.sha256(call_id.encode()).hexdigest()[:8], 16) % 1000
    return next(name for limit, name in BEHAVIOURS if roll < limit)


def answer_delay(call_id: str) -> int:
    return 3 + int(hashlib.sha256((call_id + "d").encode()).hexdigest()[:4], 16) % 12


class Worker:
    def __init__(self) -> None:
        self._sim_carry = 0.0
        self._last_sim = time.monotonic()
        self._agents: list[str] = []
        self._sim_users: int | None = None
        self._unclear_seen: dict[str, int] = {}

    # ------------------------------------------------------------------ plumbing
    def _services(self):
        from app.callcenter.service import CallCenterService
        from app.mandates.router import get_mandate_service
        from app.voice.router import get_voice_service

        mandates = get_mandate_service()
        return mandates, CallCenterService(mandates), get_voice_service()

    def tick(self) -> dict[str, int]:
        mandates, center, voice = self._services()
        policy = center.policy()
        out = {"timeouts": 0, "retries": 0, "sim_cashouts": 0, "sim_answers": 0}

        for call_id in center.stale_ringing_calls(policy["ring_timeout_seconds"]):
            try:
                voice.provider_status(call_id, "no-answer")
                out["timeouts"] += 1
            except Exception as exc:  # keep the loop alive
                log.warning("ring timeout failed for %s: %s", call_id, exc)

        for check_id in center.claim_due_retries():
            try:
                voice.start_check_call(check_id, SCHEDULER_ACTOR, automatic=True)
                out["retries"] += 1
            except Exception as exc:
                # Could not place the call (no phone number, provider down): count it as a
                # missed attempt so the retry budget still runs out.
                log.warning("retry call failed for check %s: %s", check_id, exc)
                center.on_no_answer(check_id)

        from app.settings.router import get_settings

        values = get_settings().values()
        if values.get("sim.enabled"):
            out["sim_cashouts"] = self._simulate_cashouts(mandates, int(
                values.get("sim.rate_per_minute", 12)))
            out["sim_answers"] = self._simulate_answers(mandates, voice)
            out["p2p"] = self._simulate_p2p(mandates)
        else:
            self._last_sim = time.monotonic()
        self._rescore_receivers(mandates)
        return out

    def _simulate_p2p(self, mandates: Any) -> int:
        """Normal family transfers most ticks; a scam burst or shop orders now and then."""
        from app.scam import seed

        now = time.monotonic()
        made = seed.family_transfers(mandates.get_connection, count=random.randint(0, 2))
        if now - getattr(self, "_last_burst", 0) > 300:
            self._last_burst = now
            made += seed.scam_burst(mandates.get_connection, payments=random.randint(4, 8),
                                    amount=random.choice((1250, 1250, 1490)))
            made += seed.shop_orders(mandates.get_connection, orders=random.randint(2, 4))
        return made

    def _rescore_receivers(self, mandates: Any) -> None:
        now = time.monotonic()
        if now - getattr(self, "_last_rescore", 0) < 60:
            return
        self._last_rescore = now
        from app.scam.service import ScamService

        try:
            ScamService(mandates.get_connection).evaluate()
        except Exception as exc:
            log.warning("receiver rescoring failed: %s", exc)

    # ------------------------------------------------------------------ simulator
    def _load_pool(self, mandates: Any) -> None:
        with mandates.get_connection() as conn, conn.cursor() as cur:
            if not self._agents:
                cur.execute("SELECT agent_id FROM agents WHERE agent_id NOT LIKE 'A_777%%' "
                            "ORDER BY agent_id;")
                self._agents = [r[0] for r in cur.fetchall()]
            if self._sim_users is None:
                cur.execute("SELECT max(user_id) FROM users WHERE user_id LIKE %s;",
                            (SIM_USER_PREFIX + "%",))
                top = cur.fetchone()[0]
                self._sim_users = int(top.rsplit("_", 1)[1]) if top else 0

    def _random_user(self, mandates: Any) -> str | None:
        if self._sim_users:
            return f"{SIM_USER_PREFIX}{random.randint(1, self._sim_users):07d}"
        with mandates.get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id FROM transactions WHERE txn_id >= "
                        "(SELECT (random() * max(txn_id))::bigint FROM transactions) "
                        "AND txn_type = 'credit' ORDER BY txn_id LIMIT 1;")
            row = cur.fetchone()
        return row[0] if row else None

    def _simulate_cashouts(self, mandates: Any, rate_per_minute: int) -> int:
        from app.txn.service import CheckError, TxnCheckService

        now = time.monotonic()
        self._sim_carry += (now - self._last_sim) * rate_per_minute / 60.0
        self._last_sim = now
        due = min(int(self._sim_carry), 50)
        self._sim_carry -= due
        if due <= 0:
            return 0
        self._load_pool(mandates)
        if not self._agents:
            return 0
        checks = TxnCheckService(mandates)
        _m, _c, voice = self._services()
        made = 0
        for _ in range(due):
            user = self._random_user(mandates)
            if not user:
                break
            agent = random.choice(self._agents)
            amount = random.choice((500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 7000, 10000))
            try:
                txn = checks.record_cashout(agent, user, amount, source="simulator")
            except CheckError:
                continue  # balance, daily limit: real rules still apply
            try:
                voice.start_check_call(txn["check_id"], SIM_ACTOR, automatic=True)
            except Exception as exc:
                log.warning("simulated call failed: %s", exc)
            made += 1
        return made

    def _simulate_answers(self, mandates: Any, voice: Any) -> int:
        with mandates.get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.call_id, c.amount, EXTRACT(EPOCH FROM now() - v.created_at)
                FROM voice_calls v JOIN txn_checks c ON c.check_id = v.check_id
                WHERE c.source = 'simulator' AND v.provider = 'simulated'
                  AND v.status IN ('queued','ringing','in_progress')
                ORDER BY v.created_at LIMIT 200;
                """
            )
            rows = cur.fetchall()
        answered = 0
        for call_id, amount, age in rows:
            call_id = str(call_id)
            behaviour = behaviour_for(call_id)
            if behaviour == "no_answer" or age < answer_delay(call_id):
                continue
            amount = int(amount)
            try:
                if behaviour == "speak_amount":
                    voice.handle_digits(call_id, "", "", speech=spoken_amount(amount, call_id),
                                        confidence=round(random.uniform(0.75, 0.97), 2))
                elif behaviour == "silent":
                    voice.handle_digits(call_id, "", "", no_input=True)
                elif behaviour == "human":
                    voice.handle_digits(call_id, "9", "")
                elif behaviour == "unclear":
                    voice.handle_digits(call_id, "", "", speech=random.choice(MUMBLES),
                                        confidence=round(random.uniform(0.15, 0.5), 2))
                elif behaviour == "deny":
                    voice.handle_digits(call_id, "", "")
                elif behaviour == "duress":
                    voice.handle_digits(call_id, f"0{amount}", "")
                elif behaviour == "mismatch":
                    voice.handle_digits(call_id, str(max(100, amount - random.choice(
                        (200, 500, 1000)))), "")
                elif behaviour == "confirm_retry":
                    seen = self._unclear_seen.get(call_id, 0)
                    digits = str(amount - 100) if seen == 0 else str(amount)
                    self._unclear_seen[call_id] = seen + 1
                    voice.handle_digits(call_id, digits, "")
                else:
                    voice.handle_digits(call_id, str(amount), "")
                answered += 1
            except Exception as exc:
                log.warning("simulated answer failed for %s: %s", call_id, exc)
        if len(self._unclear_seen) > 5000:
            self._unclear_seen.clear()
        return answered


_task: asyncio.Task | None = None


async def _loop() -> None:
    worker = Worker()
    while True:
        try:
            await asyncio.to_thread(worker.tick)
        except Exception as exc:  # database restarting, settings table missing, ...
            log.warning("worker tick failed: %s", exc)
        await asyncio.sleep(TICK_SECONDS)


def start() -> None:
    global _task
    if _task is None and worker_enabled():
        _task = asyncio.get_event_loop().create_task(_loop())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
