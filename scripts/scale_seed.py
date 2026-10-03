#!/usr/bin/env python3
"""Load a platform-scale synthetic population (default 5,000,000 customers).

upay serves more than 5 million users, so the operations console must stay fast at that
size. This script bulk-generates synthetic customers inside PostgreSQL with
generate_series (no data leaves the database server), in batches so it never holds one
giant transaction:

- users U_9_0000001 ... U_9_<N>, with realistic segment/region/age mixes,
- one agent point per 250 customers (20,000 agents for 5 M customers), 1.5% of them
  overcharging the fee,
- one opening credit per customer (salary, allowance, remittance or add-money) in the
  last 60 days, and a cash-out at their home agent for about 40% of them.

All rows are synthetic and live in the reserved U_9_ namespace, disjoint from the
training cohorts and from the demo fixtures. Re-running continues where it stopped.

Usage:
    DATABASE_URL=postgresql://... python scripts/scale_seed.py --users 5000000
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg

BATCH = 250_000

INSERT_USERS = """
INSERT INTO users (user_id, group_label, gender, age_band, region, urban_rural, created_at)
SELECT 'U_9_' || lpad(g::text, 7, '0'),
       (ARRAY['independent_urban','independent_rural','assisted_allowance','assisted_family'])
           [1 + (hashint %% 100 >= 45)::int + (hashint %% 100 >= 75)::int
              + (hashint %% 100 >= 90)::int],
       (ARRAY['female','male','other'])[1 + (hashint / 7 %% 100 >= 49)::int
              + (hashint / 7 %% 100 >= 99)::int],
       (ARRAY['18-25','26-40','41-60','60+'])[1 + (hashint / 11 %% 4)],
       (ARRAY['dhaka','chittagong','rajshahi','khulna','barishal','sylhet','rangpur',
              'mymensingh'])[1 + (hashint / 13 %% 8)],
       CASE WHEN hashint / 17 %% 100 < 42 THEN 'urban' ELSE 'rural' END,
       now() - make_interval(days => 60 + hashint %% 700)
FROM (SELECT g, abs(hashtext('sathi' || g::text)) AS hashint
      FROM generate_series(%(lo)s, %(hi)s) g) s
ON CONFLICT (user_id) DO NOTHING;
"""

INSERT_CREDITS = """
INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, fee,
                          balance_after, channel, ts)
SELECT 'U_9_' || lpad(g::text, 7, '0'), NULL, 'credit',
       (ARRAY['salary','allowance','remittance','add_money'])[1 + (h %% 4)],
       amt, 0, amt, 'app',
       now() - make_interval(days => 2 + h %% 58, secs => h %% 86400)
FROM (SELECT g, abs(hashtext('credit' || g::text)) AS h,
             (5000 + abs(hashtext('amt' || g::text)) %% 55000)::numeric(12,2) AS amt
      FROM generate_series(%(lo)s, %(hi)s) g) s;
"""

AGENTS_PER_CUSTOMER = 250  # one agent point serves about 250 customers

INSERT_AGENTS = """
INSERT INTO agents (agent_id, region, volume_band, agent_type, created_at)
SELECT 'A_9_' || lpad(g::text, 6, '0'),
       (ARRAY['dhaka','chittagong','rajshahi','khulna','barishal','sylhet','rangpur',
              'mymensingh'])[1 + (abs(hashtext('ar' || g::text)) %% 8)],
       (ARRAY['low','medium','high'])[1 + (abs(hashtext('av' || g::text)) %% 3)],
       CASE WHEN abs(hashtext('skim' || g::text)) %% 1000 < 15 THEN 'skimmer' ELSE 'normal' END,
       now() - make_interval(days => 90 + abs(hashtext('ac' || g::text)) %% 900)
FROM generate_series(1, %(agents)s) g
ON CONFLICT (agent_id) DO NOTHING;
"""

# Each customer has a home agent. About 40% made one cash-out 1-48 hours after their credit
# (never in the future). A small share of agents (agent_type 'skimmer') overcharge the fee,
# which the live agent-risk model should surface.
INSERT_CASHOUTS = """
INSERT INTO transactions (user_id, agent_id, txn_type, credit_source, amount, fee,
                          balance_after, channel, ts)
