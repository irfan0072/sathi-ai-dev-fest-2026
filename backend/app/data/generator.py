"""Config-driven synthetic dataset and cash observations generator for Sathi.

Assisted share parameters (0.2 for normal/high-volume honest, 0.6 for skimmers)
represent relative sampling propensities, not exact fraction guarantees with
a 35% global assisted population; actual realized counts may differ.
Service count distributions serve as proxies for activity-use counts rather than
unique service categories, as the underlying database schema permits exactly four
transaction types ('credit', 'cash_out', 'send', 'bill_pay').
"""

import math
import random
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from app.data.config import ConfigError, load_config, validate_config
from app.data.database import validate_dataset


class DatasetResult(dict):
    """Dictionary containing the main dataset conforming to database loader whitelists.

    Provides convenient attribute access to the simulation observations sidecar.
    """

    def __init__(self, main_dataset: dict[str, Any], observations: dict[str, Any]):
        super().__init__(main_dataset)
        self.observations = observations


def sample_poisson(rng: random.Random, lam: float) -> int:
    """Sample an integer from a Poisson distribution using Knuth's algorithm with pure stdlib."""
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    prod = rng.random()
    count = 0
    while prod > limit:
        count += 1
        prod *= rng.random()
    return count


def _quantize_float(val: Decimal | float) -> float:
    """Quantize money to two decimal places for NUMERIC(12,2)."""
    if isinstance(val, Decimal):
        return float(val.quantize(Decimal("0.01")))
    return float(round(val, 2))


