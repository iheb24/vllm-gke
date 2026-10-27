"""Deterministic scripted model transport for local demos and tests.

make_fake_transport() returns a callable with the same signature as the real
HTTP transport, so GatewayClient runs unchanged with no network and no GPU.
The fake role-plays both pipeline stages: it pattern-matches the question
into plausible SQL for the synthesis stage, and for the answer stage it
composes text strictly from the JSON rows the pipeline executed, classifying
free-text incident notes with simple keyword rules. One pattern deliberately
emits invalid SQL first and fixed SQL on retry to exercise the repair loop.
Everything is deterministic: same question, same database, same answer.
"""

import json
import re

_CAPACITY_WORDS = ("oom", "quota", "backlog", "pending", "saturat", "throttl", "exhausted", "queue")
_CONFIGURATION_WORDS = ("misconfig", "mis-set", "cold start", "retry storm", "threshold", "config reload", "scaledown")
_NETWORK_WORDS = ("dns", "metadata server", "network", "upstream reset")
_UX_WORDS = ("chat ui", "stale", "users", "client-side", "user impact")


def _classify(note):
    text = note.lower()
    if any(w in text for w in _CAPACITY_WORDS):
        return "capacity"
    if any(w in text for w in _CONFIGURATION_WORDS):
        return "configuration"
    if any(w in text for w in _NETWORK_WORDS):
        return "network"
    if any(w in text for w in _UX_WORDS):
        return "ux"
    return "uncategorized"


def _fmt_value(key, value):
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _summarize_rows(rows):
    parts = []
    for row in rows:
        parts.append("(" + ", ".join(f"{k}={_fmt_value(k, v)}" for k, v in row.items()) + ")")
    return "; ".join(parts)


def _answer_from_rows(rows):
    if not rows:
        return (
            "The query returned no rows, so the database does not contain an "
            "answer to this question."
        )
    if any("note" in row for row in rows):
        classified = []
        counts = {}
        for row in rows:
            note = str(row.get("note", ""))
            label = _classify(note)
            counts[label] = counts.get(label, 0) + 1
            day = row.get("day", "?")
            cost = row.get("est_cost_usd")
            entry = f"{day} - {label}: \"{note}\""
            if cost is not None:
                entry = f"{day} (${float(cost):.2f}) - {label}: \"{note}\""
            classified.append(entry)
        dominant = max(counts, key=counts.get)
        head = ", ".join(
            f"{row['day']} (${float(row['est_cost_usd']):.2f})"
            for row in rows
            if "est_cost_usd" in row
        )
        prefix = f"The most expensive days in scope were {head}. " if head else ""
        total = sum(counts.values())
        return (
            f"{prefix}Classifying each incident note by its meaning: "
            + "; ".join(classified)
            + f". {counts[dominant]} of {total} point to {dominant}"
            + (", the rest to " + ", ".join(f"{v} {k}" for k, v in counts.items() if k != dominant) if len(counts) > 1 else "")
            + f" - so the notes point mainly to {dominant} problems."
        )
    return f"The query returned {len(rows)} row(s): {_summarize_rows(rows)}."


