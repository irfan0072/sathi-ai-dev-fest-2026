# Sathi (সাথী): Delegated Trust for Assisted MFS Users

> AI DEV FEST 2026, AI Hackathon (DIU CPC x upay). Track 07: Open Innovation.
> Team: Runtime Terrors. Status: TEMPLATE. Fill every [PLACEHOLDER] before submission.

## 1. Project overview
- **Problem:** [Many older and first-time users cannot operate their wallets alone, so they share their PIN with agents or relatives. This exposes them to theft and overcharging, and fraud models cannot tell who is really transacting.]
- **Solution:** [Sathi replaces PIN sharing with scoped, one-time, auditable mandates, verifies the customer's intent in Bangla (voice or keypad), finds users likely to need help, and flags abnormal agent behavior.]
- **Purpose:** [Safer digital finance for vulnerable users, measured by fewer PIN disclosures and less simulated loss.]

## 2. Features
| Feature | Implemented? | How AI is used |
|---|---|---|
| Scoped one-time mandate engine | [ ] | Rules only (deterministic) |
| Assisted-user detection | [ ] | LightGBM classifier + SHAP |
| Agent anomaly detection | [ ] | Peer z-score + Isolation Forest |
| Bangla voice / keypad verification | [ ] | Speech-to-text (optional), rule-based amount parsing |
| Plain-language receipt and case narrative | [ ] | LLM wording over structured evidence only |
| Analyst console with human review | [ ] | n/a |

## 3. Technology stack
- Python [version], FastAPI, PostgreSQL [version], React [version]
- ML: scikit-learn, LightGBM, SHAP, NetworkX (optional)
- AI services: [speech-to-text provider], [LLM provider/model]
- Deployment: [platform]

## 4. Requirements
- [OS, Python, Node, Docker versions]
- [Hardware notes, API access needed]

## 5. Installation and setup
1. `git clone [REPO_URL] && cd sathi`
2. [Install backend dependencies]
3. [Install console dependencies]
4. [Start Postgres, e.g. docker compose up -d db]
5. [Run migrations: docs/schema.sql]
6. [Generate synthetic data: seed command]
7. [Train models: train command]

## 6. Environment variables (use placeholders, never real secrets)
| Name | Purpose | Example |
|---|---|---|
| DATABASE_URL | Postgres connection | postgresql://user:pass@localhost:5432/sathi |
| LLM_API_KEY | LLM provider key | YOUR_KEY_HERE |
| STT_API_KEY | Speech-to-text key | YOUR_KEY_HERE |
| JWT_SECRET | Token signing | CHANGE_ME |
| SATHI_CONFIG | Path to config | data/config.yaml |

## 7. Run and build commands
- Backend: `[command]`
- Console: `[command]`
- Full stack: `[docker compose up --build]`
- Production build: `[command]`

## 8. Live deployment URL
[https://...]  Demo logins: [role: credentials for judges]

## 9. Testing instructions
- Unit/policy/lifecycle tests: `[command]`
- Reproduce evaluation numbers: `[command]`
- Manual check: follow docs/demo-script.md

## 10. Other configuration
- Thresholds live in `data/config.yaml`. All synthetic assumptions are in `data/assumptions.md`.
- Data is 100% synthetic. No real customer data or PII is used.

## Disclosures
- External services/models: [list]. Pre-existing components: [list]. AI tools used for development: [list].
