"""Feature extraction and engineering for Sathi models.

Transforms raw transaction and session histories into behavioral feature
representations. Strictly verifies against feature leakage guard before
any feature matrix is exposed to models.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.features.guard import assert_feature_columns


def extract_user_features(
    users_data: list[dict[str, Any]],
    transactions_data: list[dict[str, Any]],
    sessions_data: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, list[str]]:
    """Extract behavioral features for customers.

    Returns:
        X (pd.DataFrame): Pure numeric behavioral features adhering to guard allowlist.
        y (pd.Series): Binary ground-truth target (1 for assisted, 0 for independent).
        slices (pd.DataFrame): Evaluation slices (gender, age_band, region, urban_rural).
        user_ids (list[str]): Customer IDs preserving alignment.
    """
    # Group transactions and sessions by user_id
    tx_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tx in transactions_data:
        tx_by_user[tx["user_id"]].append(tx)

    sessions_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sess in sessions_data:
        sessions_by_user[sess["user_id"]].append(sess)

    records: list[dict[str, Any]] = []
    targets: list[int] = []
    slice_rows: list[dict[str, Any]] = []
    user_ids: list[str] = []

    for u in users_data:
        uid = u["user_id"]
        user_ids.append(uid)

        # Ground truth target: assisted vs independent
        g_label = u.get("group_label", "")
        is_assisted = 1 if ("assisted" in g_label) else 0
        targets.append(is_assisted)

        # Demographic / fairness evaluation slices (never model inputs)
        slice_rows.append(
            {
                "gender": u.get("gender", "unknown"),
                "age_band": u.get("age_band", "unknown"),
                "region": u.get("region", "unknown"),
                "urban_rural": u.get("urban_rural", "unknown"),
            }
        )

        user_txs = tx_by_user.get(uid, [])
        user_sess = sessions_by_user.get(uid, [])

        # Sort transactions chronologically
        user_txs_sorted = sorted(user_txs, key=lambda t: t["ts"])

        # Split transactions by type
        cashouts = [t for t in user_txs_sorted if t["txn_type"] == "cash_out"]
        credits = [t for t in user_txs_sorted if t["txn_type"] == "credit"]
        sends = [t for t in user_txs_sorted if t["txn_type"] == "send"]
        bills = [t for t in user_txs_sorted if t["txn_type"] == "bill_pay"]

        # 1. Top agent share & concentration
        if cashouts:
            agent_counts: dict[str, int] = defaultdict(int)
            for co in cashouts:
                aid = co.get("agent_id")
                if aid:
                    agent_counts[aid] += 1
            if agent_counts:
                max_co = max(agent_counts.values())
                top_agent_share = float(max_co) / len(cashouts)
                shares = [c / len(cashouts) for c in agent_counts.values()]
                top_agent_concentration = float(sum(s * s for s in shares))
            else:
                top_agent_share = 0.0
                top_agent_concentration = 0.0
        else:
            top_agent_share = 0.0
            top_agent_concentration = 0.0

        # 2. Cash out metrics
        co_count = len(cashouts)
        co_amounts = [float(t["amount"]) for t in cashouts]
        co_total = float(sum(co_amounts))
        co_mean = float(np.mean(co_amounts)) if co_amounts else 0.0
        co_median = float(np.median(co_amounts)) if co_amounts else 0.0
        co_std = float(np.std(co_amounts)) if len(co_amounts) > 1 else 0.0
        co_min = float(min(co_amounts)) if co_amounts else 0.0
        co_max = float(max(co_amounts)) if co_amounts else 0.0

        # 3. Credit metrics
        cr_count = len(credits)
        cr_amounts = [float(t["amount"]) for t in credits]
        cr_total = float(sum(cr_amounts))
        cr_mean = float(np.mean(cr_amounts)) if cr_amounts else 0.0

        # 4. Credit to cashout hours delay
        delays_hours: list[float] = []
        for co in cashouts:
            co_dt = datetime.datetime.fromisoformat(co["ts"])
            preceding_credits = [
                c for c in credits if datetime.datetime.fromisoformat(c["ts"]) <= co_dt
            ]
            if preceding_credits:
                last_cr = preceding_credits[-1]
                last_cr_dt = datetime.datetime.fromisoformat(last_cr["ts"])
                diff_sec = (co_dt - last_cr_dt).total_seconds()
                delays_hours.append(max(0.0, diff_sec / 3600.0))

        if delays_hours:
            cr_to_co_mean = float(np.mean(delays_hours))
            cr_to_co_median = float(np.median(delays_hours))
            cr_to_co_min = float(min(delays_hours))
        else:
            # Default to neutral synthetic prior
            cr_to_co_mean = 72.0
            cr_to_co_median = 72.0
            cr_to_co_min = 72.0

        # 5. Withdrawn balance ratio
        withdrawn_ratios: list[float] = []
        for co in cashouts:
            amt = float(co["amount"])
            bal_after = float(co.get("balance_after", 0.0))
            fee = float(co.get("fee", 0.0))
            bal_before = bal_after + fee + amt
            if bal_before > 0:
                withdrawn_ratios.append(min(1.0, amt / bal_before))

        withdrawn_ratio_mean = float(np.mean(withdrawn_ratios)) if withdrawn_ratios else 0.0
        withdrawn_ratio_max = float(max(withdrawn_ratios)) if withdrawn_ratios else 0.0

        # 6. Balances
        balances = [float(t.get("balance_after", 0.0)) for t in user_txs_sorted]
        balance_end = balances[-1] if balances else 5000.0
        balance_mean = float(np.mean(balances)) if balances else 5000.0
        balance_min = float(min(balances)) if balances else 5000.0

        # 7. PIN sessions behavior
        retries = [int(s.get("pin_retries", 0)) for s in user_sess]
        pin_retries_total = sum(retries)
        pin_retries_mean = float(np.mean(retries)) if retries else 0.0
        pin_retries_max = max(retries) if retries else 0

        pin_sec = [float(s.get("pin_entry_ms", 0)) / 1000.0 for s in user_sess]
        pin_entry_seconds_mean = float(np.mean(pin_sec)) if pin_sec else 6.0
        pin_entry_seconds_median = float(np.median(pin_sec)) if pin_sec else 6.0
        pin_entry_seconds_std = float(np.std(pin_sec)) if len(pin_sec) > 1 else 0.0

        steps = [int(s.get("steps", 4)) for s in user_sess]
        session_steps_mean = float(np.mean(steps)) if steps else 4.0
        session_steps_max = max(steps) if steps else 4

        # 8. Diversity of services
        distinct_types = {t["txn_type"] for t in user_txs}
        service_diversity_count = len(distinct_types)

        # 9. Send & Bill Pay
        send_count = len(sends)
        send_total = float(sum(float(t["amount"]) for t in sends))
        bill_count = len(bills)
        bill_total = float(sum(float(t["amount"]) for t in bills))

        # 10. Channel and fees
        assisted_txs = [t for t in user_txs if t.get("channel") == "agent_initiated"]
        agent_assisted_tx_ratio = float(len(assisted_txs)) / len(user_txs) if user_txs else 0.0
        fees = [float(t.get("fee", 0.0)) for t in user_txs]
        fee_total = float(sum(fees))
        all_amounts = [float(t["amount"]) for t in user_txs]
        fee_to_amount_ratio = float(fee_total) / sum(all_amounts) if sum(all_amounts) > 0 else 0.0

        row = {
            "top_agent_share": top_agent_share,
            "top_agent_concentration": top_agent_concentration,
            "cash_out_tx_count": float(co_count),
            "cash_out_total_amount": co_total,
            "cash_out_amount_mean": co_mean,
            "cash_out_amount_median": co_median,
            "cash_out_amount_std": co_std,
            "cash_out_amount_min": co_min,
            "cash_out_amount_max": co_max,
            "credit_tx_count": float(cr_count),
            "credit_total_amount": cr_total,
            "credit_amount_mean": cr_mean,
            "credit_to_cashout_hours_mean": cr_to_co_mean,
            "credit_to_cashout_hours_min": cr_to_co_min,
            "credit_to_cashout_hours_median": cr_to_co_median,
            "withdrawn_balance_ratio_mean": withdrawn_ratio_mean,
            "withdrawn_balance_ratio_max": withdrawn_ratio_max,
            "balance_end": balance_end,
            "balance_mean": balance_mean,
            "balance_min": balance_min,
            "pin_retries_total": float(pin_retries_total),
            "pin_retries_mean": pin_retries_mean,
            "pin_retries_max": float(pin_retries_max),
            "pin_entry_seconds_mean": pin_entry_seconds_mean,
            "pin_entry_seconds_median": pin_entry_seconds_median,
            "pin_entry_seconds_std": pin_entry_seconds_std,
            "session_steps_mean": session_steps_mean,
            "session_steps_max": float(session_steps_max),
            "service_diversity_count": float(service_diversity_count),
            "send_tx_count": float(send_count),
            "send_total_amount": send_total,
            "bill_pay_tx_count": float(bill_count),
            "bill_pay_total_amount": bill_total,
            "agent_assisted_tx_ratio": agent_assisted_tx_ratio,
            "fee_total_paid": fee_total,
            "fee_to_amount_ratio": fee_to_amount_ratio,
        }
        records.append(row)

    df_X = pd.DataFrame(records)
    # Strictly enforce feature guard
    assert_feature_columns(df_X)

    return df_X, pd.Series(targets, name="target"), pd.DataFrame(slice_rows), user_ids


def extract_agent_features(
    agents_data: list[dict[str, Any]],
    transactions_data: list[dict[str, Any]],
    official_fee_rate: float | None = None,
    start_timestamp: str | None = None,
    allowance_cycle_days: int | None = None,
    allowance_day_of_cycle: int | None = None,
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, list[str]]:
    """Extract behavioral features for agents.

    Returns:
        X (pd.DataFrame): Pure numeric behavioral features adhering to guard allowlist.
        y (pd.Series): Binary ground truth (1 for skimmer, 0 for normal/honest).
        meta_df (pd.DataFrame): Evaluation metadata returned separately
            (region, volume_band, agent_type).
        agent_ids (list[str]): Agent IDs.
    """
    if config is not None:
        from app.data.config import validate_config

        cfg = validate_config(config)
    else:
        from app.data.config import load_config

        cfg = load_config(config_path)

    sim_cfg = cfg.get("simulation")
    if not isinstance(sim_cfg, dict):
        from app.data.config import ConfigError

        raise ConfigError("Missing required 'simulation' mapping in configuration.")

    if official_fee_rate is not None:
        if (
            isinstance(official_fee_rate, bool)
            or not isinstance(official_fee_rate, (int, float))
            or not math.isfinite(official_fee_rate)
            or official_fee_rate <= 0.0
        ):
            raise ValueError("official_fee_rate must be a positive finite number.")
        fee_rate = float(official_fee_rate)
    else:
        if "official_fee_rate" not in sim_cfg:
            from app.data.config import ConfigError

            raise ConfigError("simulation.official_fee_rate is required in config.")
        fee_rate = float(sim_cfg["official_fee_rate"])

    if start_timestamp is not None:
        if not isinstance(start_timestamp, str):
            raise ValueError("start_timestamp must be an ISO 8601 string.")
        start_ts = start_timestamp
    else:
        if "start_timestamp" not in sim_cfg:
            from app.data.config import ConfigError

            raise ConfigError("simulation.start_timestamp is required in config.")
        start_ts = str(sim_cfg["start_timestamp"])

    if allowance_cycle_days is not None:
        if (
            isinstance(allowance_cycle_days, bool)
            or not isinstance(allowance_cycle_days, int)
            or allowance_cycle_days < 1
        ):
            raise ValueError("allowance_cycle_days must be an integer >= 1.")
        cycle_days = allowance_cycle_days
    else:
        credits_cfg = sim_cfg.get("credits", {})
        allowance_cfg = credits_cfg.get("allowance", {})
        if "cycle_days" not in allowance_cfg:
            from app.data.config import ConfigError

            raise ConfigError("simulation.credits.allowance.cycle_days is required in config.")
        cycle_days = int(allowance_cfg["cycle_days"])

    if allowance_day_of_cycle is not None:
        if (
            isinstance(allowance_day_of_cycle, bool)
            or not isinstance(allowance_day_of_cycle, int)
            or allowance_day_of_cycle < 0
            or allowance_day_of_cycle >= cycle_days
        ):
            raise ValueError("allowance_day_of_cycle must be inside the configured cycle.")
        day_of_cycle = allowance_day_of_cycle
    else:
        if "allowance_day_of_cycle" not in sim_cfg:
            from app.data.config import ConfigError

            raise ConfigError("simulation.allowance_day_of_cycle is required in config.")
        day_of_cycle = int(sim_cfg["allowance_day_of_cycle"])

    start_dt = datetime.datetime.fromisoformat(start_ts.replace("Z", "+00:00"))

    tx_by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tx in transactions_data:
        aid = tx.get("agent_id")
        if aid:
            tx_by_agent[aid].append(tx)

    records: list[dict[str, Any]] = []
    targets: list[int] = []
    agent_ids: list[str] = []

    for a in agents_data:
        aid = a["agent_id"]
        agent_ids.append(aid)

        atype = a.get("agent_type", "")
        targets.append(1 if atype == "skimmer" else 0)

        txs = tx_by_agent.get(aid, [])
        if txs:
            fee_ratios: list[float] = []
            days_set: set[str] = set()
            allowance_tx_count = 0
            for t in txs:
                if t.get("txn_type") == "cash_out":
                    amt = float(t["amount"])
                    fee = float(t.get("fee", 0.0))
                    expected_fee = amt * fee_rate
                    if expected_fee > 0:
                        fee_ratios.append(fee / expected_fee)
                dt_str = t["ts"][:10]
                days_set.add(dt_str)
                # Allowance day check: determined by configured start_timestamp + cycle
                try:
                    dt = datetime.datetime.fromisoformat(t["ts"].replace("Z", "+00:00"))
                    if dt.tzinfo is None and start_dt.tzinfo is not None:
                        dt = dt.replace(tzinfo=start_dt.tzinfo)
                    elif dt.tzinfo is not None and start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=dt.tzinfo)
                    day_offset = (dt.date() - start_dt.date()).days
                    if (
                        day_offset >= 0
                        and (day_offset % cycle_days) == day_of_cycle
                    ):
                        allowance_tx_count += 1
                except Exception:
                    pass

            fee_ratio_over_official = float(np.mean(fee_ratios)) if fee_ratios else 1.0
            num_days = max(1, len(days_set))
            volume_daily_mean = float(len(txs)) / float(num_days)
            non_allowance_tx = len(txs) - allowance_tx_count
            allowance_ratio = float(allowance_tx_count) / max(1, non_allowance_tx)
        else:
            fee_ratio_over_official = 1.0
            volume_daily_mean = 0.0
            allowance_ratio = 1.0

        records.append(
            {
                "agent_fee_ratio_over_official": fee_ratio_over_official,
                "agent_volume_daily_mean": volume_daily_mean,
                "agent_allowance_day_volume_ratio": allowance_ratio,
            }
        )

    df_X = pd.DataFrame(records)
    assert_feature_columns(df_X)

    meta_df = pd.DataFrame(
        [
            {
                "region": a.get("region", "dhaka"),
                "volume_band": a.get("volume_band", "standard"),
                "agent_type": a.get("agent_type", "normal"),
            }
            for a in agents_data
        ]
    )

    return df_X, pd.Series(targets, name="target"), meta_df, agent_ids