def build_canonical_agent_registry(
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build canonical stable global agent registry using seed_train RNG.

    Canonical agents are stable across generation seeds via independent seed_train RNG.
    """
    if config is None:
        raw_config = load_config()
    else:
        raw_config = validate_config(config)

    sim_cfg = raw_config["simulation"]
    fairness_cfg = raw_config.get("fairness", {})
    slice_cats = fairness_cfg.get("slice_categories", {})

    seed_train = sim_cfg["seed_train"]
    total_agents = sim_cfg["agents"]
    agent_mix = sim_cfg["agent_mix"]

    fairness_regions = slice_cats["region"]
    start_ts_str = sim_cfg["start_timestamp"]

    agent_rng = random.Random(seed_train)

    canonical_types = (
        ["normal"] * agent_mix["normal"]
        + ["high_volume_honest"] * agent_mix["high_volume_honest"]
        + ["skimmer"] * agent_mix["skimmers"]
    )
    if len(canonical_types) != total_agents:
        raise ConfigError(
            f"agent_mix sum ({len(canonical_types)}) does not match agents count ({total_agents})"
        )
    agent_rng.shuffle(canonical_types)

    canonical_agents: list[dict[str, Any]] = []
    for idx in range(total_agents):
        aid = f"A_{idx:06d}"
        atype = canonical_types[idx]
        region = agent_rng.choice(fairness_regions)
        if atype == "high_volume_honest":
            volume_band = "high"
        elif atype == "skimmer":
            volume_band = agent_rng.choice(["medium", "high", "standard"])
        else:
            volume_band = agent_rng.choice(["low", "medium", "standard"])

        arec = {
            "agent_id": aid,
            "region": region,
            "volume_band": volume_band,
            "agent_type": atype,
            "created_at": start_ts_str,
        }
        canonical_agents.append(arec)

    return canonical_agents


def generate_dataset(
    config: dict[str, Any] | None = None,
    seed: int | None = None,
    agent_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    customers: int | None = None,
    return_observations: bool = False,
    canonical_agents: list[dict[str, Any]] | None = None,
) -> DatasetResult | tuple[dict[str, Any], dict[str, Any]]:
    """Generate synthetic Sathi dataset and sidecar cash observations.

    Parameters:
        config: Simulation configuration dictionary (loads data/config.yaml if None).
        seed: Random seed for customer/timeline generation (defaults to simulation.seed_train).
        agent_ids: Optional explicit agent IDs for cohort-isolated routing (T015).
        customers: Optional customer count override (e.g. for smoke testing or small fixtures).
        return_observations: If True, returns (main_dataset, observations).
                             If False, returns DatasetResult.
        canonical_agents: Optional pre-built canonical agents registry for reuse across cohorts.

    Canonical agents are stable across generation seeds via independent seed_train RNG.
    """
    if config is None:
        raw_config = load_config()
    else:
        raw_config = validate_config(config)

    sim_cfg = raw_config["simulation"]
    fairness_cfg = raw_config.get("fairness", {})
    slice_cats = fairness_cfg.get("slice_categories", {})

    if seed is not None:
        if type(seed) is not int or isinstance(seed, bool) or not (0 <= seed < 2**31):
            raise ConfigError(
                f"Explicit seed override must be a nonnegative 31-bit integer, got {seed!r}"
            )
        gen_seed = seed
    else:
        gen_seed = sim_cfg["seed_train"]

    if customers is not None:
        if type(customers) is not int or isinstance(customers, bool) or customers <= 0:
            raise ConfigError(
                f"Explicit customers override must be a positive integer, got {customers!r}"
            )
        num_customers = customers
    else:
        num_customers = sim_cfg["customers"]

    start_ts_str = sim_cfg["start_timestamp"]
    start_dt = datetime.fromisoformat(start_ts_str.replace("Z", "+00:00"))
    days = sim_cfg["days"]
    max_dt = start_dt + timedelta(days=days)

    official_fee_rate = Decimal(str(sim_cfg["official_fee_rate"]))

    # -------------------------------------------------------------------------
    # 1. Canonical Agents Registry (Independent RNG using seed_train)
    # -------------------------------------------------------------------------
    if canonical_agents is None:
        canonical_agents = build_canonical_agent_registry(raw_config)
    canonical_agents_dict: dict[str, dict[str, Any]] = {
        a["agent_id"]: a for a in canonical_agents
    }

    # Filter to cohort agents if explicit agent_ids provided; reject unknown IDs
    if agent_ids is not None:
        if not isinstance(agent_ids, (list, set, tuple)):
            raise ConfigError("Supplied agent_ids must be an iterable collection")
        target_ids = set(agent_ids)
        if not target_ids:
            raise ConfigError("Supplied agent_ids cannot be empty")
        canonical_ids = set(canonical_agents_dict.keys())
        unknown_ids = target_ids - canonical_ids
        if unknown_ids:
            raise ConfigError(
                f"Supplied agent_ids contains unknown agent IDs: {sorted(unknown_ids)}"
            )
        cohort_agents = [canonical_agents_dict[aid] for aid in sorted(target_ids)]
    else:
        cohort_agents = list(canonical_agents)

    cohort_agents_dict = {a["agent_id"]: a for a in cohort_agents}

    # -------------------------------------------------------------------------
    # 2. Customers and Users Generation (RNG using generation seed)
    # -------------------------------------------------------------------------
    rng = random.Random(gen_seed)

    group_shares = sim_cfg["group_shares"]

    # Calculate exact integer group quotas respecting four shares
    raw_quotas = {group: num_customers * share for group, share in group_shares.items()}
    quotas = {group: math.floor(count) for group, count in raw_quotas.items()}
    remainder = num_customers - sum(quotas.values())
    priority = sorted(quotas, key=lambda group: (-(raw_quotas[group] - quotas[group]), group))
    for group in priority[:remainder]:
        quotas[group] += 1
    shuffled_groups = [group for group, count in quotas.items() for _ in range(count)]
    rng.shuffle(shuffled_groups)

    label_noise = sim_cfg["label_noise"]
    aux = sim_cfg["auxiliary_assumptions"]
    amount_rounding = aux["amount_rounding_bdt"]
    loyal_fraction = aux["independent_loyal_fraction"]
    initial_balance_cfg = aux["initial_balance"]
    min_cashout_cfg = Decimal(str(aux["min_cashout"]))

    genders = slice_cats["gender"]
    age_bands = slice_cats["age_band"]
    user_regions = slice_cats["region"]

    users_list: list[dict[str, Any]] = []
    user_metadata: dict[str, dict[str, Any]] = {}

    normal_assisted_propensity = sim_cfg["agent_behavior"]["normal"]["assisted_share"]
    hv_assisted_propensity = sim_cfg["agent_behavior"]["high_volume_honest"]["assisted_share"]
    high_vol_weight = sim_cfg["agent_behavior"]["high_volume_honest"]["customer_weight"]
    skimmer_assisted_propensity = sim_cfg["agent_behavior"]["skimmers"]["assisted_share"]

    for idx in range(num_customers):
        uid = f"U_{gen_seed}_{idx:06d}"
        group_label = shuffled_groups[idx]

        # Flip behavior profile for configured label noise (retain group_label as true label)
        if rng.random() < label_noise:
            behavior_flipped = True
            if group_label == "assisted_allowance":
                effective_profile = "independent_rural"
            elif group_label == "assisted_family":
                effective_profile = "independent_urban"
            elif group_label == "independent_rural":
                effective_profile = "assisted_allowance"
            else:
                effective_profile = "assisted_family"
        else:
            behavior_flipped = False
            effective_profile = group_label

        is_assisted_behavior = effective_profile in ("assisted_allowance", "assisted_family")

        # Independent loyal fraction adopting assisted Beta(6, 2)
        if not is_assisted_behavior:
            is_loyal = rng.random() < loyal_fraction
        else:
            is_loyal = False

        # Evaluation slices only (fairness categories)
        gender = rng.choice(genders)
        age_band = rng.choice(age_bands)
        region = rng.choice(user_regions)
        if group_label == "independent_urban":
            urban_rural = "urban"
        elif group_label == "independent_rural":
            urban_rural = "rural"
        else:
            urban_rural = rng.choice(slice_cats["urban_rural"])

        users_list.append(
            {
                "user_id": uid,
                "group_label": group_label,
                "gender": gender,
                "age_band": age_band,
                "region": region,
                "urban_rural": urban_rural,
                "created_at": start_ts_str,
            }
        )

        # Home Agent Selection: 3x high-volume customer weight, propensity biased
        cohort_weights: list[float] = []
        for a in cohort_agents:
            atype = a["agent_type"]
            if is_assisted_behavior:
                if atype == "high_volume_honest":
                    w = high_vol_weight * hv_assisted_propensity
                elif atype == "skimmer":
                    w = 1.0 * skimmer_assisted_propensity
                else:
                    w = 1.0 * normal_assisted_propensity
            else:
                if atype == "high_volume_honest":
                    w = high_vol_weight * (1.0 - hv_assisted_propensity)
                elif atype == "skimmer":
                    w = 1.0 * (1.0 - skimmer_assisted_propensity)
                else:
                    w = 1.0 * (1.0 - normal_assisted_propensity)
            cohort_weights.append(w)

        if sum(cohort_weights) <= 0:
            raise ConfigError("Agent cohort has no support for this behavior profile")
        home_agent_id = rng.choices(cohort_agents, weights=cohort_weights, k=1)[0]["agent_id"]

        # Top-agent preference from beta distribution directly without clamping
        if is_assisted_behavior or is_loyal:
            beta_alpha = sim_cfg["distributions"]["top_agent_share"]["assisted"]["alpha"]
            beta_beta = sim_cfg["distributions"]["top_agent_share"]["assisted"]["beta"]
        elif effective_profile == "independent_urban":
            beta_alpha = sim_cfg["distributions"]["top_agent_share"]["independent_urban"]["alpha"]
            beta_beta = sim_cfg["distributions"]["top_agent_share"]["independent_urban"]["beta"]
        else:
            beta_alpha = sim_cfg["distributions"]["top_agent_share"]["independent_rural"]["alpha"]
            beta_beta = sim_cfg["distributions"]["top_agent_share"]["independent_rural"]["beta"]

        sampled_top_share = rng.betavariate(beta_alpha, beta_beta)

        user_metadata[uid] = {
            "group_label": group_label,
            "effective_profile": effective_profile,
            "behavior_flipped": behavior_flipped,
            "is_loyal": is_loyal,
            "is_assisted_behavior": is_assisted_behavior,
            "home_agent_id": home_agent_id,
            "sampled_top_agent_share": sampled_top_share,
        }

    # -------------------------------------------------------------------------
    # 3. Simulate Timeline Transactions and Sessions
    # -------------------------------------------------------------------------
    txn_counter = (gen_seed * 100_000_000) + 1
    session_counter = (gen_seed * 100_000_000) + 1

    transactions: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    txn_observations: dict[str, dict[str, Any]] = {}

    allowance_day_cycle = sim_cfg["allowance_day_of_cycle"]
    credits_cfg = sim_cfg["credits"]
    allow_cycle_days = credits_cfg["allowance"]["cycle_days"]
    indep_cycle_days = credits_cfg["independent"]["cycle_days"]

    skimming_intensity = sim_cfg["skimming_intensity"]
    skimmer_profiles = sim_cfg["agent_behavior"]["skimmers"]["intensity_profiles"]
    skimmer_profile = skimmer_profiles[skimming_intensity]

    customer_report_rate = sim_cfg["customer_report_rate"]
    customer_report_accuracy = sim_cfg["customer_report_accuracy"]
    report_noise_sigma = aux["customer_report_noise_sigma_bdt"]
    extra_service_cfg = aux["extra_service"]
    p_cycle = extra_service_cfg["probability_per_cycle"]
    s_min = extra_service_cfg["amount_min"]
    s_max = extra_service_cfg["amount_max"]

    steps_cfg = aux["session_steps"]
    assisted_steps = steps_cfg["assisted"]
    independent_steps = steps_cfg["independent"]

    for u in users_list:
        uid = u["user_id"]
        meta = user_metadata[uid]
        eff_profile = meta["effective_profile"]
        is_asst = meta["is_assisted_behavior"]
        home_aid = meta["home_agent_id"]
        top_share = meta["sampled_top_agent_share"]

        balance = Decimal("0.00")
        events: list[dict[str, Any]] = []

        # A. Initial Balance Credit at t=0 (credit_source is add_money for all profiles)
        if initial_balance_cfg > 0:
            init_amt = Decimal(str(initial_balance_cfg)).quantize(Decimal("0.01"))
            init_dt = start_dt + timedelta(minutes=rng.randint(*aux["opening_delay_minutes"]))
            events.append(
                {
                    "type": "credit",
                    "ts": init_dt,
                    "amount": init_amt,
                    "credit_source": "add_money",
                    "channel": "app" if eff_profile == "independent_urban" else "ussd",
                }
            )

        # B. Scheduled Periodic / Irregular Credits (including final partial cycle)
        if eff_profile == "assisted_allowance":
            allow_cfg = credits_cfg["allowance"]
            c_min = allow_cfg["amount_min"]
            c_max = allow_cfg["amount_max"]
            step_min = math.ceil(c_min / amount_rounding)
            step_max = math.floor(c_max / amount_rounding)
            num_allow_cycles = math.ceil(days / allow_cycle_days)
            for cycle_idx in range(num_allow_cycles):
                d_offset = (cycle_idx * allow_cycle_days) + allowance_day_cycle
                if d_offset < days:
                    c_dt = start_dt + timedelta(
                        days=d_offset,
                        hours=rng.randint(*aux["credit_hours"]["allowance"]),
                        minutes=rng.randint(0, 59),
                    )
                    c_amt = Decimal(
                        str(rng.randint(step_min, step_max) * amount_rounding)
                    ).quantize(Decimal("0.01"))
                    events.append(
                        {
                            "type": "credit",
                            "ts": c_dt,
                            "amount": c_amt,
                            "credit_source": "allowance",
                            "channel": "ussd",
                        }
                    )

        elif eff_profile == "assisted_family":
            fam_cfg = credits_cfg["family"]
            daily_prob = fam_cfg["daily_probability"]
            c_min = fam_cfg["amount_min"]
            c_max = fam_cfg["amount_max"]
            step_min = math.ceil(c_min / amount_rounding)
            step_max = math.floor(c_max / amount_rounding)
            for day_idx in range(days):
                if rng.random() < daily_prob:
                    c_dt = start_dt + timedelta(
                        days=day_idx,
                        hours=rng.randint(*aux["credit_hours"]["family"]),
                        minutes=rng.randint(0, 59),
                    )
                    c_amt = Decimal(
                        str(rng.randint(step_min, step_max) * amount_rounding)
                    ).quantize(Decimal("0.01"))
                    events.append(
                        {
                            "type": "credit",
                            "ts": c_dt,
                            "amount": c_amt,
                            "credit_source": "remittance",
                            "channel": "ussd",
                        }
                    )

        else:
            indep_cfg = credits_cfg["independent"]
            c_min = indep_cfg["amount_min"]
            c_max = indep_cfg["amount_max"]
            step_min = math.ceil(c_min / amount_rounding)
            step_max = math.floor(c_max / amount_rounding)
            num_indep_cycles = math.ceil(days / indep_cycle_days)
            for cycle_idx in range(1, num_indep_cycles):
                d_offset = cycle_idx * indep_cycle_days
                if d_offset < days:
                    c_dt = start_dt + timedelta(
                        days=d_offset,
                        hours=rng.randint(*aux["credit_hours"]["independent"]),
                        minutes=rng.randint(0, 59),
                    )
                    c_amt = Decimal(
                        str(rng.randint(step_min, step_max) * amount_rounding)
                    ).quantize(Decimal("0.01"))
                    events.append(
                        {
                            "type": "credit",
                            "ts": c_dt,
                            "amount": c_amt,
                            "credit_source": rng.choice(["salary", "add_money"]),
                            "channel": "app" if eff_profile == "independent_urban" else "ussd",
                        }
                    )

        # C. Cashout Delays Scheduled After Credits
        mean_delay = (
            sim_cfg["distributions"]["credit_to_cashout_delay_hours"]["assisted"]["mean"]
            if is_asst
            else sim_cfg["distributions"]["credit_to_cashout_delay_hours"]["independent"]["mean"]
        )

        w_alpha = (
            sim_cfg["distributions"]["withdrawn_fraction"]["assisted"]["alpha"]
            if is_asst
            else sim_cfg["distributions"]["withdrawn_fraction"]["independent"]["alpha"]
        )
        w_beta = (
            sim_cfg["distributions"]["withdrawn_fraction"]["assisted"]["beta"]
            if is_asst
            else sim_cfg["distributions"]["withdrawn_fraction"]["independent"]["beta"]
        )

        for credit_ev in list(events):
            c_ts = credit_ev["ts"]
            delay_hrs = rng.expovariate(1.0 / mean_delay)
            co_ts = c_ts + timedelta(hours=delay_hrs)
            if co_ts < max_dt:
                events.append(
                    {
                        "type": "cash_out_intent",
                        "ts": co_ts,
                        "w_alpha": w_alpha,
                        "w_beta": w_beta,
                    }
                )

        # D. Extra Services: actual total_services draw drives extra-service intents per cycle
        srv_lambda = (
            sim_cfg["distributions"]["service_count"]["assisted"]["lambda"]
            if is_asst
            else sim_cfg["distributions"]["service_count"]["independent"]["lambda"]
        )
        srv_base = (
            sim_cfg["distributions"]["service_count"]["assisted"]["base"]
            if is_asst
            else sim_cfg["distributions"]["service_count"]["independent"]["base"]
        )
        total_services = srv_base + sample_poisson(rng, srv_lambda)

        if total_services > 0:
            es_step_min = math.ceil(s_min / amount_rounding)
            es_step_max = math.floor(s_max / amount_rounding)
            num_extra_cycles = math.ceil(days / allow_cycle_days)
            for cycle_idx in range(num_extra_cycles):
                if rng.random() < p_cycle:
                    for _ in range(total_services):
                        s_day = (cycle_idx * allow_cycle_days) + rng.randint(
                            min(aux["extra_service_day_range"][0], allow_cycle_days - 1),
                            min(aux["extra_service_day_range"][1], allow_cycle_days - 1),
                        )
                        if s_day < days:
                            s_dt = start_dt + timedelta(
                                days=s_day,
                                hours=rng.randint(*aux["extra_service_hours"]),
                                minutes=rng.randint(0, 59),
                            )
                            s_amt = Decimal(
                                str(rng.randint(es_step_min, es_step_max) * amount_rounding)
                            ).quantize(Decimal("0.01"))
                            events.append(
                                {
                                    "type": "extra_service",
                                    "service_type": rng.choice(["send", "bill_pay"]),
                                    "ts": s_dt,
                                    "amount": s_amt,
                                }
                            )

        # E. Process chronological ledger events for this user
        events.sort(key=lambda ev: ev["ts"])

        for ev in events:
            ev_type = ev["type"]
            ev_ts = ev["ts"]

            if ev_type == "credit":
                c_amt = ev["amount"]
                balance += c_amt
                tid = txn_counter
                txn_counter += 1
                sid = session_counter
                session_counter += 1

                ts_iso = ev_ts.isoformat()
                transactions.append(
                    {
                        "txn_id": tid,
                        "user_id": uid,
                        "agent_id": None,
                        "txn_type": "credit",
                        "credit_source": ev["credit_source"],
                        "amount": _quantize_float(c_amt),
                        "fee": 0.0,
                        "balance_after": _quantize_float(balance),
                        "channel": ev["channel"],
                        "ts": ts_iso,
                    }
                )

                pin_lambda = (
                    sim_cfg["distributions"]["pin_retries"]["assisted"]["lambda"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_retries"]["independent"]["lambda"]
                )
                pin_retries = sample_poisson(rng, pin_lambda)

                pin_med = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["median"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["median"]
                )
                pin_sig = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["sigma"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["sigma"]
                )
                pin_sec = rng.lognormvariate(math.log(pin_med), pin_sig)
                pin_ms = max(0, int(round(pin_sec * 1000)))
                steps = assisted_steps if is_asst else independent_steps

                sessions.append(
                    {
                        "session_id": sid,
                        "user_id": uid,
                        "txn_id": tid,
                        "pin_retries": pin_retries,
                        "pin_entry_ms": pin_ms,
                        "steps": steps,
                        "ts": ts_iso,
                    }
                )

            elif ev_type == "cash_out_intent":
                if balance < min_cashout_cfg:
                    continue

                fraction = Decimal(str(round(rng.betavariate(ev["w_alpha"], ev["w_beta"]), 4)))
                raw_amt = balance * fraction
                target_amt = Decimal(str(int(raw_amt // amount_rounding) * amount_rounding))
                if target_amt < min_cashout_cfg:
                    target_amt = min_cashout_cfg
                target_amt = min(target_amt, balance)

                # Agent selection
                if rng.random() < top_share:
                    chosen_aid = home_aid
                else:
                    non_homes = [a["agent_id"] for a in cohort_agents if a["agent_id"] != home_aid]
                    chosen_aid = rng.choice(non_homes) if non_homes else home_aid

                chosen_agent = cohort_agents_dict[chosen_aid]
                chosen_atype = chosen_agent["agent_type"]

                # Cycle allowance day from timeline start offset (not calendar monthday)
                day_offset = (ev_ts - start_dt).days
                is_allowance_day = (day_offset % allow_cycle_days) == allowance_day_cycle

                # High-volume honest allowance-day volume multiplier (one single transaction)
                if chosen_atype == "high_volume_honest" and is_allowance_day:
                    hv_mult = Decimal(
                        str(
                            sim_cfg["agent_behavior"]["high_volume_honest"][
                                "allowance_day_volume_multiplier"
                            ]
                        )
                    )
                    target_amt = (target_amt * hv_mult).quantize(Decimal("0.01"))

                official_fee = (target_amt * official_fee_rate).quantize(Decimal("0.01"))
                fee_multiplier_applied = False
                payout_reduction_applied = False
                mult_val = Decimal("1.0")
                pct_reduction = Decimal("0.0")

                if chosen_atype == "skimmer":
                    if rng.random() < skimmer_profile["fee_multiplier_probability"]:
                        fee_multiplier_applied = True
                        mult_val = Decimal(str(skimmer_profile["fee_multiplier"]))
                        fee = (official_fee * mult_val).quantize(Decimal("0.01"))
                    else:
                        fee = official_fee

                    if rng.random() < skimmer_profile["payout_reduction_probability"]:
                        payout_reduction_applied = True
                        low_r, high_r = skimmer_profile["payout_reduction_range"]
                        pct_reduction = Decimal(str(round(rng.uniform(low_r, high_r), 4)))
                        reduction_amt = (target_amt * pct_reduction).quantize(Decimal("0.01"))
                        actual_cash = target_amt - reduction_amt
                    else:
                        actual_cash = target_amt
                else:
                    fee = official_fee
                    actual_cash = target_amt

                # Affordability constraint (co_amt + fee <= balance) using cents floor
                if target_amt + fee > balance:
                    effective_rate = Decimal("1.0") + (official_fee_rate * mult_val)
                    max_affordable = (balance / effective_rate).quantize(
                        Decimal("0.01"), rounding=ROUND_FLOOR
                    )
                    co_amt = max_affordable
                    official_fee = (co_amt * official_fee_rate).quantize(Decimal("0.01"))
                    fee = (official_fee * mult_val).quantize(Decimal("0.01"))
                    while (co_amt + fee) > balance and co_amt > Decimal("0.00"):
                        co_amt -= Decimal("0.01")
                        official_fee = (co_amt * official_fee_rate).quantize(Decimal("0.01"))
                        fee = (official_fee * mult_val).quantize(Decimal("0.01"))

                    if co_amt < min_cashout_cfg:
                        continue

                    if payout_reduction_applied:
                        reduction_amt = (co_amt * pct_reduction).quantize(Decimal("0.01"))
                        actual_cash = co_amt - reduction_amt
                    else:
                        actual_cash = co_amt
                else:
                    co_amt = target_amt

                balance -= co_amt + fee

                tid = txn_counter
                txn_counter += 1
                sid = session_counter
                session_counter += 1

                # Customer cash received report confirmation
                if rng.random() < customer_report_rate:
                    if rng.random() < customer_report_accuracy:
                        reported_cash = actual_cash
                    else:
                        noise = Decimal(str(round(rng.gauss(0, report_noise_sigma), 2)))
                        noisy_val = (actual_cash + noise).quantize(Decimal("0.01"))
                        reported_cash = max(Decimal("0.00"), noisy_val)
                else:
                    reported_cash = None

                ts_iso = ev_ts.isoformat()
                transactions.append(
                    {
                        "txn_id": tid,
                        "user_id": uid,
                        "agent_id": chosen_aid,
                        "txn_type": "cash_out",
                        "credit_source": None,
                        "amount": _quantize_float(co_amt),
                        "fee": _quantize_float(fee),
                        "balance_after": _quantize_float(balance),
                        "channel": "agent_initiated" if is_asst else "ussd",
                        "ts": ts_iso,
                    }
                )

                pin_lambda = (
                    sim_cfg["distributions"]["pin_retries"]["assisted"]["lambda"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_retries"]["independent"]["lambda"]
                )
                pin_retries = sample_poisson(rng, pin_lambda)

                pin_med = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["median"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["median"]
                )
                pin_sig = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["sigma"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["sigma"]
                )
                pin_sec = rng.lognormvariate(math.log(pin_med), pin_sig)
                pin_ms = max(0, int(round(pin_sec * 1000)))
                steps = assisted_steps if is_asst else independent_steps

                sessions.append(
                    {
                        "session_id": sid,
                        "user_id": uid,
                        "txn_id": tid,
                        "pin_retries": pin_retries,
                        "pin_entry_ms": pin_ms,
                        "steps": steps,
                        "ts": ts_iso,
                    }
                )

                rep_cash_val = _quantize_float(reported_cash) if reported_cash is not None else None
                txn_observations[str(tid)] = {
                    "txn_id": tid,
                    "user_id": uid,
                    "agent_id": chosen_aid,
                    "agent_type": chosen_atype,
                    "actual_cash_received": _quantize_float(actual_cash),
                    "cash_received_reported": rep_cash_val,
                    "fee_overcharge": _quantize_float(fee - official_fee),
                    "payout_reduction": _quantize_float(co_amt - actual_cash),
                    "is_skimmer_action": (fee_multiplier_applied or payout_reduction_applied),
                }

            elif ev_type == "extra_service":
                amt = ev["amount"]
                # Strict balance affordability check without hardcoded extra buffer
                if balance < amt:
                    continue

                balance -= amt
                tid = txn_counter
                txn_counter += 1
                sid = session_counter
                session_counter += 1

                ts_iso = ev_ts.isoformat()
                transactions.append(
                    {
                        "txn_id": tid,
                        "user_id": uid,
                        "agent_id": home_aid if is_asst else None,
                        "txn_type": ev["service_type"],
                        "credit_source": None,
                        "amount": _quantize_float(amt),
                        "fee": 0.0,
                        "balance_after": _quantize_float(balance),
                        "channel": "agent_initiated" if is_asst else "app",
                        "ts": ts_iso,
                    }
                )

                pin_lambda = (
                    sim_cfg["distributions"]["pin_retries"]["assisted"]["lambda"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_retries"]["independent"]["lambda"]
                )
                pin_retries = sample_poisson(rng, pin_lambda)

                pin_med = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["median"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["median"]
                )
                pin_sig = (
                    sim_cfg["distributions"]["pin_entry_seconds"]["assisted"]["sigma"]
                    if is_asst
                    else sim_cfg["distributions"]["pin_entry_seconds"]["independent"]["sigma"]
                )
                pin_sec = rng.lognormvariate(math.log(pin_med), pin_sig)
                pin_ms = max(0, int(round(pin_sec * 1000)))
                steps = assisted_steps if is_asst else independent_steps

                sessions.append(
                    {
                        "session_id": sid,
                        "user_id": uid,
                        "txn_id": tid,
                        "pin_retries": pin_retries,
                        "pin_entry_ms": pin_ms,
                        "steps": steps,
                        "ts": ts_iso,
                    }
                )

    # -------------------------------------------------------------------------
    # 4. Final Ordering and Sidecar Packaging
    # -------------------------------------------------------------------------
    transactions.sort(key=lambda t: (t["ts"], t["txn_id"]))
    sessions.sort(key=lambda s: (s["ts"], s["session_id"]))
    users_list.sort(key=lambda u: u["user_id"])
    cohort_agents.sort(key=lambda a: a["agent_id"])

    main_dataset: dict[str, Any] = {
        "schema_version": 1,
        "synthetic": True,
        "seed": gen_seed,
        "users": users_list,
        "agents": cohort_agents,
        "transactions": transactions,
        "sessions": sessions,
    }

    # Summary fractions for generator documentation (no score tuning)
    realized_assisted_users = sum(1 for m in user_metadata.values() if m["is_assisted_behavior"])
    realized_assisted_share = realized_assisted_users / len(user_metadata) if user_metadata else 0.0

    reported_count = sum(
        1 for o in txn_observations.values() if o["cash_received_reported"] is not None
    )
    total_cashouts = len(txn_observations)
    realized_report_rate = reported_count / total_cashouts if total_cashouts else 0.0

    accurate_count = sum(
        1
        for o in txn_observations.values()
        if o["cash_received_reported"] is not None
        and o["cash_received_reported"] == o["actual_cash_received"]
    )
    realized_accuracy = accurate_count / reported_count if reported_count else 0.0

    agent_txns: dict[str, list[dict[str, Any]]] = {}
    for t in transactions:
        aid = t.get("agent_id")
        if aid:
            agent_txns.setdefault(aid, []).append(t)

    agent_type_assisted_counts: dict[str, list[float]] = {
        "normal": [],
        "high_volume_honest": [],
        "skimmer": [],
    }
    for aid, a_txns in agent_txns.items():
        atype = canonical_agents_dict[aid]["agent_type"]
        asst_cnt = sum(1 for t in a_txns if user_metadata[t["user_id"]]["is_assisted_behavior"])
        frac = asst_cnt / len(a_txns) if a_txns else 0.0
        if atype in agent_type_assisted_counts:
            agent_type_assisted_counts[atype].append(frac)

    realized_agent_assisted_fractions = {}
    for atype, fracs in agent_type_assisted_counts.items():
        realized_agent_assisted_fractions[atype] = (
            round(sum(fracs) / len(fracs), 4) if fracs else 0.0
        )

    sidecar_observations: dict[str, Any] = {
        "schema_version": 1,
        "synthetic": True,
        "seed": gen_seed,
        "user_observations": user_metadata,
        "transaction_observations": txn_observations,
        "summary": {
            "realized_assisted_share": round(realized_assisted_share, 4),
            "realized_report_rate": round(realized_report_rate, 4),
            "realized_report_accuracy": round(realized_accuracy, 4),
            "realized_agent_assisted_transaction_fractions": realized_agent_assisted_fractions,
            "total_users": len(users_list),
            "total_agents": len(cohort_agents),
            "total_transactions": len(transactions),
            "total_sessions": len(sessions),
        },
    }

    if txn_counter > (gen_seed + 1) * 100_000_000:
        raise ConfigError("Dataset exceeds the numeric ID namespace capacity")
    validate_dataset(main_dataset)
    result = DatasetResult(main_dataset, sidecar_observations)
    if return_observations:
        return result, sidecar_observations
    return result


def generate_dataset_with_observations(
    config: dict[str, Any] | None = None,
    seed: int | None = None,
    agent_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    customers: int | None = None,
    canonical_agents: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience function returning (main_dataset, sidecar_observations)."""
    return generate_dataset(
        config=config,
        seed=seed,
        agent_ids=agent_ids,
        customers=customers,
        return_observations=True,
        canonical_agents=canonical_agents,
    )