def _sql_for_question(question):
    q = question.lower()
    retry = "rejected with this error" in q

    if re.search(r"\b(delete|update|drop|create|insert|truncate|remove|wipe|alter)\b", q):
        if "update" in q or "set" in q:
            return "UPDATE daily_serving_metrics SET est_cost_usd = 1.0 WHERE day = '2026-09-08'"
        if "create" in q:
            return "CREATE TABLE backups AS SELECT * FROM incident_notes"
        return "DELETE FROM incident_notes"

    if "cost per request" in q:
        if retry:
            return (
                "SELECT day, round(est_cost_usd * 1.0 / requests, 4) AS cost_per_request "
                "FROM daily_serving_metrics WHERE tier = 'gpu' ORDER BY day"
            )
        return (
            "SELECT day, round(est_cost * 1.0 / requests, 4) AS cost_per_request "
            "FROM daily_serving_metrics WHERE tier = 'gpu' ORDER BY day"
        )

    if "most expensive" in q and ("capacity" in q or "configuration" in q or "incident" in q or "notes" in q):
        return (
            "SELECT m.day, m.est_cost_usd, n.note "
            "FROM daily_serving_metrics m "
            "JOIN incident_notes n ON n.day = m.day AND n.tier = m.tier "
            "WHERE m.tier = 'gpu' AND m.day IN ("
            "SELECT day FROM daily_serving_metrics WHERE tier = 'gpu' "
            "ORDER BY est_cost_usd DESC LIMIT 3) "
            "ORDER BY m.est_cost_usd DESC"
        )

    if "most expensive" in q or ("top" in q and "cost" in q):
        limit = 3
        numbers = re.search(r"(?:top\s+)?(\d+)\s+(?:most expensive|days)", q)
        if numbers:
            limit = int(numbers.group(1))
        return (
            "SELECT day, requests, gpu_minutes, est_cost_usd FROM daily_serving_metrics "
            f"WHERE tier = 'gpu' ORDER BY est_cost_usd DESC LIMIT {limit}"
        )

    dates = re.findall(r"2026-09-\d{2}", q)
    if dates and ("note" in q or "incident" in q or "happened" in q or "classify" in q):
        day_list = ", ".join(f"'{d}'" for d in sorted(set(dates)))
        return (
            f"SELECT day, tier, note FROM incident_notes WHERE day IN ({day_list}) "
            "ORDER BY day"
        )

    if dates and "gpu minute" in q:
        return (
            "SELECT day, gpu_minutes FROM daily_serving_metrics "
            f"WHERE tier = 'gpu' AND day = '{dates[0]}'"
        )

    if "average" in q and "cost" in q:
        return (
            "SELECT tier, round(avg(est_cost_usd), 2) AS avg_daily_cost_usd "
            "FROM daily_serving_metrics GROUP BY tier"
        )

    if "total" in q and "cost" in q:
        return (
            "SELECT tier, round(sum(est_cost_usd), 2) AS total_cost_usd "
            "FROM daily_serving_metrics GROUP BY tier"
        )

    if "average" in q and "request" in q:
        return (
            "SELECT tier, round(avg(requests), 1) AS avg_daily_requests "
            "FROM daily_serving_metrics GROUP BY tier"
        )

    if "busiest" in q:
        tier = "cpu" if "cpu" in q else "gpu"
        return (
            "SELECT day, requests FROM daily_serving_metrics "
            f"WHERE tier = '{tier}' ORDER BY requests DESC LIMIT 1"
        )

    if "how many" in q and "request" in q:
        return (
            "SELECT tier, sum(requests) AS total_requests FROM daily_serving_metrics "
            "GROUP BY tier"
        )

    if "how many" in q and ("note" in q or "incident" in q):
        return "SELECT count(*) AS note_count FROM incident_notes"

    over = re.search(r"(?:over|above|exceeded?|more than)\s*\$?\s*(\d+)", q)
    if over and "cost" in q:
        return (
            "SELECT day, tier, est_cost_usd FROM daily_serving_metrics "
            f"WHERE est_cost_usd > {over.group(1)} ORDER BY est_cost_usd DESC"
        )

    return "OUT_OF_SCOPE"


def make_fake_transport(db_path=None):
    def transport(base_url, api_key, payload):
        messages = payload["messages"]
        last_user = next(m for m in reversed(messages) if m["role"] == "user")
        if "Rows (JSON):" in last_user["content"]:
            rows_json = last_user["content"].split("Rows (JSON):", 1)[1].strip()
            content = _answer_from_rows(json.loads(rows_json))
        else:
            content = _sql_for_question(last_user["content"])
        prompt_tokens = sum(len(m["content"]) for m in messages) // 4
        completion_tokens = len(content) // 4
        return {
            "id": "fake-tag-0",
            "object": "chat.completion",
            "model": payload.get("model", "fake"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    return transport
