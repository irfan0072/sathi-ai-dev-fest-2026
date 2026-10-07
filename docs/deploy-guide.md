# Deploying Sathi on Render

## Live deployment

| Service | URL |
|---|---|
| Console | <https://sathi-console.onrender.com/> |
| API health | <https://sathi-api-mqk2.onrender.com/health> |

`render.yaml` is a Render Blueprint with three resources: a managed PostgreSQL 16 database
(`sathi-db`), the FastAPI service (`sathi-api`) and the static console (`sathi-console`).

## Deploy from scratch

1. In Render choose **New → Blueprint**, connect the repository, branch `main`, file
   `render.yaml`, and review the resources before applying.
2. After the services exist, set on `sathi-api`:
   - `CORS_ORIGINS` = the console's public HTTPS origin
   - `SATHI_PUBLIC_API_URL` = the API's public HTTPS origin (needed for live calls)
3. Set `VITE_API_URL` on `sathi-console` to the API's public HTTPS URL and redeploy the
   console (Vite embeds it at build time).
4. Keep `DATABASE_URL` linked to the managed database and let Render generate
   `JWT_SECRET`. Never commit secrets.
5. On start, `PYTHONPATH=backend python -m app.bootstrap` checks the signing secret,
   configuration and model artifacts, applies migrations and seeds the small demo
   namespace. Restarts preserve balances and cases.

## Deployment mode (public demo isolation)

`render.yaml` sets `SATHI_DEPLOYMENT_MODE=public_demo` and `SATHI_SETTINGS_EDITABLE=false`. The
demo staff PINs are published, so in this mode:

- settings, provider credentials, staff and test-account management are read-only (HTTP 403,
  `PUBLIC_DEMO_READ_ONLY`);
- the voice and SMS providers are pinned to `simulated` and the case-brief AI to the deterministic
  summary, whatever a saved override or an environment variable says;
- provider probes and paid test calls/SMS are refused;
- the synthetic demo sign-in, cash-out, confirmation, queue and case workflow still work.

Use `local` (the default when the variable is unset) or `pilot` only on a private deployment with
its own credentials. An unknown value is treated as `public_demo`. `GET /api/v1/deployment` reports
the mode and the console shows "Public simulated demo". This separation is **not** a penetration
test. Remaining gaps: published PINs still reach the analyst and supervisor workflow, tokens of
agents and customers are not re-checked against account status, there is no durable login
attempt limiter, the audit trail can be altered by a database owner, and no independent review has
been done. A public instance must never hold real provider credentials.

## Load the synthetic population (fills the AI pages)

The bootstrap seeds only the demo accounts. To load the 20,000-customer synthetic dataset,
copy the database's **External Database URL** from the Render dashboard and run locally:

```sh
DATABASE_URL='<External Database URL>' PYTHONPATH=backend \
  .venv/bin/python -m app.data.cli seed --dataset data/generated/train.json
```

Then restart `sathi-api`. On startup the ledger dates are shifted to recent days, and the
live models fill the AI pages within a few minutes.

## Live calls and SMS

Add Twilio (or Bangladesh IVR) and Alpha SMS credentials on the **Settings** page, then pick
the provider. Twilio requires an upgraded account: trial accounts only allow Twilio's sample
call scripts, so Sathi's own prompt and keypad answer cannot run. The simulated handset needs
no provider and runs the same call logic. Full details: [live-mode.md](live-mode.md).

## Free-plan limits

- Free web services sleep after 15 idle minutes; the first request then takes about a
  minute, which is longer than Twilio waits for a webhook. Open `/health` before a demo, or
  use an always-on plan.
- The free plan has about 0.1 CPU. A paid instance makes pages several times faster.
- Free PostgreSQL is limited to 1 GB and expires after 30 days.
  [Render free-service limits](https://render.com/docs/free).

## Demo sign-in

Pick a role on the sign-in screen; the public synthetic PIN is filled in: agent `1234`,
customer `5678`, supervisor `3456`, super admin `7890`, analyst `9012`.
