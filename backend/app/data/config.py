"""Configuration loader and schema validator for Sathi synthetic simulation."""

import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when configuration values are missing, invalid, or inconsistent."""


def find_config_path(explicit_path: str | Path | None = None) -> Path:
    """Resolve config file path from explicit argument, env, or known repo locations."""
    if explicit_path:
        p = Path(explicit_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Specified config file not found: {explicit_path}")

    # Primary env interface is SATHI_CONFIG; SATHI_CONFIG_PATH supported as legacy fallback
    env_path = os.environ.get("SATHI_CONFIG") or os.environ.get("SATHI_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Config path specified in environment not found: {env_path}")

    candidates = [
        Path.cwd() / "data" / "config.yaml",
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "config.yaml",
        Path.cwd() / "config.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = [str(c) for c in candidates]
    raise FileNotFoundError(f"data/config.yaml not found. Searched locations: {searched}")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate configuration from YAML file."""
    config_path = find_config_path(path)
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(data).__name__}")
    return validate_config(data)


def _check_finite_num(
    val: Any,
    name: str,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    exclusive_min: bool = False,
    exclusive_max: bool = False,
) -> float:
    """Check that value is a finite number and strictly not a boolean."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ConfigError(f"{name} must be a number, got {val!r} ({type(val).__name__})")
    if not math.isfinite(val):
        raise ConfigError(f"{name} must be a finite number, got {val!r}")
    f_val = float(val)
    if min_val is not None:
        if exclusive_min and f_val <= min_val:
            raise ConfigError(f"{name} must be > {min_val}, got {val!r}")
        if not exclusive_min and f_val < min_val:
            raise ConfigError(f"{name} must be >= {min_val}, got {val!r}")
    if max_val is not None:
        if exclusive_max and f_val >= max_val:
            raise ConfigError(f"{name} must be < {max_val}, got {val!r}")
        if not exclusive_max and f_val > max_val:
            raise ConfigError(f"{name} must be <= {max_val}, got {val!r}")
    return f_val


def _check_int(
    val: Any,
    name: str,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    """Check that value is strictly an integer and not a boolean."""
    if type(val) is not int or isinstance(val, bool):
        raise ConfigError(f"{name} must be an integer, got {val!r} ({type(val).__name__})")
    if min_val is not None and val < min_val:
        raise ConfigError(f"{name} must be >= {min_val}, got {val!r}")
    if max_val is not None and val > max_val:
        raise ConfigError(f"{name} must be <= {max_val}, got {val!r}")
    return val


def _check_prob(val: Any, name: str) -> float:
    """Check that value is a valid probability in [0.0, 1.0]."""
    return _check_finite_num(val, name, min_val=0.0, max_val=1.0)


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate full configuration structure, shares, probabilities, and distributions.

    Ensures shares sum to 1.0, agent mix sums to agent count, timestamps include tz,
    and all parameters conform to approved ranges.
    """
    if "simulation" not in config or not isinstance(config["simulation"], dict):
        raise ConfigError("Missing required 'simulation' mapping in configuration.")

    sim = config["simulation"]

    # 1. start_timestamp
    start_ts = sim.get("start_timestamp")
    if not isinstance(start_ts, str):
        raise ConfigError("simulation.start_timestamp must be an ISO 8601 string.")
    try:
        dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ConfigError("simulation.start_timestamp must include timezone offset.")
    except Exception as exc:
        raise ConfigError(f"Invalid simulation.start_timestamp '{start_ts}': {exc}") from exc

    # 2. Seeds (must be distinct 31-bit non-negative integers)
    seed_keys = ("seed_train", "seed_validation", "seed_test")
    seed_vals = []
    for seed_key in seed_keys:
        s_val = sim.get(seed_key)
        val = _check_int(s_val, f"simulation.{seed_key}", min_val=0, max_val=2**31 - 1)
        seed_vals.append(val)
    if len(set(seed_vals)) != len(seed_keys):
        raise ConfigError(f"simulation seeds {seed_keys} must all be distinct, got {seed_vals}")

    # 3. agent_split
    agent_split = sim.get("agent_split")
    required_split_keys = {"train", "validation", "test"}
    if not isinstance(agent_split, dict) or set(agent_split.keys()) != required_split_keys:
        raise ConfigError(
            f"simulation.agent_split must define exact keys: {sorted(required_split_keys)}"
        )
    for sp_key, sp_val in agent_split.items():
        _check_prob(sp_val, f"simulation.agent_split['{sp_key}']")
    total_split = sum(agent_split.values())
    if abs(total_split - 1.0) > 1e-6:
        raise ConfigError(f"simulation.agent_split must sum to 1.0, got {total_split:.6f}")

    # 4. Population & window counts
    _check_int(sim.get("customers"), "simulation.customers", min_val=1)
    agents = _check_int(sim.get("agents"), "simulation.agents", min_val=1)
    _check_int(sim.get("days"), "simulation.days", min_val=1)

    # 5. Group shares
    group_shares = sim.get("group_shares")
    required_groups = {
        "independent_urban",
        "independent_rural",
        "assisted_allowance",
        "assisted_family",
    }
    if not isinstance(group_shares, dict) or set(group_shares.keys()) != required_groups:
        raise ConfigError(
            f"simulation.group_shares must define exact groups: {sorted(required_groups)}"
        )
    for grp, share in group_shares.items():
        _check_prob(share, f"simulation.group_shares['{grp}']")
    total_group_share = sum(group_shares.values())
    if abs(total_group_share - 1.0) > 1e-6:
        raise ConfigError(f"simulation.group_shares must sum to 1.0, got {total_group_share:.6f}")

    # 6. Allowance day & label noise
    _check_int(sim.get("allowance_day_of_cycle"), "simulation.allowance_day_of_cycle", min_val=0)
    _check_prob(sim.get("label_noise"), "simulation.label_noise")

    # 7. Agent mix
    agent_mix = sim.get("agent_mix")
    required_agent_types = {"normal", "high_volume_honest", "skimmers"}
    if not isinstance(agent_mix, dict) or set(agent_mix.keys()) != required_agent_types:
        raise ConfigError(f"simulation.agent_mix must define: {sorted(required_agent_types)}")
    for atype, count in agent_mix.items():
        _check_int(count, f"simulation.agent_mix['{atype}']", min_val=0)
    mix_sum = sum(agent_mix.values())
    if mix_sum != agents:
        raise ConfigError(
            f"simulation.agent_mix sum ({mix_sum}) must equal agents count ({agents})"
        )

    # 8. Skimming intensity & fee rate
    valid_intensities = {"subtle", "moderate", "obvious"}
    intensity = sim.get("skimming_intensity")
    if intensity not in valid_intensities:
        raise ConfigError(
            f"simulation.skimming_intensity must be in {sorted(valid_intensities)}; "
            f"got {intensity!r}"
        )

    _check_finite_num(
        sim.get("official_fee_rate"),
        "simulation.official_fee_rate",
        min_val=0.0,
        max_val=1.0,
        exclusive_min=True,
    )

    # 9. Report rate and accuracy
    _check_prob(sim.get("customer_report_rate"), "simulation.customer_report_rate")
    _check_prob(sim.get("customer_report_accuracy"), "simulation.customer_report_accuracy")

    # 10. Distributions
    dists = sim.get("distributions")
    if not isinstance(dists, dict):
        raise ConfigError("Missing simulation.distributions mapping.")

    # top_agent_share: beta (alpha > 0, beta > 0)
    tas = dists.get("top_agent_share")
    if not isinstance(tas, dict):
        raise ConfigError("Missing distributions.top_agent_share mapping.")
    for grp in ("independent_urban", "independent_rural", "assisted"):
        spec = tas.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "beta":
            raise ConfigError(f"distributions.top_agent_share['{grp}'] must specify dist: beta")
        _check_finite_num(
            spec.get("alpha"), f"top_agent_share.{grp}.alpha", min_val=0.0, exclusive_min=True
        )
        _check_finite_num(
            spec.get("beta"), f"top_agent_share.{grp}.beta", min_val=0.0, exclusive_min=True
        )

    # credit_to_cashout_delay_hours: exponential (mean > 0)
    ccd = dists.get("credit_to_cashout_delay_hours")
    if not isinstance(ccd, dict):
        raise ConfigError("Missing distributions.credit_to_cashout_delay_hours mapping.")
    for grp in ("independent", "assisted"):
        spec = ccd.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "exponential":
            raise ConfigError(
                f"credit_to_cashout_delay_hours[{grp}] must specify dist: exponential"
            )
        _check_finite_num(
            spec.get("mean"),
            f"credit_to_cashout_delay_hours.{grp}.mean",
            min_val=0.0,
            exclusive_min=True,
        )

    # withdrawn_fraction: beta (alpha > 0, beta > 0)
    wf = dists.get("withdrawn_fraction")
    if not isinstance(wf, dict):
        raise ConfigError("Missing distributions.withdrawn_fraction mapping.")
    for grp in ("independent", "assisted"):
        spec = wf.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "beta":
            raise ConfigError(f"distributions.withdrawn_fraction['{grp}'] must specify dist: beta")
        _check_finite_num(
            spec.get("alpha"), f"withdrawn_fraction.{grp}.alpha", min_val=0.0, exclusive_min=True
        )
        _check_finite_num(
            spec.get("beta"), f"withdrawn_fraction.{grp}.beta", min_val=0.0, exclusive_min=True
        )

    # pin_retries: poisson (lambda >= 0)
    pr = dists.get("pin_retries")
    if not isinstance(pr, dict):
        raise ConfigError("Missing distributions.pin_retries mapping.")
    for grp in ("independent", "assisted"):
        spec = pr.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "poisson":
            raise ConfigError(f"distributions.pin_retries['{grp}'] must specify dist: poisson")
        _check_finite_num(spec.get("lambda"), f"pin_retries.{grp}.lambda", min_val=0.0)

    # pin_entry_seconds: lognormal (median > 0, sigma >= 0)
    pes = dists.get("pin_entry_seconds")
    if not isinstance(pes, dict):
        raise ConfigError("Missing distributions.pin_entry_seconds mapping.")
    for grp in ("independent", "assisted"):
        spec = pes.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "lognormal":
            raise ConfigError(
                f"distributions.pin_entry_seconds['{grp}'] must specify dist: lognormal"
            )
        _check_finite_num(
            spec.get("median"),
            f"pin_entry_seconds.{grp}.median",
            min_val=0.0,
            exclusive_min=True,
        )
        _check_finite_num(spec.get("sigma"), f"pin_entry_seconds.{grp}.sigma", min_val=0.0)

    # service_count: poisson (lambda >= 0, base >= 0)
    sc = dists.get("service_count")
    if not isinstance(sc, dict):
        raise ConfigError("Missing distributions.service_count mapping.")
    for grp in ("independent", "assisted"):
        spec = sc.get(grp)
        if not isinstance(spec, dict) or spec.get("dist") != "poisson":
            raise ConfigError(f"distributions.service_count['{grp}'] must specify dist: poisson")
        _check_finite_num(spec.get("lambda"), f"service_count.{grp}.lambda", min_val=0.0)
        _check_int(spec.get("base", 0), f"service_count.{grp}.base", min_val=0)

    # 11. Credits
    credits = sim.get("credits")
    if not isinstance(credits, dict):
        raise ConfigError("Missing simulation.credits mapping.")

    # allowance: cycle_days positive int, amount_min <= amount_max, disbursement_day rejected
    allow_cfg = credits.get("allowance")
    if not isinstance(allow_cfg, dict):
        raise ConfigError("Missing credits.allowance mapping.")
    if "disbursement_day" in allow_cfg:
        raise ConfigError(
            "credits.allowance.disbursement_day is deprecated; "
            "simulation.allowance_day_of_cycle is the single source."
        )
    _check_int(allow_cfg.get("cycle_days"), "credits.allowance.cycle_days", min_val=1)
    a_min = _check_finite_num(
        allow_cfg.get("amount_min"),
        "credits.allowance.amount_min",
        min_val=0.0,
        exclusive_min=True,
    )
    a_max = _check_finite_num(
        allow_cfg.get("amount_max"),
        "credits.allowance.amount_max",
        min_val=0.0,
        exclusive_min=True,
    )
    if a_min > a_max:
        raise ConfigError(
            f"credits.allowance.amount_min ({a_min}) cannot exceed amount_max ({a_max})"
        )

    # family: daily_probability in [0,1], amount_min <= amount_max
    fam_cfg = credits.get("family")
    if not isinstance(fam_cfg, dict):
        raise ConfigError("Missing credits.family mapping.")
    _check_prob(fam_cfg.get("daily_probability"), "credits.family.daily_probability")
    f_min = _check_finite_num(
        fam_cfg.get("amount_min"), "credits.family.amount_min", min_val=0.0, exclusive_min=True
    )
    f_max = _check_finite_num(
        fam_cfg.get("amount_max"), "credits.family.amount_max", min_val=0.0, exclusive_min=True
    )
    if f_min > f_max:
        raise ConfigError(f"credits.family.amount_min ({f_min}) cannot exceed amount_max ({f_max})")

    # independent: cycle_days positive int, amount_min <= amount_max
    ind_cfg = credits.get("independent")
    if not isinstance(ind_cfg, dict):
        raise ConfigError("Missing credits.independent mapping.")
    _check_int(ind_cfg.get("cycle_days"), "credits.independent.cycle_days", min_val=1)
    i_min = _check_finite_num(
        ind_cfg.get("amount_min"),
        "credits.independent.amount_min",
        min_val=0.0,
        exclusive_min=True,
    )
    i_max = _check_finite_num(
        ind_cfg.get("amount_max"),
        "credits.independent.amount_max",
        min_val=0.0,
        exclusive_min=True,
    )
    if i_min > i_max:
        raise ConfigError(
            f"credits.independent.amount_min ({i_min}) cannot exceed amount_max ({i_max})"
        )

    # 12. Agent behavior
    agent_behav = sim.get("agent_behavior")
    if not isinstance(agent_behav, dict):
        raise ConfigError("Missing simulation.agent_behavior mapping.")
    for req_agent in ("normal", "high_volume_honest", "skimmers"):
        if req_agent not in agent_behav or not isinstance(agent_behav[req_agent], dict):
            raise ConfigError(f"simulation.agent_behavior missing '{req_agent}' profile")

    # normal
    norm_cfg = agent_behav["normal"]
    _check_prob(norm_cfg.get("assisted_share"), "agent_behavior.normal.assisted_share")
    _check_finite_num(
        norm_cfg.get("fee_multiplier"), "agent_behavior.normal.fee_multiplier", min_val=1.0
    )
    _check_prob(norm_cfg.get("payout_reduction"), "agent_behavior.normal.payout_reduction")

    # high_volume_honest
    hv_cfg = agent_behav["high_volume_honest"]
    _check_finite_num(
        hv_cfg.get("customer_weight"),
        "agent_behavior.high_volume_honest.customer_weight",
        min_val=0.0,
        exclusive_min=True,
    )
    _check_finite_num(
        hv_cfg.get("allowance_day_volume_multiplier"),
        "agent_behavior.high_volume_honest.allowance_day_volume_multiplier",
        min_val=1.0,
    )
    _check_prob(hv_cfg.get("assisted_share"), "agent_behavior.high_volume_honest.assisted_share")
    _check_finite_num(
        hv_cfg.get("fee_multiplier"),
        "agent_behavior.high_volume_honest.fee_multiplier",
        min_val=1.0,
    )
    _check_prob(
        hv_cfg.get("payout_reduction"), "agent_behavior.high_volume_honest.payout_reduction"
    )

    # skimmers
    skim_cfg = agent_behav["skimmers"]
    _check_prob(skim_cfg.get("assisted_share"), "agent_behavior.skimmers.assisted_share")
    intensity_profs = skim_cfg.get("intensity_profiles")
    if not isinstance(intensity_profs, dict):
        raise ConfigError("Missing agent_behavior.skimmers.intensity_profiles mapping.")
    for p_name in ("subtle", "moderate", "obvious"):
        if p_name not in intensity_profs or not isinstance(intensity_profs[p_name], dict):
            raise ConfigError(f"intensity_profiles missing '{p_name}' mapping")
        p_data = intensity_profs[p_name]
        _check_finite_num(
            p_data.get("fee_multiplier"),
            f"intensity_profiles.{p_name}.fee_multiplier",
            min_val=1.0,
        )
        _check_prob(
            p_data.get("fee_multiplier_probability"),
            f"intensity_profiles.{p_name}.fee_multiplier_probability",
        )
        _check_prob(
            p_data.get("payout_reduction_probability"),
            f"intensity_profiles.{p_name}.payout_reduction_probability",
        )
        p_range = p_data.get("payout_reduction_range")
        if not isinstance(p_range, (list, tuple)) or len(p_range) != 2:
            raise ConfigError(
                f"intensity_profiles.{p_name}.payout_reduction_range must be list of [low, high]"
            )
        p_low = _check_prob(p_range[0], f"intensity_profiles.{p_name}.payout_reduction_range[0]")
        p_high = _check_prob(p_range[1], f"intensity_profiles.{p_name}.payout_reduction_range[1]")
        if p_low > p_high:
            raise ConfigError(f"intensity_profiles.{p_name}.payout_reduction_range low > high")

    # 13. Auxiliary assumptions
    aux = sim.get("auxiliary_assumptions")
    if not isinstance(aux, dict):
        raise ConfigError("Missing simulation.auxiliary_assumptions mapping.")
    _check_finite_num(
        aux.get("initial_balance"), "auxiliary_assumptions.initial_balance", min_val=0.0
    )
    _check_finite_num(
        aux.get("min_cashout"), "auxiliary_assumptions.min_cashout", min_val=0.0, exclusive_min=True
    )
    _check_int(
        aux.get("amount_rounding_bdt"), "auxiliary_assumptions.amount_rounding_bdt", min_val=1
    )
    _check_prob(
        aux.get("independent_loyal_fraction"),
        "auxiliary_assumptions.independent_loyal_fraction",
    )
    _check_finite_num(
        aux.get("customer_report_noise_sigma_bdt"),
        "auxiliary_assumptions.customer_report_noise_sigma_bdt",
        min_val=0.0,
    )

    extra_srv = aux.get("extra_service")
    if not isinstance(extra_srv, dict):
        raise ConfigError("Missing auxiliary_assumptions.extra_service mapping.")
    _check_prob(extra_srv.get("probability_per_cycle"), "extra_service.probability_per_cycle")
    es_min = _check_finite_num(
        extra_srv.get("amount_min"), "extra_service.amount_min", min_val=0.0, exclusive_min=True
    )
    es_max = _check_finite_num(
        extra_srv.get("amount_max"), "extra_service.amount_max", min_val=0.0, exclusive_min=True
    )
    if es_min > es_max:
        raise ConfigError(
            f"extra_service.amount_min ({es_min}) cannot exceed amount_max ({es_max})"
        )

    s_steps = aux.get("session_steps")
    if not isinstance(s_steps, dict):
        raise ConfigError("Missing auxiliary_assumptions.session_steps mapping.")
    _check_int(s_steps.get("independent"), "session_steps.independent", min_val=1)
    _check_int(s_steps.get("assisted"), "session_steps.assisted", min_val=1)

    # 14. Policy
    policy = config.get("policy")
    if not isinstance(policy, dict):
        raise ConfigError("Missing required 'policy' mapping in configuration.")
    _check_finite_num(
        policy.get("mandate_ttl_minutes"),
        "policy.mandate_ttl_minutes",
        min_val=0.0,
        exclusive_min=True,
    )
    _check_finite_num(
        policy.get("user_cap_default"),
        "policy.user_cap_default",
        min_val=0.0,
        exclusive_min=True,
    )
    _check_finite_num(
        policy.get("daily_cash_out_limit"),
        "policy.daily_cash_out_limit",
        min_val=0.0,
        exclusive_min=True,
    )
    risk_high = _check_prob(policy.get("agent_risk_high"), "policy.agent_risk_high")
    risk_med = _check_prob(policy.get("agent_risk_medium"), "policy.agent_risk_medium")
    if risk_med >= risk_high:
        raise ConfigError(
            "policy.agent_risk_medium must be strictly less than policy.agent_risk_high"
        )
    _check_prob(policy.get("assisted_outreach_threshold"), "policy.assisted_outreach_threshold")
    _check_int(
        policy.get("max_verification_attempts"), "policy.max_verification_attempts", min_val=1
    )
    _check_int(
        policy.get("max_redemption_attempts"), "policy.max_redemption_attempts", min_val=1
    )
    if type(policy.get("review_on_mismatch")) is not bool:
        raise ConfigError("policy.review_on_mismatch must be a boolean.")

    v_modes = policy.get("verification_modes")
    if (
        not isinstance(v_modes, list)
        or not v_modes
        or not all(isinstance(m, str) and m for m in v_modes)
    ):
        raise ConfigError("policy.verification_modes must be a non-empty list of strings.")

    c_gap = policy.get("cash_gap")
    if not isinstance(c_gap, dict):
        raise ConfigError("Missing policy.cash_gap mapping.")
    _check_finite_num(c_gap.get("min_bdt"), "policy.cash_gap.min_bdt", min_val=0.0)
    _check_prob(c_gap.get("rate"), "policy.cash_gap.rate")

    # 15. Models (T023 controls) - required, fail closed
    if "models" not in config:
        raise ConfigError("Missing required 'models' mapping in configuration.")
    models = config["models"]
    if not isinstance(models, dict):
        raise ConfigError("Missing or invalid 'models' mapping in configuration.")

    # Assisted classifier
    ac = models.get("assisted_classifier")
    if not isinstance(ac, dict):
        raise ConfigError("Missing 'models.assisted_classifier' mapping.")
    _check_int(ac.get("n_estimators"), "models.assisted_classifier.n_estimators", min_val=1)
    _check_finite_num(
        ac.get("learning_rate"),
        "models.assisted_classifier.learning_rate",
        min_val=0.0,
        exclusive_min=True,
    )
    _check_int(ac.get("max_depth"), "models.assisted_classifier.max_depth", min_val=1)
    _check_prob(
        ac.get("classification_threshold"),
        "models.assisted_classifier.classification_threshold",
    )
    cal_method = ac.get("calibration_method")
    if cal_method not in ("sigmoid", "isotonic"):
        raise ConfigError(
            f"models.assisted_classifier.calibration_method must be 'sigmoid' or 'isotonic', "
            f"got {cal_method!r}"
        )
    if "calibrate" not in ac:
        raise ConfigError("Missing 'models.assisted_classifier.calibrate' control.")
    if type(ac.get("calibrate")) is not bool:
        raise ConfigError("models.assisted_classifier.calibrate must be a boolean.")

    # Agent anomaly
    aa = models.get("agent_anomaly")
    if not isinstance(aa, dict):
        raise ConfigError("Missing 'models.agent_anomaly' mapping.")
    _check_int(aa.get("n_estimators"), "models.agent_anomaly.n_estimators", min_val=1)
    _check_finite_num(
        aa.get("contamination"),
        "models.agent_anomaly.contamination",
        min_val=0.0,
        max_val=0.5,
        exclusive_min=True,
    )
    _check_int(aa.get("review_top_k"), "models.agent_anomaly.review_top_k", min_val=1)
    peer_groups = aa.get("peer_groups")
    if peer_groups != ["volume_band"]:
        raise ConfigError("models.agent_anomaly.peer_groups must equal ['volume_band'].")
    vq = aa.get("volume_quantiles")
    if not isinstance(vq, list) or len(vq) != 2:
        raise ConfigError(
            "models.agent_anomaly.volume_quantiles must be a list of two probabilities."
        )
    q1 = _check_prob(vq[0], "volume_quantiles[0]")
    q2 = _check_prob(vq[1], "volume_quantiles[1]")
    if q1 <= 0.0 or q2 >= 1.0 or q1 >= q2:
        raise ConfigError("volume_quantiles must satisfy 0.0 < q1 < q2 < 1.0.")
    w_z = _check_finite_num(
        aa.get("weight_z"), "models.agent_anomaly.weight_z", min_val=0.0, max_val=1.0
    )
    w_if = _check_finite_num(
        aa.get("weight_iforest"),
        "models.agent_anomaly.weight_iforest",
        min_val=0.0,
        max_val=1.0,
    )
    if abs(w_z + w_if - 1.0) > 1e-4:
        raise ConfigError(f"models.agent_anomaly weights must sum to 1.0, got {w_z + w_if}")
    _check_finite_num(
        aa.get("mad_floor"), "models.agent_anomaly.mad_floor", min_val=0.0, exclusive_min=True
    )
    _check_finite_num(
        aa.get("z_sigmoid_slope"),
        "models.agent_anomaly.z_sigmoid_slope",
        min_val=0.0,
        exclusive_min=True,
    )
    _check_finite_num(aa.get("z_sigmoid_midpoint"), "models.agent_anomaly.z_sigmoid_midpoint")

    # Baselines
    bl = models.get("baselines")
    if not isinstance(bl, dict):
        raise ConfigError("Missing 'models.baselines' mapping.")
    ar = bl.get("assisted_rule")
    if not isinstance(ar, dict):
        raise ConfigError("Missing 'models.baselines.assisted_rule' mapping.")
    _check_prob(
        ar.get("top_agent_share_min"),
        "models.baselines.assisted_rule.top_agent_share_min",
    )
    _check_finite_num(
        ar.get("hours_credit_to_cashout_max"),
        "models.baselines.assisted_rule.hours_credit_to_cashout_max",
        min_val=0.0,
        exclusive_min=True,
    )
    agr = bl.get("agent_rule")
    if not isinstance(agr, dict):
        raise ConfigError("Missing 'models.baselines.agent_rule' mapping.")
    _check_finite_num(
        agr.get("fee_ratio_over_official_min"),
        "models.baselines.agent_rule.fee_ratio_over_official_min",
        min_val=1.0,
    )

    # Sanity
    san = models.get("sanity")
    if not isinstance(san, dict):
        raise ConfigError("Missing 'models.sanity' mapping.")
    _check_prob(san.get("max_pr_auc"), "models.sanity.max_pr_auc")

    # 16. Fairness
    fairness = config.get("fairness")
    if not isinstance(fairness, dict):
        raise ConfigError("Missing required 'fairness' mapping in configuration.")
    slices = fairness.get("slices")
    if (
        not isinstance(slices, list)
        or not slices
        or not all(isinstance(s, str) and s for s in slices)
    ):
        raise ConfigError("fairness.slices must be a non-empty list of strings.")
    _check_prob(fairness.get("max_tpr_gap"), "fairness.max_tpr_gap")

    slice_cats = fairness.get("slice_categories")
    if not isinstance(slice_cats, dict):
        raise ConfigError("Missing fairness.slice_categories mapping.")
    for s_name in slices:
        if s_name not in slice_cats:
            raise ConfigError(f"fairness.slice_categories missing defined slice '{s_name}'")
        cats = slice_cats[s_name]
        if (
            not isinstance(cats, list)
            or not cats
            or not all(isinstance(c, str) and c for c in cats)
        ):
            raise ConfigError(
                f"fairness.slice_categories['{s_name}'] must be a non-empty list of strings."
            )

    cycle_days = credits["allowance"]["cycle_days"]
    if sim["allowance_day_of_cycle"] >= cycle_days:
        raise ConfigError("allowance_day_of_cycle must be inside the configured cycle")
    for profile in (norm_cfg, hv_cfg):
        if profile["fee_multiplier"] != 1 or profile["payout_reduction"] != 0:
            raise ConfigError("Honest agents must use official fee and unreduced payout")
    windows = [
        (aux.get("opening_delay_minutes"), "opening_delay_minutes", 0, 1439),
        (aux.get("extra_service_hours"), "extra_service_hours", 0, 23),
        (aux.get("extra_service_day_range"), "extra_service_day_range", 0, None),
    ]
    for kind in ("allowance", "family", "independent"):
        windows.append((aux.get("credit_hours", {}).get(kind), f"credit_hours.{kind}", 0, 23))
    for window, name, low, high in windows:
        if not isinstance(window, list) or len(window) != 2:
            raise ConfigError(f"{name} must be a two-element range")
        for value in window:
            _check_int(value, name, min_val=low, max_val=high)
        if window[0] > window[1]:
            raise ConfigError(f"{name} range is reversed")
    if "auth" in config:
        auth_cfg = config["auth"]
        if not isinstance(auth_cfg, dict):
            raise ConfigError("Missing or invalid 'auth' mapping in configuration.")
        if type(auth_cfg.get("demo_enabled")) is not bool:
            raise ConfigError("auth.demo_enabled must be a boolean.")
        _check_int(auth_cfg.get("token_ttl_minutes"), "auth.token_ttl_minutes", min_val=1)
        if auth_cfg.get("signing_algorithm") != "HS256":
            raise ConfigError("auth.signing_algorithm must be 'HS256'.")
        _check_int(auth_cfg.get("demo_seed"), "auth.demo_seed", min_val=0)
        _check_finite_num(
            auth_cfg.get("demo_initial_balance"),
            "auth.demo_initial_balance",
            min_val=0.0,
            exclusive_min=True,
        )
        credit_ts = auth_cfg.get("demo_credit_timestamp")
        if not isinstance(credit_ts, str):
            raise ConfigError("auth.demo_credit_timestamp must be an ISO 8601 string.")
        try:
            c_dt = datetime.fromisoformat(credit_ts.replace("Z", "+00:00"))
            if c_dt.tzinfo is None:
                raise ConfigError("auth.demo_credit_timestamp must include timezone offset.")
        except Exception as exc:
            raise ConfigError(
                f"Invalid auth.demo_credit_timestamp '{credit_ts}': {exc}"
            ) from exc

        principals = auth_cfg.get("principals")
        if not isinstance(principals, dict) or not principals:
            raise ConfigError("auth.principals must be a non-empty mapping.")
        for p_name, p_info in principals.items():
            if not isinstance(p_info, dict):
                raise ConfigError(f"auth.principals['{p_name}'] must be a mapping.")
            role = p_info.get("role")
            if role not in ("agent", "customer_channel", "analyst", "supervisor", "super_admin"):
                raise ConfigError(
                    f"auth.principals['{p_name}'].role must be one of "
                    "['agent', 'customer_channel', 'analyst', 'supervisor', 'super_admin']"
                )
            sub = p_info.get("subject")
            if not isinstance(sub, str) or not sub.strip():
                raise ConfigError(
                    f"auth.principals['{p_name}'].subject must be a non-empty string."
                )
            pin = p_info.get("pin")
            if not isinstance(pin, str) or not pin.strip():
                raise ConfigError(
                    f"auth.principals['{p_name}'].pin must be a non-empty string."
                )
            if "allowed_users" in p_info:
                ausers = p_info["allowed_users"]
                if not isinstance(ausers, list) or not all(
                    isinstance(u, str) for u in ausers
                ):
                    raise ConfigError(
                        f"auth.principals['{p_name}'].allowed_users must be a list of strings."
                    )
    return config
