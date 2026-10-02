# Synthetic Data Assumptions

All data is synthetic. Nothing here is real upay data. Every value below is an assumption to be validated with governed real data in any pilot. Change values in `data/config.yaml`, then record the change here.

## 1. Population
| Item | Value | Note |
|---|---|---|
| Customers | 20,000 | Four groups below |
| Agents | 300 | Normal, high-volume honest, skimmers |
| Window | 90 days | Daily granularity |
| Random seeds | train=42, validation=4242, test=2026 | Different seeds and disjoint agents for each split |

| Customer group | Share | Behavior |
|---|---|---|
| Independent urban | 40% | Mixed services, varied agents, low retry rate |
| Independent rural | 25% | More cash-out, moderate agent concentration |
| Assisted: allowance recipients | 20% | Fixed disbursement cycle, cash-out soon after credit, high agent concentration |
| Assisted: family-helped | 15% | Helper-initiated, evening spikes, moderate concentration |

## 2. Signals and how they are simulated
| Signal | Independent | Assisted | Caveat |
|---|---|---|---|
| Share of cash-outs at top agent | low-moderate | high | Overlap on purpose: some independent users are loyal to one agent |
| Hours from credit to cash-out | wide spread | short | |
| Fraction of balance withdrawn | variable | near full | |
| PIN retry rate | low | higher | Plausible from session logs; unverified for real upay |
| PIN entry duration | short | longer, more variable | Simulated, e.g. from USSD session timing |
| Services used (count) | many | few | |

## 3. Label noise and overlap (required)
- 10% of assisted labels flipped to independent-like behavior and vice versa.
- Feature distributions overlap so classification is not trivially separable.
- Report results with and without noise.

## 4. Agent behavior
| Type | Count | Behavior |
|---|---|---|
| Normal | ~270 | Fee at official rate, random amounts |
| High-volume honest | ~20 | Many customers, spikes on allowance days; used to measure false positives |
| Skimmers | ~10 | Mix of: fee above official rate, rounded-down payouts, targeting assisted users |

Skimming intensity is a parameter (subtle / moderate / obvious). Evaluate on all three.

## 5. Key limitation: skimming is mostly invisible in the ledger
If an agent hands over less cash than the ledger records, the ledger shows the full amount. Detection relies on indirect signals (fee ratio, round-down patterns, concentration, complaints) and on the **cash-received confirmation** the verification flow collects.
- Customers report cash received with probability `report_rate` and with accuracy `report_accuracy` (config), so we do not assume perfect reports.

## 6. Fee and limits (placeholders)
- Official cash-out fee rate: [SET AN ASSUMED VALUE IN CONFIG, label as assumption, do not present as upay's real rate].
- Per-user mandate cap and daily limits: configurable placeholders.

## 7. Splits
- Train/validation/test split **by agent and by seed**, not by row.
- Agent allocation: 60% train, 20% validation, 20% test (human-approved); use `simulation.agent_split` and `simulation.seed_validation` in config.
- A clean test set is never used for training or threshold tuning.

## 8. Adoption scenarios for impact simulation
Sathi adoption among assisted users: 30%, 50%, 70%. Report all three.

## 9. Ethics
- No real names, numbers, NID values or photos. IDs are random tokens.
- Gender, age band and region exist for fairness evaluation only, never as model inputs.

## 10. Change log
| Date | Change | Reason |
|---|---|---|
| 2026-10-02 | Added validation seed 4242 and 60/20/20 agent allocation | Human approved explicit validation setup; fee and caps remain unset pending separate values |
