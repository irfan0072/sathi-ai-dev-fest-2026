# Sathi Production Deployment Guide (Render)

This guide walks you through deploying the Sathi platform (Managed PostgreSQL database, FastAPI backend API, and React Console frontend) to **Render** using the repository's declarative Blueprint (`render.yaml`) directly from the Render web dashboard connected to your public GitHub repository.

---

## 1. Free-Tier Sleep and Expiry Limits

| Resource | Service Type | Free-Tier Limits & Expiry |
|---|---|---|
| **PostgreSQL Database** (`sathi-db`) | Managed Database | **Expires 30 days after creation.** After 30 days, Render drops the free database instance unless upgraded to a paid plan ($7/mo) or re-provisioned. Maximum 1 GB storage, 100 connections. |
| **FastAPI Backend** (`sathi-api`) | Web Service (Python) | **Spins down (sleeps) after 15 minutes of inactivity.** When an incoming request arrives, a cold start takes approximately **30–50 seconds** to spin up. Includes 750 free instance hours per month (enough for continuous uptime of 1 service). |
| **Sathi Console** (`sathi-console`) | Static Site | **Free forever.** Global CDN distribution, instant loads (no sleep, no cold starts), 100 GB free monthly bandwidth. |

---

## 2. Step-by-Step Deployment Instructions

### Step 1: Create a Render Account
1. Go to [https://render.com](https://render.com) and sign up with your GitHub account.
2. Grant Render read permissions to your public repository `irfan0072/sathi-ai-dev-fest-2026`.

### Step 2: Deploy Using Blueprint (One-Click Setup)
1. In your Render Dashboard, click **New +** (top right) and select **Blueprint**.
2. Connect the repository `irfan0072/sathi-ai-dev-fest-2026` and branch `main`.
3. Render will automatically detect `render.yaml` and show the 3 resources to create:
   - `sathi-db` (PostgreSQL Database)
   - `sathi-api` (Web Service)
   - `sathi-console` (Static Site)
4. Click **Apply**.
5. Render will automatically provision the managed database, build the FastAPI backend, and compile the frontend.

### Step 3: Run Database Migration and Seed
Once `sathi-db` and `sathi-api` finish initial build:
1. In the Render Dashboard, click into the **sathi-api** Web Service.
2. Go to the **Shell** tab (or run via Render CLI).
3. Run the following command inside the shell to apply schema migrations and seed the train split:
```sh
PYTHONPATH=backend python -m app.data.cli migrate
PYTHONPATH=backend python -m app.data.cli seed --dataset data/generated/splits/train.json
```
*(Optional: If you wish to seed all cohorts for full offline validation, also seed `validation.json` and `test.json`).*

### Step 4: Verify Health Checks
- **Backend API Health Check**:
  Visit `https://<your-sathi-api>.onrender.com/health` in your browser or curl:
  ```sh
  curl https://<your-sathi-api>.onrender.com/health
  # Expected response: {"status": "ok"}
  ```
- **Console Frontend Check**:
  Visit `https://<your-sathi-console>.onrender.com` in your browser. Verify the dashboard loads cleanly without errors.

---

## 3. Environment Variables Reference

Render automatically configures these from `render.yaml`. No secrets or passwords need to be committed.

| Variable Name | Required By | Purpose / Notes |
|---|---|---|
| `DATABASE_URL` | Backend (`sathi-api`) | Managed PostgreSQL connection string. **Automatically generated** by Render with a cryptographically secure random password. *Never use the local/CI password `CHANGE_ME` in production.* |
| `CORS_ORIGINS` | Backend (`sathi-api`) | Comma-separated list of allowed frontend origins (e.g. `https://sathi-console.onrender.com,http://localhost:13000`). Restricts cross-origin requests. |
| `SATHI_CONFIG` | Backend (`sathi-api`) | Path to configuration file: `data/config.yaml`. |
| `PYTHON_VERSION` | Backend (`sathi-api`) | Specifies Python runtime version (`3.11.9`). |
| `VITE_API_URL` | Frontend (`sathi-console`) | Public URL of the FastAPI backend service (`https://sathi-api.onrender.com`). Used by the frontend client to route API calls. |

---

## 4. Production Security Rules

1. **Zero Hardcoded Passwords**: The local CI password `CHANGE_ME` must NEVER be used on production. Render's managed database generates unique credentials per instance.
2. **Restricted CORS**: The backend rejects all origins except the explicit URL of the deployed `sathi-console` (and local development ports if specified).
3. **No Latent Truth Leakage**: Production endpoints and tables expose only public ledger fields (`users`, `agents`, `transactions`, `sessions`, `mandates`). Latent ground-truth simulation sidecars (`*.observations.json`) are never loaded into the production database.

---

## 5. Low-Privilege Synthetic Demo Logins

For judges, evaluators, and live demonstrations, use these pre-seeded synthetic test accounts:

### 1. Agent Terminal Simulator (Assisting Agent)
- **Role**: Field Agent initiating cash-out requests
- **Agent ID**: `A_000042`
- **Region**: `dhaka` | Volume Band: `medium`
- **Demo Terminal PIN**: `1234`
- **Capabilities**: Can create one-time mandate cash-out requests for assisted customers up to 5,000 BDT cap. Cannot approve transactions or access internal risk models.

### 2. Customer Phone Simulator (Assisted User)
- **Role**: Elderly / Assisted cash-out recipient
- **User ID**: `U_42_000123`
- **Phone / Token**: `01700000123`
- **Demo Customer PIN**: `5678`
- **Capabilities**: Receives one-time verification prompts, reviews mandate amount and fee, confirms or rejects cash-out.

### 3. Compliance & Risk Officer (Read-Only Reviewer)
- **Role**: Read-only auditor inspecting flags and policy metrics
- **Username**: `officer_audit`
- **Password**: `demo_audit_2026`
- **Capabilities**: Read-only access to flag cases, fairness audits, and audit logs. Cannot alter policy rules or bypass customer verification.
