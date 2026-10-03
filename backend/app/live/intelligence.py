"""Live AI on the current database (no frozen snapshots).

- Agent risk: the trained agent anomaly detector (data/artifacts/deployment/agent.joblib)
  scores features aggregated in PostgreSQL over the last 30 days. Customers' post-cash-out
  confirmations feed the cash-gap features: what the customer said they received is the
  cash report.
- Assisted-customer outreach: the trained assisted classifier (assisted.joblib) scores
  customers active in the last 30 days from their live transactions and sessions.
- Agent liquidity: LightGBM point and P90 models re-trained on live daily cash-out totals
  and forecasting the next 7 real days.
- Uplift targeting: the T-learner is re-trained on live customer features. Campaign
  outcomes come from the documented randomized-experiment simulator, because no real
  campaign has been run yet.

Results are cached briefly and refreshed by a background thread, so pages stay fast while
the numbers follow the live ledger. Every response carries `computed_at` and the window.
"""

from __future__ import annotations

import datetime
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

log = logging.getLogger("sathi.live")

WINDOW_DAYS = 30
TTL = {"agent_risk": 120, "outreach": 300, "liquidity": 900, "uplift": 1800}
OUTREACH_POOL = 6000
UPLIFT_POOL = 20000
LIQUIDITY_TRAIN_AGENTS = 600
LIQUIDITY_FORECAST_AGENTS = 2500  # busiest agents get their own forecast; others use cohorts
DHAKA = "Asia/Dhaka"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _artifact_dir() -> Path:
    return Path(os.getenv("SATHI_ARTIFACTS_DIR", "data/artifacts/deployment"))


class WarmingUp(KeyError):
    """Live model has not finished its first run after a restart."""


class _Cache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str, ttl: int, compute: Callable[[], Any], force: bool = False,
            stale_ok: bool = False) -> Any:
        """Fresh value, or recompute. `stale_ok` serves the last value while the
        background thread refreshes it, so a page never waits on a re-train."""
        hit = self._values.get(key)
        if hit and not force and (stale_ok or time.monotonic() - hit[0] < ttl):
            return hit[1]
        if stale_ok and _thread is not None and _thread.is_alive():
            # The background process owns training; wait for it instead of training twice.
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                hit = self._values.get(key)
                if hit:
                    return hit[1]
                time.sleep(0.5)
            raise WarmingUp(f"The live {key.replace('_', ' ')} model is still training on "
                            "today's data. Try again in a minute.")
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._values.get(key)
            if hit and not force and time.monotonic() - hit[0] < ttl:
                return hit[1]
            value = compute()
            self._values[key] = (time.monotonic(), value)
            return value

    def peek(self, key: str) -> Any:
        hit = self._values.get(key)
        return hit[1] if hit else None

    def clear(self) -> None:
        self._values.clear()


CACHE = _Cache()


