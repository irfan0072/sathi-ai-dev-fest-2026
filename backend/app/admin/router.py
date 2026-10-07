"""Super admin API: live platform overview, directories and staff management.

Built for platform scale (millions of customers and transactions):
- every list uses keyset pagination on an indexed key (never OFFSET),
- table sizes come from PostgreSQL statistics instead of count(*) over big tables,
- time-window aggregates hit the ts / created_at indexes added in migration 008.
All numbers are read live from the database; nothing comes from a frozen snapshot.
"""

from __future__ import annotations

import datetime
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.ops.router import case_priority, response_targets

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

Admin = Annotated[AuthenticatedPrincipal, Depends(require_roles("super_admin"))]
EXACT_COUNT_LIMIT = 200_000


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _conn():
    return get_mandate_service().get_connection()


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _f(value: Any) -> float | None:
    return float(value) if value is not None else None


def _table_size(cur: Any, table: str) -> dict[str, Any]:
    """Fast row count: planner statistics for big tables, exact count for small ones."""
    cur.execute("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s);", (table,))
    row = cur.fetchone()
    estimate = int(row[0]) if row and row[0] is not None else -1
    if 0 <= estimate < EXACT_COUNT_LIMIT or estimate < 0:
        cur.execute(f"SELECT count(*) FROM {table};")  # table name is a fixed literal
        return {"value": cur.fetchone()[0], "exact": True}
    return {"value": estimate, "exact": False}


