"""Database operations, migrations, validation, and seed loading for Sathi."""

import hashlib
import json
import os
import re
import urllib.parse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import psycopg
except ImportError:
    psycopg = None

# 64-bit advisory lock for schema migrations
MIGRATION_LOCK_ID = 84729103829104
# 32-bit namespace for seed-level advisory locks
SEED_LOCK_NAMESPACE = 4242001

# Known slice categories and domain enums
GROUP_LABELS = {
    "independent_urban",
    "independent_rural",
    "assisted_allowance",
    "assisted_family",
}
GENDERS = {"female", "male", "other"}
AGE_BANDS = {"18-25", "26-40", "41-60", "60+"}
REGIONS = {
    "dhaka",
    "chittagong",
    "rajshahi",
    "khulna",
    "barishal",
    "sylhet",
    "rangpur",
    "mymensingh",
}
URBAN_RURAL = {"urban", "rural"}
AGENT_TYPES = {"normal", "high_volume_honest", "skimmer"}
VOLUME_BANDS = {"low", "medium", "high", "standard"}
TXN_TYPES = {"credit", "cash_out", "send", "bill_pay"}
CREDIT_SOURCES = {"allowance", "remittance", "salary", "add_money"}
CHANNELS = {"app", "ussd", "agent_initiated"}

USER_ID_REGEX = re.compile(r"^U_[0-9_]+$")
AGENT_ID_REGEX = re.compile(r"^A_[0-9_]+$")

USER_ALLOWED_COLUMNS = {
    "user_id",
    "group_label",
    "gender",
    "age_band",
    "region",
    "urban_rural",
    "created_at",
}
USER_REQUIRED_COLUMNS = {
    "user_id",
    "group_label",
    "gender",
    "age_band",
    "region",
    "urban_rural",
}

AGENT_ALLOWED_COLUMNS = {
    "agent_id",
    "region",
    "volume_band",
    "agent_type",
    "created_at",
}
AGENT_REQUIRED_COLUMNS = {"agent_id", "region", "volume_band", "agent_type"}

TRANSACTION_ALLOWED_COLUMNS = {
    "txn_id",
    "user_id",
    "agent_id",
    "txn_type",
    "credit_source",
    "amount",
    "fee",
    "balance_after",
    "channel",
    "ts",
}
TRANSACTION_REQUIRED_COLUMNS = {"txn_id", "user_id", "txn_type", "amount", "ts"}

SESSION_ALLOWED_COLUMNS = {
    "session_id",
    "user_id",
    "txn_id",
    "pin_retries",
    "pin_entry_ms",
    "steps",
    "ts",
}
SESSION_REQUIRED_COLUMNS = {"session_id", "user_id", "ts"}


class DatabaseError(Exception):
    """Base exception for data layer errors."""


class MigrationError(DatabaseError):
    """Raised when migration fails or checksum verification fails."""


class ValidationError(DatabaseError):
    """Raised when seed dataset format or integrity validation fails."""


class SeedCollisionError(DatabaseError):
    """Raised when seed dataset collisions or modified reseed is detected."""


