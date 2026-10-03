"""Uplift targeting for Sathi enrollment outreach (Track 04: Growth & Campaign Intelligence).

Question answered: which customers should receive outreach so that the outreach itself
causes them to enroll in Sathi mandates? A response model finds people likely to enroll
anyway; an uplift model finds people whose behavior changes because of the outreach.

Data: a synthetic randomized experiment layered on the synthetic ledger. Treatment is
assigned at random. The true individual effect is injected with a documented formula, so
the evaluation can compare each targeting policy with the known incremental truth.
Ground-truth labels (group_label) are used only by the simulator, never as model inputs.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FEATURES = [
    "cashout_count", "cashout_median_bdt", "top_agent_share", "withdrawn_fraction",
    "credit_to_cashout_hours", "pin_retries_mean", "pin_entry_seconds", "service_count",
    "app_share",
]

# ASSUMPTION channel costs (BDT per contact) and effect multipliers on the base uplift.
CHANNELS = {
    "sms": {"cost_bdt": 0.5, "effect": 0.35},
    "ivr_call": {"cost_bdt": 3.0, "effect": 1.0},
    "agent_visit": {"cost_bdt": 40.0, "effect": 1.6},
}


def user_features(data: dict[str, Any]) -> pd.DataFrame:
    tx = pd.DataFrame(data["transactions"])
    tx["ts"] = pd.to_datetime(tx["ts"], utc=True, format="ISO8601")
    sessions = pd.DataFrame(data["sessions"])
    users = pd.DataFrame(data["users"])[["user_id", "group_label"]]

    cash = tx[tx["txn_type"] == "cash_out"]
    credit = tx[tx["txn_type"] == "credit"]
    g = cash.groupby("user_id")
    out = pd.DataFrame({
        "cashout_count": g.size(),
        "cashout_median_bdt": g["amount"].median(),
        "cashout_total": g["amount"].sum(),
    })
    top = cash.groupby(["user_id", "agent_id"]).size().groupby(level=0).max()
    out["top_agent_share"] = top / out["cashout_count"]
    out["withdrawn_fraction"] = out["cashout_total"] / credit.groupby("user_id")["amount"].sum()

    first_cash = cash.sort_values("ts").groupby("user_id")["ts"].first()
    first_credit = credit.sort_values("ts").groupby("user_id")["ts"].first()
    out["credit_to_cashout_hours"] = (first_cash - first_credit).dt.total_seconds() / 3600
    s = sessions.groupby("user_id")
    out["pin_retries_mean"] = s["pin_retries"].mean()
    out["pin_entry_seconds"] = s["pin_entry_ms"].median() / 1000
    out["service_count"] = tx[tx["txn_type"].isin(["send", "bill_pay"])].groupby("user_id").size()
    out["app_share"] = (tx["channel"] == "app").groupby(tx["user_id"]).mean()
    out = users.set_index("user_id").join(out, how="left")
    out[FEATURES] = out[FEATURES].fillna(0.0)
    out["withdrawn_fraction"] = out["withdrawn_fraction"].clip(0, 2)
    out["credit_to_cashout_hours"] = out["credit_to_cashout_hours"].clip(-1, 24 * 60)
    return out.reset_index()


def simulate_experiment(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Randomized outreach experiment with an injected, documented heterogeneous effect.

    Base enrollment propensity rises with digital comfort. The outreach effect is:
    - assisted groups (persuadables): +0.10 to +0.35, larger with agent dependence;
    - independent users with high digital usage (sure things): about 0;
    - independent users with very low engagement (sleeping dogs): -0.04.
    """
    rng = np.random.default_rng(seed)
    f = frame.copy()
    assisted = f["group_label"].str.startswith("assisted").to_numpy()
    digital = np.clip(f["app_share"].to_numpy(), 0, 1)
    dependence = np.clip(f["top_agent_share"].to_numpy(), 0, 1)
    base = 0.04 + 0.18 * digital
    tau = np.where(assisted, 0.10 + 0.25 * dependence, 0.0)
    sleeping = (~assisted) & (f["service_count"].to_numpy() <= 1) & (digital < 0.4)
    tau = np.where(sleeping, -0.04, tau)
    f["true_uplift"] = tau
    f["treated"] = rng.random(len(f)) < 0.5
    p = np.clip(base + np.where(f["treated"], tau, 0.0), 0.001, 0.999)
    f["enrolled"] = rng.random(len(f)) < p
    return f