# ---------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(principal: Admin) -> Any:
    now = datetime.datetime.now(datetime.timezone.utc)
    out: dict[str, Any] = {"generated_at": now.isoformat()}
    with _conn() as conn, conn.cursor() as cur:
        out["platform"] = {
            "customers": _table_size(cur, "users"),
            "agents": _table_size(cur, "agents"),
            "transactions": _table_size(cur, "transactions"),
        }
        cur.execute("SELECT count(*) FILTER (WHERE role = 'supervisor' AND active), "
                    "count(*) FILTER (WHERE role = 'super_admin' AND active), "
                    "count(*) FILTER (WHERE last_login_at > now() - interval '30 minutes') "
                    "FROM staff;")
        sup, admins, online = cur.fetchone()
        out["platform"]["supervisors"] = sup
        out["platform"]["admins"] = admins
        out["platform"]["staff_online"] = online

        cur.execute(
            """
            SELECT count(*), COALESCE(sum(amount), 0),
                   count(*) FILTER (WHERE txn_type = 'cash_out'),
                   COALESCE(sum(amount) FILTER (WHERE txn_type = 'cash_out'), 0),
                   COALESCE(sum(fee), 0)
            FROM transactions WHERE ts > now() - interval '24 hours' AND ts <= now();
            """)
        n, volume, cashouts, cash_bdt, fees = cur.fetchone()
        cur.execute("SELECT count(*), COALESCE(sum(amount), 0) FROM transactions "
                    "WHERE ts > now() - interval '1 hour' AND ts <= now();")
        n_hour, bdt_hour = cur.fetchone()
        out["money_24h"] = {"transactions": n, "volume_bdt": float(volume),
                            "cashouts": cashouts, "cashout_bdt": float(cash_bdt),
                            "fees_bdt": float(fees), "transactions_last_hour": n_hour,
                            "volume_last_hour_bdt": float(bdt_hour)}

        cur.execute("SELECT status, count(*), COALESCE(sum(amount), 0) FROM txn_checks "
                    "WHERE created_at > now() - interval '24 hours' GROUP BY status;")
        checks = {r[0]: {"count": r[1], "amount_bdt": float(r[2])} for r in cur.fetchall()}
        decided = sum(checks.get(s, {}).get("count", 0) for s in ("verified", "suspicious"))
        out["checks_24h"] = {
            "by_status": checks,
            "total": sum(v["count"] for v in checks.values()),
            "verified_rate": round(checks.get("verified", {}).get("count", 0) / decided, 4)
            if decided else None,
            "suspicious_bdt": checks.get("suspicious", {}).get("amount_bdt", 0.0),
        }

        cur.execute("SELECT status, count(*) FROM call_tasks GROUP BY status;")
        tasks = dict(cur.fetchall())
        cur.execute("SELECT status, count(*) FROM voice_calls "
                    "WHERE created_at > now() - interval '24 hours' GROUP BY status;")
        calls = dict(cur.fetchall())
        total_calls = sum(calls.values())
        answered = sum(calls.get(s, 0) for s in ("verified", "mismatch", "duress", "rejected",
                                                  "unclear"))
        out["calls"] = {"tasks": tasks, "calls_24h": calls, "total_24h": total_calls,
                        "answer_rate": round(answered / total_calls, 4) if total_calls else None,
                        "manual_waiting": tasks.get("needs_manual", 0),
                        "manual_active": tasks.get("assigned", 0) + tasks.get("in_progress", 0),
                        "retrying": tasks.get("retry_scheduled", 0),
                        "ignored": tasks.get("ignored", 0)}

        cur.execute("SELECT case_id, reason, created_at, assigned_to, evidence FROM cases "
                    "WHERE status IN ('open','escalated');")
        open_cases = cur.fetchall()
        targets = response_targets()
        urgent = breached = unassigned = 0
        for _cid, reason, created, assignee, evidence in open_cases:
            priority, sla = case_priority(reason, targets)
            ev = json.loads(evidence) if isinstance(evidence, str) else (evidence or {})
            if priority == "urgent" or ev.get("priority") == "urgent":
                urgent += 1
            if (now - created).total_seconds() / 60 > sla:
                breached += 1
            if assignee is None:
                unassigned += 1
        cur.execute("SELECT status, count(*) FROM cases WHERE created_at > now() - "
                    "interval '24 hours' GROUP BY status;")
        out["cases"] = {"open": len(open_cases), "urgent": urgent, "sla_breached": breached,
                        "unassigned": unassigned, "opened_24h": dict(cur.fetchall())}
        cur.execute("SELECT count(*), count(*) FILTER (WHERE decision = 'denied') "
                    "FROM audit_reports WHERE created_at > now() - interval '24 hours';")
        reports, confirmed = cur.fetchone()
        out["cases"]["reports_24h"] = reports
        out["cases"]["confirmed_problems_24h"] = confirmed

        cur.execute(
            """
            SELECT date_trunc('hour', created_at) h, count(*),
                   count(*) FILTER (WHERE status = 'verified'),
                   count(*) FILTER (WHERE status = 'suspicious'),
                   count(*) FILTER (WHERE status IN ('unreachable','manual_review')),
                   COALESCE(sum(amount), 0)
            FROM txn_checks WHERE created_at > now() - interval '24 hours'
            GROUP BY h ORDER BY h;
            """)
        out["hourly"] = [{"hour": _iso(r[0]), "cashouts": r[1], "verified": r[2],
                          "suspicious": r[3], "needs_person": r[4], "bdt": float(r[5])}
                         for r in cur.fetchall()]
        cur.execute(
            """
            SELECT date_trunc('minute', created_at) m, count(*),
                   count(*) FILTER (WHERE status = 'suspicious')
            FROM txn_checks WHERE created_at > now() - interval '30 minutes'
            GROUP BY m ORDER BY m;
            """)
        out["per_minute"] = [{"minute": _iso(r[0]), "cashouts": r[1], "suspicious": r[2]}
                             for r in cur.fetchall()]

        cur.execute(
            """
            SELECT k.agent_id, count(*) FILTER (WHERE k.status = 'suspicious') sus, count(*) n,
                   EXISTS(SELECT 1 FROM agent_watchlist w WHERE w.agent_id = k.agent_id),
                   a.region
            FROM txn_checks k LEFT JOIN agents a USING (agent_id)
            WHERE k.created_at > now() - interval '7 days' AND k.agent_id IS NOT NULL
            GROUP BY k.agent_id, a.region HAVING count(*) FILTER (WHERE k.status = 'suspicious') > 0
            ORDER BY sus DESC, n DESC LIMIT 8;
            """)
        out["risky_agents"] = [{"agent_id": r[0], "suspicious_7d": r[1], "checks_7d": r[2],
                                "watchlisted": r[3], "region": r[4]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT a.region, count(*), count(*) FILTER (WHERE k.status = 'suspicious'),
                   COALESCE(sum(k.amount), 0)
            FROM txn_checks k JOIN agents a USING (agent_id)
            WHERE k.created_at > now() - interval '24 hours'
            GROUP BY a.region ORDER BY count(*) DESC;
            """)
        out["regions"] = [{"region": r[0], "cashouts": r[1], "suspicious": r[2],
                           "bdt": float(r[3])} for r in cur.fetchall()]

        cur.execute(
            "SELECT actor, action, entity, entity_id, ts FROM audit_log "
            "ORDER BY ts DESC LIMIT 25;")
        out["events"] = [{"actor": r[0], "action": r[1], "entity": r[2], "entity_id": r[3],
                          "at": _iso(r[4])} for r in cur.fetchall()]
    from app.settings.router import get_settings

    values = get_settings().values()
    out["simulator"] = {"enabled": bool(values.get("sim.enabled")),
                        "rate_per_minute": int(values.get("sim.rate_per_minute", 12))}
    return out


# ---------------------------------------------------------------------------- customers
@router.get("/users")
def users(principal: Admin, q: str | None = Query(default=None, max_length=40),
          after: str | None = Query(default=None, max_length=40),
          limit: int = Query(default=50, ge=1, le=200)) -> Any:
    where, params = [], []
    if q:
        prefix = q.strip().upper()
        col = "u.msisdn" if prefix.isdigit() else "u.user_id"
        where.append(f"{col} >= %s AND {col} < %s")
        params += [prefix, prefix + "￿"]
    if after:
        where.append("u.user_id > %s")
        params.append(after)
    sql = (
        "SELECT u.user_id, u.group_label, u.gender, u.age_band, u.region, u.urban_rural, "
        "u.created_at, b.balance_after, b.ts, "
        "(SELECT count(*) FROM txn_checks k WHERE k.user_id = u.user_id "
        " AND k.status = 'suspicious') "
        "FROM users u LEFT JOIN LATERAL (SELECT balance_after, ts FROM transactions t "
        " WHERE t.user_id = u.user_id ORDER BY t.ts DESC, t.txn_id DESC LIMIT 1) b ON TRUE "
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY u.user_id LIMIT %s;")
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (*params, limit + 1))
        rows = cur.fetchall()
        total = _table_size(cur, "users")
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{"user_id": r[0], "segment": r[1], "gender": r[2], "age_band": r[3],
              "region": r[4], "area": r[5], "created_at": _iso(r[6]),
              "balance": _f(r[7]), "last_activity": _iso(r[8]), "flagged": r[9]}
             for r in rows]
    return {"items": items, "total": total,
            "next_after": items[-1]["user_id"] if more and items else None}


@router.get("/users/{user_id}")
def user_detail(user_id: str, principal: Admin) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id, group_label, gender, age_band, region, urban_rural, "
                    "created_at FROM users WHERE user_id = %s;", (user_id,))
        u = cur.fetchone()
        if not u:
            return _err(404, "USER_NOT_FOUND", "Customer not found.")
        cur.execute("SELECT txn_id, agent_id, txn_type, credit_source, amount, fee, "
                    "balance_after, channel, ts FROM transactions WHERE user_id = %s "
                    "ORDER BY ts DESC, txn_id DESC LIMIT 30;", (user_id,))
        txns = [{"txn_id": r[0], "agent_id": r[1], "txn_type": r[2], "credit_source": r[3],
                 "amount": _f(r[4]), "fee": _f(r[5]), "balance_after": _f(r[6]),
                 "channel": r[7], "ts": _iso(r[8])} for r in cur.fetchall()]
        cur.execute("SELECT check_id, txn_id, agent_id, amount, status, outcome, case_id, "
                    "created_at FROM txn_checks WHERE user_id = %s ORDER BY created_at DESC "
                    "LIMIT 20;", (user_id,))
        checks = [{"check_id": r[0], "txn_id": r[1], "agent_id": r[2], "amount": _f(r[3]),
                   "status": r[4], "outcome": r[5], "case_id": r[6], "at": _iso(r[7])}
                  for r in cur.fetchall()]
        cur.execute("SELECT count(*), COALESCE(sum(amount), 0) FROM transactions "
                    "WHERE user_id = %s AND txn_type = 'cash_out';", (user_id,))
        n_cash, cash_bdt = cur.fetchone()
    return {"user_id": u[0], "segment": u[1], "gender": u[2], "age_band": u[3],
            "region": u[4], "area": u[5], "created_at": _iso(u[6]),
            "balance": txns[0]["balance_after"] if txns else None,
            "cashouts_total": n_cash, "cashout_bdt_total": float(cash_bdt),
            "transactions": txns, "checks": checks}


# ---------------------------------------------------------------------------- agents
@router.get("/agents")
def agents(principal: Admin, q: str | None = Query(default=None, max_length=40),
           after: str | None = Query(default=None, max_length=40),
           region: str | None = Query(default=None, max_length=20),
           limit: int = Query(default=50, ge=1, le=200)) -> Any:
    where, params = [], []
    if q:
        prefix = q.strip().upper()
        col = "a.msisdn" if prefix.isdigit() else "a.agent_id"
        where.append(f"{col} >= %s AND {col} < %s")
        params += [prefix, prefix + "￿"]
    if region:
        where.append("a.region = %s")
        params.append(region.lower())
    if after:
        where.append("a.agent_id > %s")
        params.append(after)
    sql = (
        "SELECT a.agent_id, a.region, a.volume_band, a.created_at, "
        "(SELECT count(*) FROM transactions t WHERE t.agent_id = a.agent_id "
        " AND t.ts > now() - interval '30 days' AND t.ts <= now()), "
        "(SELECT count(*) FROM txn_checks k WHERE k.agent_id = a.agent_id "
        " AND k.created_at > now() - interval '30 days'), "
        "(SELECT count(*) FROM txn_checks k WHERE k.agent_id = a.agent_id "
        " AND k.status = 'suspicious' AND k.created_at > now() - interval '30 days'), "
        "(SELECT count(*) FROM cases c WHERE c.agent_id = a.agent_id "
        " AND c.status IN ('open','escalated')), "
        "EXISTS(SELECT 1 FROM agent_watchlist w WHERE w.agent_id = a.agent_id) "
        "FROM agents a" + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY a.agent_id LIMIT %s;")
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (*params, limit + 1))
        rows = cur.fetchall()
        total = _table_size(cur, "agents")
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for r in rows:
        checks, sus = r[5], r[6]
        items.append({"agent_id": r[0], "region": r[1], "volume_band": r[2],
                      "created_at": _iso(r[3]), "txns_30d": r[4], "checks_30d": checks,
                      "suspicious_30d": sus, "open_cases": r[7], "watchlisted": r[8],
                      "suspicious_rate": round(sus / checks, 4) if checks else None})
    return {"items": items, "total": total,
            "next_after": items[-1]["agent_id"] if more and items else None}


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str, principal: Admin) -> Any:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT agent_id, region, volume_band, created_at FROM agents "
                    "WHERE agent_id = %s;", (agent_id,))
        a = cur.fetchone()
        if not a:
            return _err(404, "AGENT_NOT_FOUND", "Agent not found.")
        cur.execute("SELECT check_id, txn_id, user_id, amount, status, outcome, case_id, "
                    "created_at FROM txn_checks WHERE agent_id = %s ORDER BY created_at DESC "
                    "LIMIT 30;", (agent_id,))
        checks = [{"check_id": r[0], "txn_id": r[1], "user_id": r[2], "amount": _f(r[3]),
                   "status": r[4], "outcome": r[5], "case_id": r[6], "at": _iso(r[7])}
                  for r in cur.fetchall()]
        cur.execute("SELECT case_id, reason, status, assigned_to, created_at FROM cases "
                    "WHERE agent_id = %s ORDER BY created_at DESC LIMIT 20;", (agent_id,))
        cases = [{"case_id": r[0], "reason": r[1], "status": r[2], "assigned_to": r[3],
                  "at": _iso(r[4])} for r in cur.fetchall()]
        cur.execute("SELECT reason, added_by, created_at FROM agent_watchlist "
                    "WHERE agent_id = %s;", (agent_id,))
        w = cur.fetchone()
        cur.execute("SELECT date_trunc('day', ts) d, count(*), COALESCE(sum(amount), 0) "
                    "FROM transactions WHERE agent_id = %s AND txn_type = 'cash_out' "
                    "AND ts > now() - interval '14 days' AND ts <= now() GROUP BY d ORDER BY d;",
                    (agent_id,))
        daily = [{"day": _iso(r[0]), "cashouts": r[1], "bdt": float(r[2])}
                 for r in cur.fetchall()]
    return {"agent_id": a[0], "region": a[1], "volume_band": a[2], "created_at": _iso(a[3]),
            "watchlist": {"reason": w[0], "added_by": w[1], "at": _iso(w[2])} if w else None,
            "checks": checks, "cases": cases, "daily": daily}


# ---------------------------------------------------------------------------- transactions
@router.get("/transactions")
def transactions(principal: Admin,
                 before: int | None = Query(default=None, ge=1),
                 txn_type: Literal["credit", "cash_out", "send", "bill_pay"] | None = None,
                 user_id: str | None = Query(default=None, max_length=40),
                 agent_id: str | None = Query(default=None, max_length=40),
                 check_status: str | None = Query(default=None, max_length=20),
                 include_future: bool = False,
                 limit: int = Query(default=50, ge=1, le=200)) -> Any:
    where, params = [], []
    if not include_future:
        where.append("t.ts <= now()")
    if before:
        where.append("t.txn_id < %s")
        params.append(before)
    if txn_type:
        where.append("t.txn_type = %s")
        params.append(txn_type)
    # Each filter takes the internal ID or the phone number.
    if user_id:
        value = user_id.strip().upper()
        where.append("t.user_id = (SELECT user_id FROM users WHERE msisdn = %s)"
                     if value.isdigit() else "t.user_id = %s")
        params.append(value)
    if agent_id:
        value = agent_id.strip().upper()
        where.append("t.agent_id = (SELECT agent_id FROM agents WHERE msisdn = %s)"
                     if value.isdigit() else "t.agent_id = %s")
        params.append(value)
    if check_status:
        where.append("k.status = %s")
        params.append(check_status)
    sql = (
        "SELECT t.txn_id, t.user_id, t.agent_id, t.txn_type, t.credit_source, t.amount, t.fee, "
        "t.balance_after, t.channel, t.ts, k.check_id, k.status, k.outcome, k.case_id, k.source "
        "FROM transactions t LEFT JOIN txn_checks k ON k.txn_id = t.txn_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY t.txn_id DESC LIMIT %s;")
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '8s';")
        cur.execute(sql, (*params, limit + 1))
        rows = cur.fetchall()
        total = _table_size(cur, "transactions")
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{"txn_id": r[0], "user_id": r[1], "agent_id": r[2], "txn_type": r[3],
              "credit_source": r[4], "amount": _f(r[5]), "fee": _f(r[6]),
              "balance_after": _f(r[7]), "channel": r[8], "ts": _iso(r[9]),
              "check_id": r[10], "check_status": r[11], "outcome": r[12], "case_id": r[13],
              "source": r[14]} for r in rows]
    return {"items": items, "total": total,
            "next_before": items[-1]["txn_id"] if more and items else None}


# ---------------------------------------------------------------------------- audit log
@router.get("/audit-log")
def audit_log(principal: Admin, before: int | None = Query(default=None, ge=1),
              actor: str | None = Query(default=None, max_length=60),
              limit: int = Query(default=50, ge=1, le=200)) -> Any:
    where, params = [], []
    if before:
        where.append("log_id < %s")
        params.append(before)
    if actor:
        where.append("actor = %s")
        params.append(actor)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT log_id, actor, action, entity, entity_id, detail, ts FROM audit_log"
                    + (" WHERE " + " AND ".join(where) if where else "")
                    + " ORDER BY log_id DESC LIMIT %s;", (*params, limit + 1))
        rows = cur.fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    items = [{"log_id": r[0], "actor": r[1], "action": r[2], "entity": r[3],
              "entity_id": r[4], "detail": json.loads(r[5]) if isinstance(r[5], str) else r[5],
              "at": _iso(r[6])} for r in rows]
    return {"items": items, "next_before": items[-1]["log_id"] if more and items else None}


# ---------------------------------------------------------------------------- staff
class StaffCreate(BaseModel):
    staff_id: str = Field(..., min_length=3, max_length=41)
    display_name: str = Field(..., min_length=2, max_length=80)
    role: Literal["supervisor", "super_admin"] = "supervisor"
    pin: str = Field(..., min_length=4, max_length=8)


class StaffUpdate(BaseModel):
    active: bool | None = None
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    pin: str | None = Field(default=None, min_length=4, max_length=8)


@router.get("/staff")
def staff_list(principal: Admin, role: str | None = None) -> Any:
    from app.staff.service import get_staff_service

    return {"items": get_staff_service().list(role)}


@router.post("/staff", status_code=201)
def staff_create(body: StaffCreate, principal: Admin) -> Any:
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.staff.service import StaffError, get_staff_service

    try:
        item = get_staff_service().create(body.staff_id, body.display_name, body.role, body.pin,
                                          principal.subject)
    except StaffError as err:
        return _err(err.status_code, err.code, err.message)
    get_mandate_service().log_audit(principal.subject, "staff_created", "staff",
                                    item["staff_id"], {"role": body.role})
    return item


@router.patch("/staff/{staff_id}")
def staff_update(staff_id: str, body: StaffUpdate, principal: Admin) -> Any:
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.staff.service import StaffError, get_staff_service

    try:
        item = get_staff_service().update(staff_id, principal.subject, active=body.active,
                                          display_name=body.display_name, pin=body.pin)
    except StaffError as err:
        return _err(err.status_code, err.code, err.message)
    get_mandate_service().log_audit(
        principal.subject, "staff_updated", "staff", staff_id,
        {"active": body.active, "renamed": body.display_name is not None,
         "pin_reset": body.pin is not None})
    return item


# ---------------------------------------------------------------------------- test accounts
class AccountCreate(BaseModel):
    kind: Literal["customer", "agent"]
    phone: str = Field(..., min_length=11, max_length=20)
    display_name: str = Field(..., min_length=2, max_length=80)
    pin: str = Field(..., min_length=4, max_length=8)
    region: str = Field(default="dhaka", max_length=20)
    opening_balance: float = Field(default=0, ge=0, le=500000)


class AccountUpdate(BaseModel):
    active: bool | None = None
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    pin: str | None = Field(default=None, min_length=4, max_length=8)


class AddMoney(BaseModel):
    amount: float = Field(..., gt=0, le=500000)


@router.get("/accounts")
def accounts_list(principal: Admin) -> Any:
    from app.accounts.service import get_account_service

    return {"items": get_account_service().list()}


@router.post("/accounts", status_code=201)
def accounts_create(body: AccountCreate, principal: Admin) -> Any:
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.accounts.service import AccountError, get_account_service

    try:
        item = get_account_service().create(body.kind, body.phone, body.display_name, body.pin,
                                            body.region, body.opening_balance,
                                            principal.subject)
    except AccountError as err:
        return _err(err.status_code, err.code, err.message)
    get_mandate_service().log_audit(principal.subject, "account_created", body.kind,
                                    item["subject"], {"opening_balance": body.opening_balance})
    return item


@router.patch("/accounts/{account_id}")
def accounts_update(account_id: int, body: AccountUpdate, principal: Admin) -> Any:
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.accounts.service import AccountError, get_account_service

    try:
        item = get_account_service().update(account_id, active=body.active,
                                            display_name=body.display_name, pin=body.pin)
    except AccountError as err:
        return _err(err.status_code, err.code, err.message)
    get_mandate_service().log_audit(
        principal.subject, "account_updated", item["kind"], item["subject"],
        {"active": body.active, "renamed": body.display_name is not None,
         "pin_reset": body.pin is not None})
    return item


@router.post("/accounts/{account_id}/add-money")
def accounts_add_money(account_id: int, body: AddMoney, principal: Admin) -> Any:
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.accounts.service import AccountError, get_account_service

    try:
        item = get_account_service().add_money(account_id, body.amount)
    except AccountError as err:
        return _err(err.status_code, err.code, err.message)
    get_mandate_service().log_audit(principal.subject, "account_money_added", item["kind"],
                                    item["subject"], {"amount": body.amount})
    return item


# ---------------------------------------------------------------------------- simulator
class SimulatorUpdate(BaseModel):
    enabled: bool
    rate_per_minute: int | None = Field(default=None, ge=1, le=600)


@router.put("/simulator")
def simulator(body: SimulatorUpdate, principal: Admin) -> Any:
    from app.settings.router import get_settings
    from app.settings.service import SettingsError

    changes: dict[str, Any] = {"sim.enabled": body.enabled}
    if body.rate_per_minute is not None:
        changes["sim.rate_per_minute"] = body.rate_per_minute
    settings = get_settings()
    try:
        settings.update(changes, principal.subject)
    except SettingsError as err:
        return _err(422, "SETTINGS_INVALID", str(err))
    values = settings.values()
    return {"enabled": bool(values["sim.enabled"]),
            "rate_per_minute": int(values["sim.rate_per_minute"])}
