import sqlite3

import db


def _query(db_path, sql):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_ensure_database_is_deterministic(tmp_path):
    first = db.ensure_database(tmp_path / "a.db")
    second = db.ensure_database(tmp_path / "b.db")
    dump_a = _query(first, "SELECT * FROM daily_serving_metrics ORDER BY day, tier")
    dump_b = _query(second, "SELECT * FROM daily_serving_metrics ORDER BY day, tier")
    assert dump_a == dump_b
    assert len(dump_a) == 60
    notes_a = _query(first, "SELECT * FROM incident_notes ORDER BY day")
    assert notes_a == _query(second, "SELECT * FROM incident_notes ORDER BY day")
    assert len(notes_a) == 12


def test_ensure_database_is_idempotent(tmp_path):
    path = db.ensure_database(tmp_path / "c.db")
    before = _query(path, "SELECT count(*) FROM daily_serving_metrics")
    db.ensure_database(path)
    db.ensure_database(path)
    assert _query(path, "SELECT count(*) FROM daily_serving_metrics") == before


def test_schema_and_window(tmp_path):
    path = db.ensure_database(tmp_path / "d.db")
    rows = _query(path, "SELECT min(day), max(day), count(DISTINCT day) FROM daily_serving_metrics")
    assert rows == [("2026-09-01", "2026-09-30", 30)]
    models = _query(path, "SELECT tier, model, count(*) FROM daily_serving_metrics GROUP BY tier ORDER BY tier")
    assert models == [
        ("cpu", "qwen3-4b-cpu", 30),
        ("gpu", "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ", 30),
    ]


def test_top3_gpu_cost_days(tmp_path):
    path = db.ensure_database(tmp_path / "e.db")
    rows = _query(
        path,
        "SELECT day, printf('%.2f', est_cost_usd), requests, gpu_minutes "
        "FROM daily_serving_metrics WHERE tier = 'gpu' "
        "ORDER BY est_cost_usd DESC LIMIT 3",
    )
    assert rows == [
        ("2026-09-08", "28.40", 512, 588),
        ("2026-09-17", "25.10", 463, 520),
        ("2026-09-24", "22.75", 438, 471),
    ]
    rest = _query(
        path,
        "SELECT printf('%.2f', max(est_cost_usd)) FROM daily_serving_metrics "
        "WHERE tier = 'gpu' AND day NOT IN ('2026-09-08', '2026-09-17', '2026-09-24')",
    )
    assert rest == [("11.76",)]


def test_september_totals(tmp_path):
    path = db.ensure_database(tmp_path / "f.db")
    rows = _query(
        path,
        "SELECT tier, sum(requests), sum(gpu_minutes), sum(est_cost_usd), "
        "avg(est_cost_usd), avg(requests) "
        "FROM daily_serving_metrics GROUP BY tier ORDER BY tier",
    )
    expected = [
        ("cpu", 14909, 0, 57.45, 1.915, 496.97),
        ("gpu", 6650, 5218, 324.80, 10.827, 221.67),
    ]
    assert len(rows) == len(expected)
    for row, want in zip(rows, expected):
        assert row[0] == want[0]
        assert row[1] == want[1]
        assert row[2] == want[2]
        assert abs(row[3] - want[3]) < 0.005
        assert abs(row[4] - want[4]) < 0.005
        assert abs(row[5] - want[5]) < 0.005
    total = _query(path, "SELECT sum(est_cost_usd) FROM daily_serving_metrics")
    assert abs(total[0][0] - 382.25) < 0.005


def test_incident_note_categories(tmp_path):
    path = db.ensure_database(tmp_path / "g.db")
    rows = _query(
        path,
        "SELECT category, count(*) FROM incident_notes GROUP BY category ORDER BY category",
    )
    assert rows == [("capacity", 5), ("configuration", 3), ("network", 2), ("ux", 2)]


def test_spike_day_notes_match_flagship_ground_truth(tmp_path):
    path = db.ensure_database(tmp_path / "h.db")
    rows = _query(
        path,
        "SELECT day, category FROM incident_notes "
        "WHERE day IN ('2026-09-08', '2026-09-17', '2026-09-24') ORDER BY day",
    )
    assert rows == [
        ("2026-09-08", "configuration"),
        ("2026-09-17", "capacity"),
        ("2026-09-24", "capacity"),
    ]
    capacity = sum(1 for _, c in rows if c == "capacity")
    assert capacity == 2