def qini_curve(uplift_score: np.ndarray, treated: np.ndarray, outcome: np.ndarray,
               points: int = 20) -> list[dict[str, float]]:
    order = np.argsort(-uplift_score, kind="stable")
    t, y = treated[order], outcome[order]
    n = len(order)
    curve = [{"targeted_share": 0.0, "incremental": 0.0}]
    for k in range(1, points + 1):
        m = int(round(n * k / points))
        nt, nc = t[:m].sum(), (~t[:m]).sum()
        yt, yc = y[:m][t[:m]].sum(), y[:m][~t[:m]].sum()
        inc = yt - yc * (nt / nc) if nc else 0.0
        curve.append({"targeted_share": k / points, "incremental": float(inc)})
    return curve


def qini_coefficient(curve: list[dict[str, float]]) -> float:
    xs = np.array([p["targeted_share"] for p in curve])
    ys = np.array([p["incremental"] for p in curve])
    random_line = ys[-1] * xs
    return float(np.trapezoid(ys - random_line, xs))


def train_and_evaluate(data: dict[str, Any], seed: int = 42,
                       features: pd.DataFrame | None = None,
                       assumptions: list[str] | None = None) -> dict[str, Any]:
    import lightgbm as lgb

    frame = simulate_experiment(features if features is not None else user_features(data),
                                seed)
    rng = np.random.default_rng(seed + 1)
    test_mask = rng.random(len(frame)) < 0.3
    train, test = frame[~test_mask], frame[test_mask]
    params = dict(n_estimators=250, learning_rate=0.05, num_leaves=15, min_child_samples=60,
                  random_state=seed, verbose=-1)

    m_t = lgb.LGBMClassifier(**params).fit(train.loc[train["treated"], FEATURES],
                                           train.loc[train["treated"], "enrolled"])
    m_c = lgb.LGBMClassifier(**params).fit(train.loc[~train["treated"], FEATURES],
                                           train.loc[~train["treated"], "enrolled"])
    p_t = m_t.predict_proba(test[FEATURES])[:, 1]
    p_c = m_c.predict_proba(test[FEATURES])[:, 1]
    uplift = p_t - p_c

    treated = test["treated"].to_numpy()
    outcome = test["enrolled"].to_numpy()
    policies = {
        "uplift_t_learner": uplift,
        "response_model": p_t,
        "agent_dependence_rule": test["top_agent_share"].to_numpy(),
        "random": np.random.default_rng(seed + 2).random(len(test)),
    }
    comparison = {}
    for name, score in policies.items():
        curve = qini_curve(score, treated, outcome)
        top = np.argsort(-score, kind="stable")[: int(0.2 * len(test))]
        comparison[name] = {
            "qini_coefficient": round(qini_coefficient(curve), 3),
            "observed_incremental_top20": round(curve[4]["incremental"], 1),
            "true_incremental_top20": round(float(test["true_uplift"].to_numpy()[top].sum()), 1),
            "curve": curve,
        }

    importance = sorted(
        zip(FEATURES, (m_t.booster_.feature_importance("gain")
                       + m_c.booster_.feature_importance("gain")).tolist()),
        key=lambda item: -item[1])
    total = sum(v for _, v in importance) or 1.0

    scored = test.assign(predicted_uplift=uplift, p_treated=p_t, p_control=p_c)
    scored = scored.sort_values("predicted_uplift", ascending=False)
    candidates = [
        {"user_id": r.user_id, "predicted_uplift": round(float(r.predicted_uplift), 4),
         "p_if_contacted": round(float(r.p_treated), 4),
         "p_if_not": round(float(r.p_control), 4),
         "agent_dependence": round(float(r.top_agent_share), 3),
         "app_share": round(float(r.app_share), 3)}
        for r in scored.itertuples()
    ]
    corr = float(np.corrcoef(uplift, test["true_uplift"])[0, 1])
    return {
        "model": "t_learner_lightgbm_v1",
        "experiment": {
            "users": int(len(frame)), "treated_share": round(float(frame["treated"].mean()), 3),
            "train_users": int(len(train)), "holdout_users": int(len(test)),
            "holdout_treated": int(treated.sum()),
            "observed_ate": round(float(outcome[treated].mean() - outcome[~treated].mean()), 4),
            "true_ate": round(float(test["true_uplift"].mean()), 4),
        },
        "uplift_truth_correlation": round(corr, 3),
        "policies": comparison,
        "feature_importance": [
            {"feature": n, "gain_share": round(g / total, 4)} for n, g in importance
        ],
        "channels": CHANNELS,
        "candidates": candidates,
        "assumptions": assumptions or [
            "Synthetic randomized experiment; the true effect formula is injected and "
            "documented so policies can be checked against known truth.",
            "Channel costs and effect multipliers are ASSUMPTIONS, not upay prices.",
            "Outreach invites enrollment only; no offer, fee change or pressure tactic.",
            "Demographic fields are not model features.",
        ],
    }


