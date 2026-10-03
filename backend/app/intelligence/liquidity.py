"""Agent liquidity forecasting (Track 05: Merchant & Agent Intelligence).

Direct multi-horizon forecast of each agent's daily cash-out demand (BDT) for the next
7 days, using only information available at the forecast origin. A LightGBM point model
and a P90 quantile model are compared against seasonal-naive and moving-average baselines
on a later time window that is never used for training.

The P90 forecast drives a cash-float recommendation: an agent who opens the day with less
cash than the P90 demand risks turning customers away, which pushes customers toward
informal (and riskier) cash-out.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

HORIZON = 7
DHAKA_OFFSET = pd.Timedelta(hours=6)
FEATURES = [
    "h", "target_dow", "target_dom", "lag_same_dow", "mean_7", "mean_28", "std_28",
    "max_28", "zero_share_28", "trend_7_28", "volume_band_code",
]
VOLUME_BANDS = {"low": 0, "medium": 1, "high": 2}


def daily_cashout(data: dict[str, Any]) -> pd.DataFrame:
    """Agent x Dhaka-day cash-out totals, zero-filled across the whole window."""
    tx = pd.DataFrame(data["transactions"])
    tx = tx[(tx["txn_type"] == "cash_out") & tx["agent_id"].notna()].copy()
    stamps = pd.to_datetime(tx["ts"], utc=True, format="ISO8601")
    tx["day"] = (stamps + DHAKA_OFFSET).dt.tz_localize(None)
    tx["day"] = tx["day"].dt.normalize()
    daily = tx.groupby(["agent_id", "day"])["amount"].sum()
    agents = [a["agent_id"] for a in data["agents"]]
    days = pd.date_range(tx["day"].min(), tx["day"].max(), freq="D")
    index = pd.MultiIndex.from_product([agents, days], names=["agent_id", "day"])
    return daily.reindex(index, fill_value=0.0).rename("demand").reset_index()


def build_examples(daily: pd.DataFrame, agents: list[dict[str, Any]],
                   origins: list[pd.Timestamp], with_target: bool = True) -> pd.DataFrame:
    band = {a["agent_id"]: VOLUME_BANDS.get(a.get("volume_band"), 1) for a in agents}
    wide = daily.pivot(index="day", columns="agent_id", values="demand").sort_index()
    rows = []
    for origin in origins:
        hist = wide.loc[:origin]
        if len(hist) < 28:
            continue
        last7, last28 = hist.iloc[-7:], hist.iloc[-28:]
        mean7, mean28 = last7.mean(), last28.mean()
        stats = {
            "mean_7": mean7, "mean_28": mean28, "std_28": last28.std(ddof=0),
            "max_28": last28.max(), "zero_share_28": (last28 == 0).mean(),
            "trend_7_28": (mean7 + 1.0) / (mean28 + 1.0),
        }
        for h in range(1, HORIZON + 1):
            target_day = origin + pd.Timedelta(days=h)
            same_dow = target_day - pd.Timedelta(days=7)
            frame = pd.DataFrame({"agent_id": wide.columns})
            frame["origin"], frame["target_day"], frame["h"] = origin, target_day, h
            frame["target_dow"] = target_day.dayofweek
            frame["target_dom"] = target_day.day
            frame["lag_same_dow"] = hist.loc[same_dow].values if same_dow in hist.index else 0.0
            for key, series in stats.items():
                frame[key] = series.values
            frame["volume_band_code"] = frame["agent_id"].map(band).fillna(1)
            if with_target:
                if target_day not in wide.index:
                    continue
                frame["demand"] = wide.loc[target_day].values
            rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual, predicted = np.asarray(actual, float), np.asarray(predicted, float)
    total = actual.sum()
    return {
        "mae_bdt": float(np.mean(np.abs(actual - predicted))),
        "wape": float(np.abs(actual - predicted).sum() / total) if total else float("nan"),
        "bias_bdt": float(np.mean(predicted - actual)),
    }


def train_and_evaluate(data: dict[str, Any], seed: int = 42,
                       external: dict[str, Any] | None = None) -> dict[str, Any]:
    import lightgbm as lgb

    daily = daily_cashout(data)
    days = sorted(daily["day"].unique())
    # Time split by forecast origin. Targets of the last training origin end before the
    # first test origin, so no test-window demand is used for fitting.
    test_origins = [pd.Timestamp(d) for d in days[-HORIZON - 14:-HORIZON]]
    train_end = test_origins[0] - pd.Timedelta(days=HORIZON)
    train_origins = [pd.Timestamp(d) for d in days if 27 <= days.index(d) and
                     pd.Timestamp(d) <= train_end]
    train = build_examples(daily, data["agents"], train_origins)
    test = build_examples(daily, data["agents"], test_origins)

    params = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.9, random_state=seed,
                  verbose=-1)
    point = lgb.LGBMRegressor(objective="regression_l1", **params)
    point.fit(train[FEATURES], train["demand"])
    p90 = lgb.LGBMRegressor(objective="quantile", alpha=0.9, **params)
    p90.fit(train[FEATURES], train["demand"])

    def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
        pred = np.clip(point.predict(frame[FEATURES]), 0, None)
        upper = np.clip(p90.predict(frame[FEATURES]), 0, None)
        return {
            "rows": int(len(frame)),
            "agents": int(frame["agent_id"].nunique()),
            "lightgbm": metrics(frame["demand"], pred),
            "seasonal_naive": metrics(frame["demand"], frame["lag_same_dow"]),
            "moving_average_7": metrics(frame["demand"], frame["mean_7"]),
            "p90_coverage": float(np.mean(frame["demand"].values <= upper)),
        }

    evaluation = {"time_holdout": evaluate(test)}
    if external is not None:
        ext_daily = daily_cashout(external)
        ext_days = sorted(ext_daily["day"].unique())
        ext_origins = [pd.Timestamp(d) for d in ext_days[-HORIZON - 14:-HORIZON]]
        evaluation["unseen_agent_population"] = evaluate(
            build_examples(ext_daily, external["agents"], ext_origins))

    importance = sorted(
        zip(FEATURES, point.booster_.feature_importance("gain").tolist()),
        key=lambda item: -item[1])
    total_gain = sum(v for _, v in importance) or 1.0

    # Forecast from the last observed day.
    origin = pd.Timestamp(days[-1])
    future = build_examples(daily, data["agents"], [origin], with_target=False)
    future["forecast"] = np.clip(point.predict(future[FEATURES]), 0, None)
    future["p90"] = np.maximum(np.clip(p90.predict(future[FEATURES]), 0, None),
                               future["forecast"])
    # The alert compares with the busiest day of the last 35 days, so it spans one full
    # 30-day allowance cycle; an alert means demand beyond anything seen in that cycle.
    wide = daily.pivot(index="day", columns="agent_id", values="demand").sort_index()
    cycle_max = wide.loc[:origin].iloc[-35:].max()
    agents_out = []
    for agent_id, group in future.groupby("agent_id"):
        group = group.sort_values("h")
        typical = float(group["mean_28"].iloc[0])
        recent_max = float(cycle_max[agent_id])
        peak = group.loc[group["p90"].idxmax()]
        pressure = float(peak["p90"]) / typical if typical > 0 else 0.0
        agents_out.append({
            "agent_id": agent_id,
            "typical_daily_bdt": round(typical, 2),
            "max_daily_35d_bdt": round(recent_max, 2),
            # Alert when even the expected (not P90) peak beats the busiest recent day.
            "exceeds_recent_max": bool(float(group["forecast"].max()) > recent_max),
            "headroom_needed_bdt": round(max(0.0, float(peak["p90"]) - recent_max), 2),
            "days": [
                {"date": row.target_day.date().isoformat(),
                 "forecast_bdt": round(float(row.forecast), 2),
                 "p90_bdt": round(float(row.p90), 2)}
                for row in group.itertuples()
            ],
            "peak_date": peak["target_day"].date().isoformat(),
            "peak_p90_bdt": round(float(peak["p90"]), 2),
            "pressure_ratio": round(pressure, 3),
            "recommended_opening_float_bdt": round(float(np.ceil(peak["p90"] / 500.0) * 500), 2),
        })
    agents_out.sort(key=lambda a: (not a["exceeds_recent_max"], -a["headroom_needed_bdt"]))
    band_of = {a["agent_id"]: a.get("volume_band", "medium") for a in data["agents"]}
    cohorts = {}
    for band_name in VOLUME_BANDS:
        members = [a for a in agents_out if band_of.get(a["agent_id"]) == band_name]
        if not members:
            continue
        cohorts[band_name] = {
            "agents": len(members),
            "days": [
                {"date": members[0]["days"][i]["date"],
                 "forecast_bdt": round(float(np.median([m["days"][i]["forecast_bdt"]
                                                        for m in members])), 2),
                 "p90_bdt": round(float(np.median([m["days"][i]["p90_bdt"]
                                                   for m in members])), 2)}
                for i in range(HORIZON)
            ],
        }

    return {
        "model": "lightgbm_direct_multi_horizon_v1",
        "horizon_days": HORIZON,
        "forecast_origin": origin.date().isoformat(),
        "train_origins": [str(train_origins[0].date()), str(train_origins[-1].date())],
        "test_origins": [str(test_origins[0].date()), str(test_origins[-1].date())],
        "evaluation": evaluation,
        "feature_importance": [
            {"feature": name, "gain_share": round(gain / total_gain, 4)}
            for name, gain in importance
        ],
        "agents": agents_out,
        "cohorts": cohorts,
        "assumptions": [
            "Synthetic 90-day ledger; dates are simulation coordinates, not live days.",
            "Recommended float rounds the peak P90 demand up to 500 BDT.",
            "Forecasts guide cash planning only; they never limit a customer's cash-out.",
        ],
    }