class LiveIntelligence:
    def __init__(self, get_connection: Callable, config: dict[str, Any] | None = None) -> None:
        self._conn = get_connection
        if config is None:
            from app.data.config import load_config

            config = load_config()
        self.config = config
        self._agent_model = None
        self._assisted_model = None

    # ------------------------------------------------------------------ models
    def agent_model(self):
        if self._agent_model is None:
            from app.models.agent_model import AgentAnomalyDetector

            self._agent_model = AgentAnomalyDetector.load(_artifact_dir() / "agent.joblib")
        return self._agent_model

    def assisted_model(self):
        if self._assisted_model is None:
            from app.models.assisted_model import AssistedUserClassifier

            self._assisted_model = AssistedUserClassifier.load(
                _artifact_dir() / "assisted.joblib")
        return self._assisted_model

    # ------------------------------------------------------------------ agent risk
    def _allowance_anchor(self, cur: Any) -> tuple[datetime.date, int, int]:
        from app.live.rebase import ledger_shift_days

        sim = self.config["simulation"]
        start = datetime.datetime.fromisoformat(
            str(sim["start_timestamp"]).replace("Z", "+00:00")).date()
        start -= datetime.timedelta(days=ledger_shift_days(cur))
        cycle = int(sim.get("credits", {}).get("allowance", {}).get("cycle_days", 30))
        return start, cycle, int(sim.get("allowance_day_of_cycle", 5))

    def _agent_features(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        fee_rate = float(self.config["simulation"]["official_fee_rate"])
        gap = self.config.get("policy", {}).get("cash_gap", {"min_bdt": 50, "rate": 0.02})
        with self._conn() as conn, conn.cursor() as cur:
            start, cycle, day = self._allowance_anchor(cur)
            cur.execute("SET LOCAL statement_timeout = '60s';")
            cur.execute(
                """
                SELECT t.agent_id,
                       avg(t.fee / NULLIF(t.amount * %(rate)s, 0))
                           FILTER (WHERE t.txn_type = 'cash_out'),
                       count(*),
                       count(DISTINCT (t.ts AT TIME ZONE 'Asia/Dhaka')::date),
                       count(*) FILTER (WHERE (((t.ts AT TIME ZONE 'UTC')::date - %(start)s::date)
                                               %% %(cycle)s) = %(day)s),
                       count(*) FILTER (WHERE t.txn_type = 'cash_out'),
                       COALESCE(sum(t.amount) FILTER (WHERE t.txn_type = 'cash_out'), 0)
                FROM transactions t
                WHERE t.agent_id IS NOT NULL AND t.ts > now() - make_interval(days => %(w)s)
                  AND t.ts <= now()
                GROUP BY t.agent_id;
                """,
                {"rate": fee_rate, "start": start, "cycle": cycle, "day": day,
                 "w": WINDOW_DAYS})
            tx = {r[0]: r[1:] for r in cur.fetchall()}
            cur.execute(
                """
                SELECT agent_id,
                       count(*) FILTER (WHERE stated_amount IS NOT NULL),
                       count(*) FILTER (WHERE stated_amount IS NOT NULL
                                        AND amount - stated_amount
                                            > GREATEST(%(min)s, %(gr)s * amount)),
                       count(*) FILTER (WHERE status = 'suspicious'),
                       count(*) FILTER (WHERE outcome = 'duress'),
                       count(*)
                FROM txn_checks WHERE agent_id IS NOT NULL
                  AND created_at > now() - make_interval(days => %(w)s)
                GROUP BY agent_id;
                """,
                {"min": float(gap.get("min_bdt", 50)), "gr": float(gap.get("rate", 0.02)),
                 "w": WINDOW_DAYS})
            checks = {r[0]: r[1:] for r in cur.fetchall()}
            cur.execute("SELECT agent_id, region, volume_band FROM agents;")
            meta = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
            cur.execute("SELECT agent_id FROM agent_watchlist;")
            watch = {r[0] for r in cur.fetchall()}
        rows, info = [], []
        for agent_id in sorted(set(tx) | set(checks)):
            fee, n, days, allowance, n_cash, cash_bdt = tx.get(
                agent_id, (None, 0, 0, 0, 0, 0))
            reported, gaps, suspicious, duress, n_checks = checks.get(agent_id, (0, 0, 0, 0, 0))
            non_allow = max(1, n - allowance)
            rows.append({
                "agent_fee_ratio_over_official": float(fee) if fee is not None else 1.0,
                "agent_volume_daily_mean": float(n) / max(1, days),
                "agent_allowance_day_volume_ratio": float(allowance) / non_allow if n else 1.0,
                "agent_cash_gap_rate": float(gaps) / reported if reported else 0.0,
                "cash_gap_reported_count": float(gaps),
                "agent_cash_report_count": float(reported),
                "agent_cash_report_coverage": float(reported) / n_cash if n_cash else 0.0,
                "agent_cash_gap_missing": 0.0 if reported else 1.0,
                "agent_cash_gap_has_reports": 1.0 if reported else 0.0,
            })
            region, band = meta.get(agent_id, (None, None))
            info.append({"agent_id": agent_id, "region": region, "volume_band": band,
                         "cashouts_30d": int(n_cash), "cashout_bdt_30d": float(cash_bdt),
                         "checks_30d": int(n_checks), "suspicious_30d": int(suspicious),
                         "duress_30d": int(duress), "watchlisted": agent_id in watch})
        return pd.DataFrame(rows), pd.DataFrame(info)

    def _score_agents(self) -> dict[str, Any]:
        model = self.agent_model()
        X, info = self._agent_features()
        started = time.monotonic()
        if X.empty:
            return {"agents": [], "computed_at": _now().isoformat(), "window_days": WINDOW_DAYS}
        X = X[model.feature_names_]
        risk, contexts = model.score_combined(X)
        allowance_limit = self.config.get("models", {}).get("agent_anomaly", {}).get(
            "allowance_volume_threshold")
        agents = []
        for i, row in info.iterrows():
            x = X.iloc[i]
            ctx = contexts[i]
            r = float(risk[i])
            reasons = [{"feature": "fee_ratio_vs_official",
                        "value": round(float(x["agent_fee_ratio_over_official"]), 3),
                        "peer_median": round(float(ctx["peer_median"]), 3)}]
            if allowance_limit is not None and float(
                    x["agent_allowance_day_volume_ratio"]) > float(allowance_limit):
                reasons.append({"feature": "allowance_day_volume_spike",
                                "value": round(float(x["agent_allowance_day_volume_ratio"]), 2),
                                "peer_median": 1.0})
            if x["agent_cash_report_count"] > 0:
                reasons.append({"feature": "agent_cash_gap_rate",
                                "value": round(float(x["agent_cash_gap_rate"]), 3),
                                "peer_median": 0.0})
            agents.append({
                **row.to_dict(),
                "risk": round(r, 4), "level": model.get_risk_level(r).lower(),
                "reasons": reasons, "peer_group": ctx["peer_group"],
                "features": {k: round(float(v), 4) for k, v in x.items()},
            })
        agents.sort(key=lambda a: (-a["risk"], -a["suspicious_30d"]))
        return {
            "agents": agents,
            "levels": {lvl: sum(1 for a in agents if a["level"] == lvl)
                       for lvl in ("high", "medium", "low")},
            "model": "agent_anomaly_v1 (frozen trained weights, live features)",
            "window_days": WINDOW_DAYS,
            "computed_at": _now().isoformat(),
            "compute_seconds": round(time.monotonic() - started, 2),
        }

    def agent_board(self, force: bool = False, stale_ok: bool = True) -> dict[str, Any]:
        return CACHE.get("agent_risk", TTL["agent_risk"], self._score_agents, force, stale_ok)

    def agent_risk(self, agent_id: str) -> dict[str, Any]:
        board = self.agent_board()
        hit = next((a for a in board["agents"] if a["agent_id"] == agent_id), None)
        if hit is None:
            raise KeyError("No activity for this agent in the last 30 days")
        return {**hit, "computed_at": board["computed_at"], "window_days": WINDOW_DAYS,
                "provenance": "live database, last 30 days", "is_sample": False,
                "model_version": "agent_anomaly_v1"}

    # ------------------------------------------------------------------ assisted customers
    def _load_users(self, user_ids: list[str], since: datetime.datetime
                    ) -> tuple[list[dict], list[dict], list[dict]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT user_id, group_label, gender, age_band, region, urban_rural "
                        "FROM users WHERE user_id = ANY(%s);", (user_ids,))
            users = [{"user_id": r[0], "group_label": r[1] or "", "gender": r[2],
                      "age_band": r[3], "region": r[4], "urban_rural": r[5]}
                     for r in cur.fetchall()]
            cur.execute("SELECT txn_id, user_id, agent_id, txn_type, credit_source, amount, fee, "
                        "balance_after, channel, ts FROM transactions "
                        "WHERE user_id = ANY(%s) AND ts <= now();", (user_ids,))
            txns = [{"txn_id": r[0], "user_id": r[1], "agent_id": r[2], "txn_type": r[3],
                     "credit_source": r[4], "amount": float(r[5]),
                     "fee": float(r[6] or 0), "balance_after": float(r[7] or 0),
                     "channel": r[8], "ts": r[9].isoformat()} for r in cur.fetchall()]
            cur.execute("SELECT session_id, user_id, txn_id, pin_retries, pin_entry_ms, steps, ts "
                        "FROM sessions WHERE user_id = ANY(%s) AND ts > %s AND ts <= now();",
                        (user_ids, since))
            sessions = [{"session_id": r[0], "user_id": r[1], "txn_id": r[2],
                         "pin_retries": r[3] or 0, "pin_entry_ms": r[4] or 0,
                         "steps": r[5] or 0, "ts": r[6].isoformat()} for r in cur.fetchall()]
        return users, txns, sessions

    def _active_pool(self, limit: int) -> list[str]:
        """Customers with a cash-out and an app/USSD session in the window, newest first."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.user_id FROM sessions s
                WHERE s.ts > now() - make_interval(days => %s) AND s.ts <= now()
                GROUP BY s.user_id ORDER BY max(s.ts) DESC LIMIT %s;
                """, (WINDOW_DAYS, limit))
            return [r[0] for r in cur.fetchall()]

    def _score_users(self, user_ids: list[str]) -> tuple[pd.DataFrame, list[str]]:
        from app.models.features import extract_user_features

        now = _now()
        since = now - datetime.timedelta(days=WINDOW_DAYS)
        users, txns, sessions = self._load_users(user_ids, since)
        if not users:
            return pd.DataFrame(), []
        X, _y, _slices, ids = extract_user_features(
            users, txns, sessions, as_of=now, window_days=WINDOW_DAYS, config=self.config)
        model = self.assisted_model()
        X = X[model.feature_names_]
        proba = np.asarray(model.predict_proba(X))
        X = X.assign(_score=proba[:, 1] if proba.ndim == 2 else proba)
        return X, ids

    def _outreach(self) -> dict[str, Any]:
        started = time.monotonic()
        pool = self._active_pool(OUTREACH_POOL)
        X, ids = self._score_users(pool)
        threshold = float(self.assisted_model().classification_threshold)
        items = []
        if ids:
            for uid, (_, row) in zip(ids, X.iterrows()):
                items.append({
                    "user_id": uid, "assisted_score": round(float(row["_score"]), 4),
                    "likely_assisted": bool(row["_score"] >= threshold),
                    "cashouts_30d": int(row.get("cash_out_tx_count", 0)),
                    "top_agent_share": round(float(row.get("top_agent_share", 0)), 3),
                    "is_sample": False, "provenance": "live database, last 30 days",
                })
            items.sort(key=lambda r: (-r["assisted_score"], r["user_id"]))
        return {
            "total": len(items), "items": items[:500],
            "likely_assisted": sum(1 for i in items if i["likely_assisted"]),
            "scored_customers": len(items), "threshold": threshold,
            "synthetic": True, "is_sample": False,
            "provenance": "live database, last 30 days",
            "selection": f"{len(items)} customers with app/USSD activity in the last "
                         f"{WINDOW_DAYS} days, scored by the trained assisted classifier",
            "window_days": WINDOW_DAYS, "computed_at": _now().isoformat(),
            "compute_seconds": round(time.monotonic() - started, 2),
        }

    def outreach(self, force: bool = False, stale_ok: bool = True) -> dict[str, Any]:
        return CACHE.get("outreach", TTL["outreach"], self._outreach, force, stale_ok)

    def user_score(self, user_id: str) -> dict[str, Any]:
        X, ids = self._score_users([user_id])
        if not ids:
            raise KeyError("Customer not found")
        model = self.assisted_model()
        row = X.drop(columns=["_score"]).iloc[[0]]
        score = float(X["_score"].iloc[0])
        try:
            reasons = model.explain(row)
        except Exception:
            reasons = []
        return {
            "user_id": user_id, "score": round(score, 4),
            "assisted": bool(score >= float(model.classification_threshold)),
            "is_sample": False, "synthetic": True,
            "provenance": "live database, last 30 days",
            "model_version": "assisted_classifier_v1 (frozen trained weights, live features)",
            "top_reasons": reasons,
            "features": {k: (round(float(v), 4) if isinstance(v, (int, float, np.floating))
                             and math.isfinite(float(v)) else None)
                         for k, v in row.iloc[0].items()},
            "explanation_unit": "base-model raw log-odds, not calibrated probability",
            "computed_at": _now().isoformat(), "window_days": WINDOW_DAYS,
        }

    # ------------------------------------------------------------------ liquidity
    def _liquidity(self) -> dict[str, Any]:
        from app.intelligence.liquidity import train_and_evaluate

        started = time.monotonic()
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '60s';")
            cur.execute(
                """
                SELECT agent_id, (ts AT TIME ZONE 'Asia/Dhaka')::date d, sum(amount)
                FROM transactions
                WHERE txn_type = 'cash_out' AND agent_id IS NOT NULL
                  AND ts > now() - interval '91 days' AND ts <= now()
                GROUP BY 1, 2;
                """)
            rows = cur.fetchall()
            cur.execute("SELECT agent_id, volume_band FROM agents;")
            agents = [{"agent_id": r[0], "volume_band": r[1]} for r in cur.fetchall()]
        if not rows:
            raise KeyError("No cash-outs in the last 90 days")
        frame = pd.DataFrame(rows, columns=["agent_id", "day", "demand"])
        frame_all_agents = int(frame["agent_id"].nunique())
        frame["day"] = pd.to_datetime(frame["day"])
        frame["demand"] = frame["demand"].astype(float)
        totals = frame.groupby("agent_id")["demand"].sum().sort_values(ascending=False)
        active = sorted(totals.index[:LIQUIDITY_FORECAST_AGENTS])
        frame = frame[frame["agent_id"].isin(set(active))]
        today = pd.Timestamp(datetime.datetime.now(datetime.timezone(
            datetime.timedelta(hours=6))).date())
        days = pd.date_range(today - pd.Timedelta(days=89), today, freq="D")
        index = pd.MultiIndex.from_product([active, days], names=["agent_id", "day"])
        daily = (frame.groupby(["agent_id", "day"])["demand"].sum()
                 .reindex(index, fill_value=0.0).rename("demand").reset_index())
        totals = totals.loc[active].sort_values(ascending=False)
        rng = np.random.default_rng(7)
        train_agents = list(totals.index[: LIQUIDITY_TRAIN_AGENTS // 2])
        rest = list(totals.index[LIQUIDITY_TRAIN_AGENTS // 2:])
        if rest:
            train_agents += list(rng.choice(rest, size=min(len(rest),
                                                          LIQUIDITY_TRAIN_AGENTS // 2),
                                            replace=False))
        known = {a["agent_id"] for a in agents}
        result = train_and_evaluate(
            {"agents": [a for a in agents if a["agent_id"] in set(active) & known]},
            daily=daily, train_agents=train_agents,
            assumptions=[
                "Live ledger: the last 90 days of cash-outs up to today, re-trained every "
                "15 minutes.",
                "Recommended float rounds the peak P90 demand up to 500 BDT.",
                "Forecasts guide cash planning only; they never limit a customer's cash-out.",
            ])
        result["provenance"] = {"source": "live database", "history_days": 90,
                                "agents_with_cashouts": frame_all_agents,
                                "agents_forecast": len(active),
                                "agents_trained": len(train_agents)}
        result["computed_at"] = _now().isoformat()
        result["compute_seconds"] = round(time.monotonic() - started, 2)
        return result

    def liquidity(self, force: bool = False, stale_ok: bool = True) -> dict[str, Any]:
        return CACHE.get("liquidity", TTL["liquidity"], self._liquidity, force, stale_ok)

    # ------------------------------------------------------------------ uplift
    def _uplift(self) -> dict[str, Any]:
        from app.intelligence.uplift import train_and_evaluate, user_features

        started = time.monotonic()
        pool = self._active_pool(UPLIFT_POOL)
        users, txns, sessions = self._load_users(
            pool, _now() - datetime.timedelta(days=WINDOW_DAYS))
        if len(users) < 200:
            raise KeyError("Not enough active customers to train the uplift model")
        recent = _now() - datetime.timedelta(days=WINDOW_DAYS)
        txns = [t for t in txns if t["ts"] >= recent.isoformat()]
        features = user_features({"users": users, "transactions": txns,
                                  "sessions": sessions})
        result = train_and_evaluate({}, features=features, assumptions=[
            "Customer features come from the live ledger (last 30 days of activity).",
            "Campaign outcomes are simulated with a documented randomized-experiment model "
            "until a real campaign runs; policies are checked against that known truth.",
            "Channel costs and effect multipliers are ASSUMPTIONS, not upay prices.",
            "Outreach invites enrollment only; no offer, fee change or pressure tactic.",
            "Demographic fields are not model features.",
        ])
        result["provenance"] = {"source": "live database", "customers": len(users),
                                "window_days": WINDOW_DAYS}
        result["computed_at"] = _now().isoformat()
        result["compute_seconds"] = round(time.monotonic() - started, 2)
        return result

    def uplift(self, force: bool = False, stale_ok: bool = True) -> dict[str, Any]:
        return CACHE.get("uplift", TTL["uplift"], self._uplift, force, stale_ok)


def get_live() -> LiveIntelligence:
    from app.mandates.router import get_mandate_service

    return LiveIntelligence(get_mandate_service().get_connection)


# ---------------------------------------------------------------------- background refresh
_thread: threading.Thread | None = None


COMPUTE = {"agent_risk": "_score_agents", "outreach": "_outreach",
           "liquidity": "_liquidity", "uplift": "_uplift"}


def _child_compute(name: str, db_url: str, schema: str | None) -> Any:
    """Runs in a separate process so model training never stalls the API's requests."""
    from app.data.database import get_connection

    live = LiveIntelligence(lambda: get_connection(db_url, schema=schema))
    return getattr(live, COMPUTE[name])()


def _refresh_loop() -> None:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    from app.mandates.router import get_mandate_service

    time.sleep(5)
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    while True:
        service = get_mandate_service()
        for name in COMPUTE:
            hit = CACHE._values.get(name)
            if hit and time.monotonic() - hit[0] < TTL[name]:
                continue
            try:
                value = pool.submit(_child_compute, name, service.db_url,
                                    service.schema).result(timeout=600)
                CACHE._values[name] = (time.monotonic(), value)
            except Exception as exc:
                log.warning("live %s refresh failed: %s", name, exc)
        time.sleep(20)


def start_refresh() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_refresh_loop, name="sathi-live-ai", daemon=True)
        _thread.start()
