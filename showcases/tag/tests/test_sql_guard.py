import pytest

import db
from sql_guard import (
    QueryTimeout,
    RowCapExceeded,
    SqlRejected,
    connect_readonly,
    validate_and_execute,
)


@pytest.fixture()
def conn(tmp_path):
    path = db.ensure_database(tmp_path / "guard.db")
    connection = connect_readonly(path)
    yield connection
    connection.close()


def test_accepts_plain_select(conn):
    columns, rows = validate_and_execute(
        conn, "SELECT day, tier, est_cost_usd FROM daily_serving_metrics WHERE tier = 'gpu'", 200
    )
    assert columns == ["day", "tier", "est_cost_usd"]
    assert len(rows) == 30
    assert rows[0]["day"] == "2026-09-01"


def test_accepts_with_select(conn):
    sql = (
        "WITH ranked AS (SELECT day, est_cost_usd FROM daily_serving_metrics WHERE tier = 'gpu') "
        "SELECT day FROM ranked ORDER BY est_cost_usd DESC LIMIT 1"
    )
    columns, rows = validate_and_execute(conn, sql, 200)
    assert rows == [{"day": "2026-09-08"}]


def test_accepts_aggregates_and_join(conn):
    sql = (
        "SELECT m.day, count(n.note) AS notes FROM daily_serving_metrics m "
        "JOIN incident_notes n ON n.day = m.day AND n.tier = m.tier "
        "GROUP BY m.day ORDER BY m.day LIMIT 3"
    )
    columns, rows = validate_and_execute(conn, sql, 200)
    assert columns == ["day", "notes"]
    assert rows[0] == {"day": "2026-09-03", "notes": 1}


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO incident_notes VALUES ('2026-09-30', 'gpu', 'x', 'capacity')",
        "UPDATE incident_notes SET note = 'x'",
        "DELETE FROM incident_notes",
        "CREATE TABLE evil (a TEXT)",
        "DROP TABLE incident_notes",
        "ALTER TABLE incident_notes ADD COLUMN z TEXT",
        "PRAGMA table_info(incident_notes)",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        "VACUUM",
    ],
)
def test_rejects_non_select_statements(conn, statement):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, statement, 10)


def test_rejects_multiple_statements(conn):
    with pytest.raises(SqlRejected, match="one SELECT"):
        validate_and_execute(conn, "SELECT 1; SELECT 2", 10)


def test_rejects_comment_smuggled_write(conn):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, "SELECT 1; /* innocent */ DROP TABLE incident_notes", 10)


def test_rejects_comment_only_input(conn):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, "-- nothing here\n/* still nothing */", 10)


def test_rejects_leading_comment_then_write(conn):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, "-- looks like a query\nDELETE FROM incident_notes", 10)


def test_rejects_unknown_table(conn):
    with pytest.raises(SqlRejected, match="secret_billing"):
        validate_and_execute(conn, "SELECT * FROM secret_billing", 10)


def test_rejects_unknown_column(conn):
    with pytest.raises(SqlRejected, match="password"):
        validate_and_execute(conn, "SELECT password FROM daily_serving_metrics", 10)


def test_rejects_sqlite_master(conn):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, "SELECT name, sql FROM sqlite_master", 10)


def test_rejects_non_allowlisted_function(conn):
    with pytest.raises(SqlRejected, match="sqlite_version"):
        validate_and_execute(conn, "SELECT sqlite_version()", 10)


def test_row_cap_raises_instead_of_truncating(conn):
    with pytest.raises(RowCapExceeded, match="more than 5 rows"):
        validate_and_execute(conn, "SELECT * FROM daily_serving_metrics", 5)


def test_row_cap_boundary_is_exact(conn):
    columns, rows = validate_and_execute(
        conn, "SELECT day FROM incident_notes ORDER BY day", 12
    )
    assert len(rows) == 12


def test_heavy_query_times_out(conn):
    sql = (
        "WITH RECURSIVE cnt(x) AS ("
        "SELECT 1 UNION ALL SELECT x + 1 FROM cnt WHERE x < 5000000"
        ") SELECT sum(x) FROM cnt"
    )
    with pytest.raises(QueryTimeout, match="execution budget"):
        validate_and_execute(conn, sql, 10, opcode_budget=50_000)


def test_guard_does_not_poison_connection(conn):
    with pytest.raises(SqlRejected):
        validate_and_execute(conn, "DELETE FROM incident_notes", 10)
    columns, rows = validate_and_execute(conn, "SELECT count(*) AS n FROM incident_notes", 10)
    assert rows == [{"n": 12}]


def test_returns_rows_as_dicts(conn):
    columns, rows = validate_and_execute(
        conn,
        "SELECT day, category FROM incident_notes WHERE day = '2026-09-17'",
        10,
    )
    assert rows == [{"day": "2026-09-17", "category": "capacity"}]