def sanitize_database_url(url: str | None) -> str:
    """Return database URL with credentials redacted. Never prints passwords."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme:
            netloc = parsed.netloc
            if parsed.password:
                user = parsed.username or ""
                host = parsed.hostname or ""
                netloc = f"{user}:***@{host}"
                if parsed.port:
                    netloc += f":{parsed.port}"
            elif parsed.username:
                user = parsed.username
                host = parsed.hostname or ""
                netloc = f"{user}@{host}"
                if parsed.port:
                    netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit(
                (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
            )
    except Exception:
        pass
    sanitized = re.sub(r"password=([^\s]+)", "password=***", url)
    sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", sanitized)
    return sanitized


def get_migrations_dir() -> Path:
    """Find migrations directory supporting source repo and Docker runtime."""
    env_dir = os.environ.get("MIGRATIONS_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
        raise FileNotFoundError(
            f"MIGRATIONS_DIR path does not exist: {env_dir}"
        )

    candidates = [
        Path(__file__).resolve().parent.parent.parent / "migrations",
        Path.cwd() / "backend" / "migrations",
        Path.cwd() / "migrations",
        Path(__file__).resolve().parent.parent.parent.parent / "backend" / "migrations",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    searched = [str(c) for c in candidates]
    raise FileNotFoundError(
        f"Migrations directory not found. Searched locations: {searched}"
    )


def get_connection(db_url: str, schema: str | None = None):
    """Establish database connection with optional schema/search_path."""
    if not db_url:
        raise ValueError("Database URL must be provided.")
    if psycopg is None:
        raise ImportError(
            "psycopg is not installed. Please install psycopg[binary]>=3.2,<4."
        )
    conn = psycopg.connect(db_url, autocommit=True)
    if schema:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", schema):
            conn.close()
            raise ValueError(f"Invalid schema name: {schema}")
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
            cur.execute(f"SET search_path TO {schema};")
        conn.commit()
    return conn


def run_migrations(
    db_url: str,
    migrations_dir: Path | str | None = None,
    schema: str | None = None,
) -> list[str]:
    """Transactionally apply migrations with checksum check and advisory lock.

    Never drops, resets, or truncates existing tables.
    Concurrent and retry migrations are safe via pg_advisory_lock.
    """
    if not db_url:
        raise ValueError("Database URL must be provided.")

    mig_dir = Path(migrations_dir) if migrations_dir else get_migrations_dir()
    if not mig_dir.is_dir():
        raise FileNotFoundError(f"Migrations directory not found: {mig_dir}")

    migration_files = sorted(mig_dir.glob("*.sql"))
    if not migration_files:
        raise FileNotFoundError(f"No SQL migration files found in {mig_dir}")

    conn = get_connection(db_url, schema=schema)
    applied_versions: list[str] = []

    try:
        # Acquire advisory lock for migrations (waits if another runner is active)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s);", (MIGRATION_LOCK_ID,))
        conn.commit()

        try:
            # Ensure schema_migrations metadata table exists
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            version TEXT PRIMARY KEY,
                            checksum TEXT NOT NULL,
                            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )

            # Query existing migration versions and checksums
            with conn.cursor() as cur:
                cur.execute("SELECT version, checksum FROM schema_migrations;")
                existing_records = dict(cur.fetchall())

            for mig_file in migration_files:
                version = mig_file.name
                content = mig_file.read_text(encoding="utf-8")
                checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

                if version in existing_records:
                    recorded_checksum = existing_records[version]
                    if recorded_checksum != checksum:
                        raise MigrationError(
                            f"Migration '{version}' checksum mismatch: "
                            f"recorded '{recorded_checksum}', "
                            f"file has '{checksum}'. "
                            "Modified migration reuse is prevented."
                        )
                    # Previously applied with identical checksum; skip
                    continue

                # Transactionally apply migration and record metadata
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(content)
                        cur.execute(
                            """
                            INSERT INTO schema_migrations (version, checksum, applied_at)
                            VALUES (%s, %s, now());
                            """,
                            (version, checksum),
                        )
                applied_versions.append(version)

        finally:
            # Safely release advisory lock
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_unlock(%s);", (MIGRATION_LOCK_ID,)
                    )
                conn.commit()
            except Exception:
                pass
    finally:
        conn.close()

    return applied_versions


def compute_dataset_checksum(data: dict[str, Any]) -> str:
    """Compute canonical SHA256 checksum of dataset for provenance tracking."""
    canonical_json = json.dumps(
        data, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()


def _parse_iso_ts(val: Any) -> datetime:
    """Parse and validate ISO 8601 timestamp string or datetime object."""
    if isinstance(val, datetime):
        return val
    if not isinstance(val, str):
        raise ValidationError(
            f"Timestamp must be string or datetime, got {type(val)}"
        )
    try:
        parsed = datetime.fromisoformat(val)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValidationError("Timestamp must include timezone")
        return parsed
    except Exception as exc:
        raise ValidationError(
            f"Invalid ISO 8601 timestamp '{val}': {exc}"
        ) from exc


def _validate_decimal(val: Any, name: str, allow_zero: bool = False) -> None:
    """Validate numeric amounts, disallowing booleans and invalid numbers."""
    if isinstance(val, bool):
        raise ValidationError(f"{name} cannot be a boolean")
    if not isinstance(val, (int, float, Decimal, str)):
        raise ValidationError(f"{name} must be a number, got {type(val)}")
    try:
        d = Decimal(str(val))
    except Exception as exc:
        raise ValidationError(f"Invalid number for {name}: {val}") from exc
    if not d.is_finite() or abs(d) >= Decimal("10000000000"):
        raise ValidationError(f"{name} must be finite and fit NUMERIC(12,2)")
    if d != d.quantize(Decimal("0.01")):
        raise ValidationError(f"{name} must have at most two decimal places")
    if allow_zero:
        if d < 0:
            raise ValidationError(f"{name} must be >= 0, got {val}")
    else:
        if d <= 0:
            raise ValidationError(f"{name} must be > 0, got {val}")


def validate_dataset(data: dict[str, Any]) -> None:
    """Pure validation function for dataset structure, types, and relations.

    Prohibits real-looking free-text fields.
    Validates synthetic ID prefixes (U_, A_) and known enum/slice categories.
    Verifies transactional relations and relational consistency.
    Rejects malformed data before any database mutation.
    """
    if not isinstance(data, dict):
        raise ValidationError(
            f"Dataset must be a JSON object (dict), got {type(data)}"
        )

    expected_keys = {
        "schema_version",
        "synthetic",
        "seed",
        "users",
        "agents",
        "transactions",
        "sessions",
    }
    actual_keys = set(data.keys())
    if actual_keys != expected_keys:
        unknown = actual_keys - expected_keys
        missing = expected_keys - actual_keys
        errs = []
        if unknown:
            errs.append(f"unknown keys: {sorted(unknown)}")
        if missing:
            errs.append(f"missing keys: {sorted(missing)}")
        raise ValidationError(
            f"Invalid dataset top-level structure: {', '.join(errs)}"
        )

    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError(
            f"schema_version must be integer 1, got {data['schema_version']!r}"
        )

    if type(data["synthetic"]) is not bool or data["synthetic"] is not True:
        raise ValidationError(
            f"synthetic must be boolean True, got {data['synthetic']!r}"
        )

    if type(data["seed"]) is not int or isinstance(data["seed"], bool):
        raise ValidationError(f"seed must be an integer, got {type(data['seed'])}")

    if not 0 <= data["seed"] < 2**31:
        raise ValidationError("seed must be a nonnegative 31-bit integer")

    for list_name in ("users", "agents", "transactions", "sessions"):
        if not isinstance(data[list_name], list):
            raise ValidationError(
                f"{list_name} must be a list, got {type(data[list_name])}"
            )

    # Validate Users
    user_ids: set[str] = set()
    for idx, u in enumerate(data["users"]):
        if not isinstance(u, dict):
            raise ValidationError(f"users[{idx}] must be a dict")
        u_keys = set(u.keys())
        unknown_u = u_keys - USER_ALLOWED_COLUMNS
        if unknown_u:
            raise ValidationError(
                f"users[{idx}] contains unknown fields: {sorted(unknown_u)}"
            )
        missing_u = USER_REQUIRED_COLUMNS - u_keys
        if missing_u:
            raise ValidationError(
                f"users[{idx}] missing required fields: {sorted(missing_u)}"
            )

        uid = u["user_id"]
        if not isinstance(uid, str) or not USER_ID_REGEX.match(uid):
            raise ValidationError(
                f"users[{idx}] invalid user_id '{uid}': "
                "must be non-empty string starting with 'U_'"
            )
        if uid in user_ids:
            raise ValidationError(f"Duplicate user_id in dataset: '{uid}'")
        user_ids.add(uid)

        if u["group_label"] not in GROUP_LABELS:
            raise ValidationError(
                f"users[{idx}] invalid group_label '{u['group_label']}': "
                f"must be in {sorted(GROUP_LABELS)}"
            )
        if u["gender"] not in GENDERS:
            raise ValidationError(
                f"users[{idx}] invalid gender '{u['gender']}': "
                f"must be in {sorted(GENDERS)}"
            )
        if u["age_band"] not in AGE_BANDS:
            raise ValidationError(
                f"users[{idx}] invalid age_band '{u['age_band']}': "
                f"must be in {sorted(AGE_BANDS)}"
            )
        if u["region"] not in REGIONS:
            raise ValidationError(
                f"users[{idx}] invalid region '{u['region']}': "
                f"must be in {sorted(REGIONS)}"
            )
        if u["urban_rural"] not in URBAN_RURAL:
            raise ValidationError(
                f"users[{idx}] invalid urban_rural '{u['urban_rural']}': "
                f"must be in {sorted(URBAN_RURAL)}"
            )
        if "created_at" in u and u["created_at"] is not None:
            _parse_iso_ts(u["created_at"])

    # Validate Agents
    agent_ids: set[str] = set()
    for idx, a in enumerate(data["agents"]):
        if not isinstance(a, dict):
            raise ValidationError(f"agents[{idx}] must be a dict")
        a_keys = set(a.keys())
        unknown_a = a_keys - AGENT_ALLOWED_COLUMNS
        if unknown_a:
            raise ValidationError(
                f"agents[{idx}] contains unknown fields: {sorted(unknown_a)}"
            )
        missing_a = AGENT_REQUIRED_COLUMNS - a_keys
        if missing_a:
            raise ValidationError(
                f"agents[{idx}] missing required fields: {sorted(missing_a)}"
            )

        aid = a["agent_id"]
        if not isinstance(aid, str) or not AGENT_ID_REGEX.match(aid):
            raise ValidationError(
                f"agents[{idx}] invalid agent_id '{aid}': "
                "must be non-empty string starting with 'A_'"
            )
        if aid in agent_ids:
            raise ValidationError(f"Duplicate agent_id in dataset: '{aid}'")
        agent_ids.add(aid)

        if a["region"] not in REGIONS:
            raise ValidationError(
                f"agents[{idx}] invalid region '{a['region']}': "
                f"must be in {sorted(REGIONS)}"
            )
        if a["volume_band"] not in VOLUME_BANDS:
            raise ValidationError(
                f"agents[{idx}] invalid volume_band '{a['volume_band']}': "
                f"must be in {sorted(VOLUME_BANDS)}"
            )
        if a["agent_type"] not in AGENT_TYPES:
            raise ValidationError(
                f"agents[{idx}] invalid agent_type '{a['agent_type']}': "
                f"must be in {sorted(AGENT_TYPES)}"
            )
        if "created_at" in a and a["created_at"] is not None:
            _parse_iso_ts(a["created_at"])

    # Validate Transactions
    txn_ids: set[int] = set()
    txn_user_map: dict[int, str] = {}
    for idx, t in enumerate(data["transactions"]):
        if not isinstance(t, dict):
            raise ValidationError(f"transactions[{idx}] must be a dict")
        t_keys = set(t.keys())
        unknown_t = t_keys - TRANSACTION_ALLOWED_COLUMNS
        if unknown_t:
            raise ValidationError(
                f"transactions[{idx}] contains unknown fields: {sorted(unknown_t)}"
            )
        missing_t = TRANSACTION_REQUIRED_COLUMNS - t_keys
        if missing_t:
            raise ValidationError(
                f"transactions[{idx}] missing required fields: {sorted(missing_t)}"
            )

        tid = t["txn_id"]
        if type(tid) is not int or isinstance(tid, bool) or not 0 < tid < 2**63:
            raise ValidationError(
                f"transactions[{idx}] invalid txn_id '{tid}': "
                "must be positive integer"
            )
        if tid in txn_ids:
            raise ValidationError(f"Duplicate txn_id in dataset: {tid}")
        txn_ids.add(tid)

        uid = t["user_id"]
        if uid not in user_ids:
            raise ValidationError(
                f"transactions[{idx}] user_id '{uid}' does not exist "
                "in users list (missing foreign key)"
            )
        txn_user_map[tid] = uid

        aid = t.get("agent_id")
        if aid is not None:
            if not isinstance(aid, str) or aid not in agent_ids:
                raise ValidationError(
                    f"transactions[{idx}] agent_id '{aid}' does not exist "
                    "in agents list (missing foreign key)"
                )

        ttype = t["txn_type"]
        if ttype not in TXN_TYPES:
            raise ValidationError(
                f"transactions[{idx}] invalid txn_type '{ttype}': "
                f"must be in {sorted(TXN_TYPES)}"
            )

        csource = t.get("credit_source")
        if ttype == "credit":
            if csource not in CREDIT_SOURCES:
                raise ValidationError(
                    f"transactions[{idx}] credit transaction must have credit_source "
                    f"in {sorted(CREDIT_SOURCES)}, got '{csource}'"
                )
        else:
            if csource is not None:
                raise ValidationError(
                    f"transactions[{idx}] non-credit transaction has credit_source "
                    f"'{csource}'; must be null"
                )

        _validate_decimal(
            t["amount"], f"transactions[{idx}].amount", allow_zero=False
        )
        if "fee" in t and t["fee"] is not None:
            _validate_decimal(
                t["fee"], f"transactions[{idx}].fee", allow_zero=True
            )
        if "balance_after" in t and t["balance_after"] is not None:
            _validate_decimal(
                t["balance_after"],
                f"transactions[{idx}].balance_after",
                allow_zero=True,
            )

        channel = t.get("channel")
        if channel is not None and channel not in CHANNELS:
            raise ValidationError(
                f"transactions[{idx}] invalid channel '{channel}': "
                f"must be in {sorted(CHANNELS)}"
            )

        _parse_iso_ts(t["ts"])

    # Validate Sessions
    session_ids: set[int] = set()
    for idx, s in enumerate(data["sessions"]):
        if not isinstance(s, dict):
            raise ValidationError(f"sessions[{idx}] must be a dict")
        s_keys = set(s.keys())
        unknown_s = s_keys - SESSION_ALLOWED_COLUMNS
        if unknown_s:
            raise ValidationError(
                f"sessions[{idx}] contains unknown fields: {sorted(unknown_s)}"
            )
        missing_s = SESSION_REQUIRED_COLUMNS - s_keys
        if missing_s:
            raise ValidationError(
                f"sessions[{idx}] missing required fields: {sorted(missing_s)}"
            )

        sid = s["session_id"]
        if type(sid) is not int or isinstance(sid, bool) or not 0 < sid < 2**63:
            raise ValidationError(
                f"sessions[{idx}] invalid session_id '{sid}': "
                "must be positive integer"
            )
        if sid in session_ids:
            raise ValidationError(f"Duplicate session_id in dataset: {sid}")
        session_ids.add(sid)

        uid = s["user_id"]
        if uid not in user_ids:
            raise ValidationError(
                f"sessions[{idx}] user_id '{uid}' does not exist "
                "in users list (missing foreign key)"
            )

        stid = s.get("txn_id")
        if stid is not None:
            if type(stid) is not int or isinstance(stid, bool):
                raise ValidationError(
                    f"sessions[{idx}] txn_id must be an integer, got {type(stid)}"
                )
            if stid not in txn_ids:
                raise ValidationError(
                    f"sessions[{idx}] txn_id {stid} does not exist "
                    "in transactions list (missing foreign key)"
                )
            if txn_user_map[stid] != uid:
                raise ValidationError(
                    f"sessions[{idx}] references txn_id {stid} belonging to "
                    f"user '{txn_user_map[stid]}', but session user_id is '{uid}' "
                    "(inconsistent relations)"
                )

        if "pin_retries" in s and s["pin_retries"] is not None:
            pr = s["pin_retries"]
            if type(pr) is not int or isinstance(pr, bool) or pr < 0:
                raise ValidationError(
                    f"sessions[{idx}] pin_retries must be non-negative int, "
                    f"got {pr!r}"
                )

        if "pin_entry_ms" in s and s["pin_entry_ms"] is not None:
            pms = s["pin_entry_ms"]
            if type(pms) is not int or isinstance(pms, bool) or pms < 0:
                raise ValidationError(
                    f"sessions[{idx}] pin_entry_ms must be non-negative int, "
                    f"got {pms!r}"
                )

        if "steps" in s and s["steps"] is not None:
            st = s["steps"]
            if type(st) is not int or isinstance(st, bool) or st < 0:
                raise ValidationError(
                    f"sessions[{idx}] steps must be non-negative int, "
                    f"got {st!r}"
                )

        _parse_iso_ts(s["ts"])


def load_seed(
    db_url: str,
    dataset: dict[str, Any] | Path | str,
    schema: str | None = None,
) -> dict[str, Any]:
    """Load validated synthetic seed dataset into database.

    - Validates dataset shape and content before mutation.
    - Transactional all-or-nothing insertion.
    - Repeated exact dataset is a safe no-op.
    - Changed dataset or ID collisions are rejected without overwriting.
    - Safe sequence setval preserves max explicit IDs after successful insert.
    - No mandate rows seeded.
    """
    if isinstance(dataset, (str, Path)):
        p = Path(dataset)
        if not p.is_file():
            raise FileNotFoundError(f"Dataset file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = dataset

    # Pure validation: reject malformed before touching database
    validate_dataset(data)

    checksum = compute_dataset_checksum(data)
    seed = data["seed"]

    counts = {
        "users": len(data["users"]),
        "agents": len(data["agents"]),
        "transactions": len(data["transactions"]),
        "sessions": len(data["sessions"]),
    }

    conn = get_connection(db_url, schema=schema)
    try:
        # Acquire advisory lock keyed to this dataset seed
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_lock(%s, %s);",
                (SEED_LOCK_NAMESPACE, 0),
            )
        conn.commit()

        try:
            # Ensure dataset_metadata table exists
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS dataset_metadata (
                            seed BIGINT PRIMARY KEY,
                            checksum TEXT NOT NULL,
                            record_counts JSONB NOT NULL,
                            loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        );
                        """
                    )

            # Check if this seed is already loaded
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT checksum, record_counts FROM dataset_metadata WHERE seed = %s;",
                    (seed,),
                )
                existing = cur.fetchone()

            if existing is not None:
                existing_checksum, existing_counts = existing
                if existing_checksum == checksum:
                    # Repeated exact dataset is a no-op
                    return {
                        "status": "noop",
                        "seed": seed,
                        "checksum": checksum,
                        "message": (
                            f"Dataset for seed {seed} already loaded "
                            "with matching checksum. No-op."
                        ),
                        "counts": existing_counts,
                    }
                else:
                    raise SeedCollisionError(
                        f"Dataset for seed {seed} already exists with checksum "
                        f"'{existing_checksum}', but new dataset has checksum '{checksum}'. "
                        "Overwriting or reseeding modified data is rejected."
                    )

            # Check for ID collisions against existing tables
            u_ids = [u["user_id"] for u in data["users"]]
            a_ids = [a["agent_id"] for a in data["agents"]]
            t_ids = [t["txn_id"] for t in data["transactions"]]
            s_ids = [s["session_id"] for s in data["sessions"]]

            with conn.cursor() as cur:
                if u_ids:
                    cur.execute(
                        "SELECT user_id FROM users WHERE user_id = ANY(%s) LIMIT 1;",
                        (u_ids,),
                    )
                    hit = cur.fetchone()
                    if hit:
                        raise SeedCollisionError(
                            f"Collision: user_id '{hit[0]}' already exists in database."
                        )
                if a_ids:
                    cur.execute(
                        "SELECT agent_id FROM agents WHERE agent_id = ANY(%s) LIMIT 1;",
                        (a_ids,),
                    )
                    hit = cur.fetchone()
                    if hit:
                        raise SeedCollisionError(
                            f"Collision: agent_id '{hit[0]}' already exists in database."
                        )
                if t_ids:
                    cur.execute(
                        "SELECT txn_id FROM transactions WHERE txn_id = ANY(%s) LIMIT 1;",
                        (t_ids,),
                    )
                    hit = cur.fetchone()
                    if hit:
                        raise SeedCollisionError(
                            f"Collision: txn_id {hit[0]} already exists in database."
                        )
                if s_ids:
                    cur.execute(
                        "SELECT session_id FROM sessions WHERE session_id = ANY(%s) LIMIT 1;",
                        (s_ids,),
                    )
                    hit = cur.fetchone()
                    if hit:
                        raise SeedCollisionError(
                            f"Collision: session_id {hit[0]} already exists in database."
                        )

            # Transactional all-or-nothing insertion
            with conn.transaction():
                with conn.cursor() as cur:
                    # Insert users
                    if data["users"]:
                        user_rows = [
                            (
                                u["user_id"],
                                u["group_label"],
                                u["gender"],
                                u["age_band"],
                                u["region"],
                                u["urban_rural"],
                                u.get("created_at"),
                            )
                            for u in data["users"]
                        ]
                        cur.executemany(
                            """
                            INSERT INTO users (
                                user_id, group_label, gender, age_band,
                                region, urban_rural, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now()));
                            """,
                            user_rows,
                        )

                    # Insert agents
                    if data["agents"]:
                        agent_rows = [
                            (
                                a["agent_id"],
                                a["region"],
                                a["volume_band"],
                                a["agent_type"],
                                a.get("created_at"),
                            )
                            for a in data["agents"]
                        ]
                        cur.executemany(
                            """
                            INSERT INTO agents (
                                agent_id, region, volume_band, agent_type, created_at
                            ) VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, now()));
                            """,
                            agent_rows,
                        )

                    # Insert transactions
                    if data["transactions"]:
                        txn_rows = [
                            (
                                t["txn_id"],
                                t["user_id"],
                                t.get("agent_id"),
                                t["txn_type"],
                                t.get("credit_source"),
                                t["amount"],
                                t.get("fee", 0),
                                t.get("balance_after"),
                                t.get("channel"),
                                t["ts"],
                            )
                            for t in data["transactions"]
                        ]
                        cur.executemany(
                            """
                            INSERT INTO transactions (
                                txn_id, user_id, agent_id, txn_type, credit_source,
                                amount, fee, balance_after, channel, ts
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz);
                            """,
                            txn_rows,
                        )

                    # Insert sessions
                    if data["sessions"]:
                        session_rows = [
                            (
                                s["session_id"],
                                s["user_id"],
                                s.get("txn_id"),
                                s.get("pin_retries", 0),
                                s.get("pin_entry_ms"),
                                s.get("steps"),
                                s["ts"],
                            )
                            for s in data["sessions"]
                        ]
                        cur.executemany(
                            """
                            INSERT INTO sessions (
                                session_id, user_id, txn_id,
                                pin_retries, pin_entry_ms, steps, ts
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::timestamptz);
                            """,
                            session_rows,
                        )

                    # Insert dataset provenance record
                    cur.execute(
                        """
                        INSERT INTO dataset_metadata (seed, checksum, record_counts, loaded_at)
                        VALUES (%s, %s, %s::jsonb, now());
                        """,
                        (seed, checksum, json.dumps(counts)),
                    )

            # Update sequences preserving current max IDs safely (after successful commit)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DO $$
                    DECLARE
                        txn_seq TEXT;
                        sess_seq TEXT;
                        max_txn BIGINT;
                        max_sess BIGINT;
                    BEGIN
                        txn_seq := pg_get_serial_sequence('transactions', 'txn_id');
                        IF txn_seq IS NOT NULL THEN
                            SELECT MAX(txn_id) INTO max_txn FROM transactions;
                            IF max_txn IS NOT NULL THEN
                                PERFORM setval(txn_seq, max_txn, true);
                            END IF;
                        END IF;

                        sess_seq := pg_get_serial_sequence('sessions', 'session_id');
                        IF sess_seq IS NOT NULL THEN
                            SELECT MAX(session_id) INTO max_sess FROM sessions;
                            IF max_sess IS NOT NULL THEN
                                PERFORM setval(sess_seq, max_sess, true);
                            END IF;
                        END IF;
                    END $$;
                    """
                )
            conn.commit()

            return {
                "status": "loaded",
                "seed": seed,
                "checksum": checksum,
                "counts": counts,
            }

        finally:
            # Release advisory lock
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_unlock(%s, %s);",
                        (SEED_LOCK_NAMESPACE, 0),
                    )
                conn.commit()
            except Exception:
                pass
    finally:
        conn.close()