def optimize_budget(candidates: list[dict[str, Any]], budget_bdt: float,
                    channels: dict[str, dict[str, float]] = CHANNELS,
                    min_uplift: float = 0.0) -> dict[str, Any]:
    """Multiple-choice knapsack greedy: at most one channel per customer.

    For each customer the channels form an efficient frontier (more cost, more expected
    incremental enrollment). Every step on a frontier is an "upgrade" with its own
    gain-per-taka; frontiers are concave, so taking upgrades globally by ratio keeps each
    customer's upgrades in order. Customers with no positive expected uplift are never
    contacted (avoids sleeping dogs and spam).
    """
    ordered = sorted(channels.items(), key=lambda item: item[1]["cost_bdt"])
    steps = []
    skipped = 0
    for c in candidates:
        base = c["predicted_uplift"]
        if base <= min_uplift:
            skipped += 1
            continue
        frontier = [("none", 0.0, 0.0)]
        for name, ch in ordered:
            gain = min(base * ch["effect"], 1.0 - c["p_if_not"])
            if gain <= frontier[-1][2]:
                continue
            # Drop earlier points that the new one dominates on ratio (keep it concave).
            while len(frontier) >= 2:
                (_, c1, g1), (_, c2, g2) = frontier[-2], frontier[-1]
                if (g2 - g1) / (c2 - c1) <= (gain - g2) / (ch["cost_bdt"] - c2):
                    frontier.pop()
                else:
                    break
            frontier.append((name, ch["cost_bdt"], gain))
        for i in range(1, len(frontier)):
            (_, c_prev, g_prev), (name, cost, gain) = frontier[i - 1], frontier[i]
            steps.append(((gain - g_prev) / (cost - c_prev), c["user_id"], i, name,
                          cost - c_prev, gain - g_prev))
    steps.sort(key=lambda s: -s[0])

    spent, gained = 0.0, 0.0
    level: dict[str, int] = {}
    choice: dict[str, tuple[str, float]] = {}
    for _ratio, user_id, index, name, d_cost, d_gain in steps:
        if level.get(user_id, 0) != index - 1 or spent + d_cost > budget_bdt:
            continue
        spent += d_cost
        gained += d_gain
        level[user_id] = index
        choice[user_id] = (name, choice.get(user_id, ("", 0.0))[1] + d_gain)

    plan = {name: 0 for name in channels}
    for name, _gain in choice.values():
        plan[name] += 1
    first = sorted(choice.items(), key=lambda item: -item[1][1])[:25]
    return {
        "budget_bdt": budget_bdt,
        "spent_bdt": round(spent, 2),
        "contacts": len(choice),
        "by_channel": plan,
        "expected_incremental_enrollments": round(gained, 1),
        "cost_per_incremental_bdt": round(spent / gained, 2) if gained else None,
        "skipped_non_positive_uplift": skipped,
        "first_contacts": [
            {"user_id": user_id, "channel": name, "expected_incremental": round(gain, 4)}
            for user_id, (name, gain) in first
        ],
    }
