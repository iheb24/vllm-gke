"""Read-only SQL validation and bounded execution over the serving database.

The model writes SQL; this module decides what may run. Enforcement lives at
the SQLite engine level, not in regexes: a connection authorizer vets every
table, column, and function at prepare time, and a progress handler bounds
execution time. A statement that survives validation is executed read-only
and its result is capped, with overflow reported instead of truncated.

Layer summary:
1. first-keyword check - only SELECT / WITH after leading comments.
2. EXPLAIN with the authorizer set - fires the authorizer at prepare time
   without executing the statement.
3. execution with the authorizer still set, a progress handler opcode
   budget, a row cap, and an optional SQL-length limit.

All failures raise SqlRejected, RowCapExceeded, or QueryTimeout carrying
human-readable reasons that are safe to feed back to the model for a retry.
"""

import re
import sqlite3

ALLOWED_TABLES = {
    "daily_serving_metrics": {
        "day",
        "tier",
        "model",
        "requests",
        "prompt_tokens",
        "completion_tokens",
        "gpu_minutes",
        "est_cost_usd",
    },
    "incident_notes": {"day", "tier", "note", "category"},
}

ALLOWED_FUNCTIONS = {
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "total",
    "round",
    "abs",
    "coalesce",
    "ifnull",
    "length",
    "lower",
    "upper",
    "substr",
    "instr",
    "trim",
    "date",
    "time",
    "datetime",
    "julianday",
    "strftime",
    "printf",
    "group_concat",
    "like",
}

DEFAULT_OPCODE_BUDGET = 200_000
MAX_SQL_LENGTH = 10_000

_ACTION_NAMES = {
    value: name
    for name, value in vars(sqlite3).items()
    if name.startswith("SQLITE_") and isinstance(value, int)
}


class SqlRejected(Exception):
    """The statement is not a single read-only SELECT over allowlisted data."""


class RowCapExceeded(Exception):
    """The statement would return more rows than the configured cap."""


class QueryTimeout(Exception):
    """The statement exceeded its execution budget."""


def connect_readonly(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _first_keyword(sql):
    i, n = 0, len(sql)
    while i < n:
        if sql[i].isspace():
            i += 1
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end == -1 else end + 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                return None
            i = end + 2
        elif sql[i] == "'":
            return None
        else:
            break
    match = re.match(r"[A-Za-z]+", sql[i:])
    return match.group(0).upper() if match else None


def _make_authorizer(violations):
    def authorize(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            columns = ALLOWED_TABLES.get(arg1)
            if columns is None:
                violations.append(
                    f"table '{arg1}' is not allowed; only {sorted(ALLOWED_TABLES)} can be read"
                )
                return sqlite3.SQLITE_DENY
            if arg2 == "" or arg2 in columns:
                return sqlite3.SQLITE_OK
            violations.append(f"column '{arg1}.{arg2}' is not allowed")
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            name = (arg2 or "").lower()
            if name in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            violations.append(f"function '{name}' is not allowed")
            return sqlite3.SQLITE_DENY
        violations.append(
            f"operation {_ACTION_NAMES.get(action, action)} is not allowed; only read-only SELECT is"
        )
        return sqlite3.SQLITE_DENY

    return authorize


def _map_sqlite_error(exc, violations, opcode_budget):
    text = str(exc)
    if violations:
        return SqlRejected(violations[0])
    if "one statement" in text:
        return SqlRejected("multiple statements are not allowed; send one SELECT")
    if "interrupted" in text:
        return QueryTimeout(
            f"query exceeded the execution budget of {opcode_budget} opcodes; "
            "simplify it (smaller range, aggregation, or LIMIT)"
        )
    if "too large" in text:
        return SqlRejected(f"statement exceeds the {MAX_SQL_LENGTH}-character limit")
    return SqlRejected(f"SQL rejected: {text}")


def validate_and_execute(conn, sql, row_cap, opcode_budget=DEFAULT_OPCODE_BUDGET):
    text = (sql or "").strip()
    if not text:
        raise SqlRejected("empty query")
    keyword = _first_keyword(text)
    if keyword not in ("SELECT", "WITH"):
        raise SqlRejected(
            f"statement must start with SELECT or WITH, got {keyword or 'nothing parseable'}"
        )
    if hasattr(conn, "setlimit"):
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_LENGTH)
    violations = []
    conn.set_authorizer(_make_authorizer(violations))
    ticks = {"count": 0}
    step = 1000

    def progress():
        ticks["count"] += step
        return 1 if ticks["count"] > opcode_budget else 0

    conn.set_progress_handler(progress, step)
    try:
        try:
            conn.execute("EXPLAIN " + text)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc, violations, opcode_budget) from exc
        try:
            cursor = conn.execute(text)
            columns = [d[0] for d in cursor.description]
            raw = cursor.fetchmany(row_cap + 1)
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc, violations, opcode_budget) from exc
    finally:
        conn.set_progress_handler(None, 0)
        conn.set_authorizer(None)
    if len(raw) > row_cap:
        raise RowCapExceeded(
            f"query returned more than {row_cap} rows; narrow it with WHERE, "
            "aggregate it, or add a LIMIT"
        )
    rows = [dict(zip(columns, row)) for row in raw]
    return columns, rows
