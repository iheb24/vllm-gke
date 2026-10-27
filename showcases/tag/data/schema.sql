CREATE TABLE IF NOT EXISTS daily_serving_metrics (
    day TEXT NOT NULL,
    tier TEXT NOT NULL,
    model TEXT NOT NULL,
    requests INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    gpu_minutes INTEGER NOT NULL,
    est_cost_usd REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS incident_notes (
    day TEXT NOT NULL,
    tier TEXT NOT NULL,
    note TEXT NOT NULL,
    category TEXT NOT NULL
);