SELECT s.uid, s.aid, 'cash_out', NULL, s.co,
       round(s.co * 0.015 * CASE WHEN a.agent_type = 'skimmer' THEN 1.6 ELSE 1 END, 2),
       s.amt - s.co - round(s.co * 0.015 * CASE WHEN a.agent_type = 'skimmer' THEN 1.6
                                                 ELSE 1 END, 2),
       'agent_initiated',
       LEAST(now() - interval '1 minute', s.credit_ts + make_interval(hours => 1 + s.h %% 48))
FROM (SELECT 'U_9_' || lpad(g::text, 7, '0') AS uid,
             'A_9_' || lpad((1 + abs(hashtext('home' || g::text)) %% %(agents)s)::text, 6, '0')
                 AS aid,
             (500 * (1 + abs(hashtext('co' || g::text)) %% 8))::numeric(12,2) AS co,
             (5000 + abs(hashtext('amt' || g::text)) %% 55000)::numeric(12,2) AS amt,
             now() - make_interval(days => 2 + abs(hashtext('credit' || g::text)) %% 58,
                                   secs => abs(hashtext('credit' || g::text)) %% 86400)
                 AS credit_ts,
             abs(hashtext('ts' || g::text)) AS h
      FROM generate_series(%(lo)s, %(hi)s) g
      WHERE abs(hashtext('pick' || g::text)) %% 100 < 40) s
JOIN agents a ON a.agent_id = s.aid;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=5_000_000)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--rebuild-cashouts", action="store_true",
                        help="Delete and regenerate the scale cash-outs for loaded customers")
    args = parser.parse_args()
    if not args.database_url:
        print("Set DATABASE_URL or pass --database-url.", file=sys.stderr)
        return 2
    with psycopg.connect(args.database_url, autocommit=True) as conn:
        cur = conn.cursor()
        agents = max(1, args.users // AGENTS_PER_CUSTOMER)
        cur.execute(INSERT_AGENTS, {"agents": agents})
        if args.rebuild_cashouts:
            cur.execute("SELECT max(user_id) FROM users WHERE user_id LIKE 'U_9_%%';")
            top = cur.fetchone()[0]
            loaded = int(top.rsplit("_", 1)[1]) if top else 0
            print(f"Rebuilding cash-outs for {loaded:,} customers across {agents:,} agents")
            cur.execute("DELETE FROM transactions WHERE user_id LIKE 'U_9_%%' "
                        "AND txn_type = 'cash_out' AND txn_id NOT IN "
                        "(SELECT txn_id FROM txn_checks);")
            for lo in range(1, loaded + 1, BATCH):
                hi = min(lo + BATCH - 1, loaded)
                cur.execute(INSERT_CASHOUTS, {"lo": lo, "hi": hi, "agents": agents})
                print(f"  {hi:>10,} customers", flush=True)
        cur.execute("SELECT max(user_id) FROM users WHERE user_id LIKE 'U_9_%%';")
        top = cur.fetchone()[0]
        start = int(top.rsplit("_", 1)[1]) + 1 if top else 1
        if start > args.users:
            print(f"Already loaded {start - 1:,} scale customers.")
            cur.execute("VACUUM (PARALLEL 0, ANALYZE) transactions;")
            return 0
        print(f"Loading customers {start:,} .. {args.users:,} in batches of {BATCH:,}")
        t0 = time.time()
        for lo in range(start, args.users + 1, BATCH):
            hi = min(lo + BATCH - 1, args.users)
            with conn.transaction():
                params = {"lo": lo, "hi": hi, "agents": agents}
                cur.execute(INSERT_USERS, params)
                cur.execute(INSERT_CREDITS, params)
                cur.execute(INSERT_CASHOUTS, params)
            rate = (hi - start + 1) / max(time.time() - t0, 0.001)
            print(f"  {hi:>10,} customers  ({rate:,.0f}/s)", flush=True)
        cur.execute("VACUUM (PARALLEL 0, ANALYZE) users;")
        cur.execute("VACUUM (PARALLEL 0, ANALYZE) transactions;")
    print(f"Done in {time.time() - t0:,.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
