"""Three-stage Table-Augmented Generation pipeline over the serving database.

Stage 1 - query synthesis: the model translates the question into one
read-only SQLite SELECT (or answers OUT_OF_SCOPE).
Stage 2 - validation and execution: sql_guard vets the statement at the
SQLite engine level and runs it bounded; guard errors are fed back to the
model for a bounded number of retries, then the pipeline fails closed.
Stage 3 - answer generation: the model writes an answer grounded strictly
in the returned rows, classifying free-text incident notes by meaning.

This module is transport-agnostic: GatewayClient takes an injectable
transport callable so tests and demos can run a scripted fake model with no
network. It deliberately has no web-framework imports.
"""

import json
import time
from dataclasses import dataclass

import requests

from db import DEFAULT_DB_PATH, ensure_database
from sql_guard import (
    DEFAULT_OPCODE_BUDGET,
    QueryTimeout,
    RowCapExceeded,
    SqlRejected,
    connect_readonly,
    validate_and_execute,
)

METHOD = "table-augmented-generation"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"

SYNTHESIS_PROMPT = """You translate one natural-language question into exactly one SQLite SELECT statement over a synthetic serving-analytics database.

Schema:
CREATE TABLE daily_serving_metrics(day TEXT, tier TEXT, model TEXT, requests INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, gpu_minutes INTEGER, est_cost_usd REAL);
CREATE TABLE incident_notes(day TEXT, tier TEXT, note TEXT, category TEXT);

Rules:
- SQLite dialect. Reply with a single read-only SELECT (optionally WITH ... SELECT) and nothing else: no markdown fences, no commentary, no second statement.
- Only the tables and columns above exist. Anything else (including sqlite_master) is rejected.
- At most {row_cap} rows may come back; use WHERE, aggregates (COUNT, SUM, AVG, GROUP BY) and LIMIT to stay small.
- day values are ISO dates ('2026-09-08'); tier is 'gpu' or 'cpu'.
- incident_notes.note is free text; incident_notes.category is an internal label - never select it, never mention it.
- If the question cannot be answered from this database, reply exactly {sentinel} and nothing else.
"""

ANSWER_PROMPT = """You answer the question strictly from the SQL result rows below.

Rules:
- Ground every claim in the rows; outside knowledge is forbidden.
- Quote numbers exactly as they appear in the rows; never recompute, re-round, or invent values.
- When rows contain free-text notes and the question asks about causes, classify each note by its meaning (for example capacity vs configuration) and say which class dominates.
- If the rows are insufficient to answer, say so plainly instead of guessing.

Question: {question}

Validated SQL:
{sql}

Rows (JSON):
{rows}
"""

OUT_OF_SCOPE_ANSWER = (
    "This question is not answerable from the serving-analytics database, "
    "which only covers synthetic daily serving metrics and incident notes "
    "for September 2026."
)


class GatewayClient:
    def __init__(self, base_url, api_key=None, model=DEFAULT_MODEL, transport=None, on_response=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.transport = transport or self._http_transport
        self.on_response = on_response

    def _http_transport(self, base_url, api_key, payload):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.post(
            f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120
        )
        resp.raise_for_status()
        return resp.json()

    def chat(self, messages, temperature=0.0):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        start = time.perf_counter()
        body = self.transport(self.base_url, self.api_key, payload)
        duration = time.perf_counter() - start
        raw_usage = body.get("usage") or {}
        usage = {
            "prompt_tokens": raw_usage.get("prompt_tokens", 0),
            "completion_tokens": raw_usage.get("completion_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }
        if self.on_response:
            self.on_response(duration, usage)
        return body["choices"][0]["message"]["content"], usage


@dataclass
class TagConfig:
    gateway: GatewayClient
    db_path: str = str(DEFAULT_DB_PATH)
    row_cap: int = 200
    max_sql_attempts: int = 2
    opcode_budget: int = DEFAULT_OPCODE_BUDGET


def _strip_fences(text):
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _is_out_of_scope(text):
    return _strip_fences(text).rstrip(".;").strip().upper() == OUT_OF_SCOPE


class TagPipeline:
    def __init__(self, config: TagConfig):
        self.config = config
        ensure_database(config.db_path)

    def _timed_stage(self, stages, name, fn):
        start = time.perf_counter()
        result = fn()
        stages.append({"name": name, "duration_s": round(time.perf_counter() - start, 6)})
        return result

    def answer(self, question):
        cfg = self.config
        stages = []
        attempts = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def add_usage(u):
            for key in usage:
                usage[key] += u.get(key, 0)

        def result(answer, evidence, error=None):
            return {
                "method": METHOD,
                "answer": answer,
                "evidence": evidence,
                "trace": {
                    "stages": stages,
                    "sql_attempts": attempts,
                    "model": cfg.gateway.model,
                    "db_path": str(cfg.db_path),
                },
                "usage": usage,
                **({"error": error} if error else {}),
            }

        sql = None
        columns, rows = [], []
        feedback = None
        conn = connect_readonly(cfg.db_path)
        try:
            for attempt_no in range(1, cfg.max_sql_attempts + 1):
                user_content = question
                if feedback:
                    user_content += (
                        f"\n\nYour previous SQL was rejected with this error: {feedback}\n"
                        "Rewrite it as one valid read-only SELECT over the documented schema."
                    )
                messages = [
                    {
                        "role": "system",
                        "content": SYNTHESIS_PROMPT.format(
                            row_cap=cfg.row_cap, sentinel=OUT_OF_SCOPE
                        ),
                    },
                    {"role": "user", "content": user_content},
                ]
                content, call_usage = self._timed_stage(
                    stages, "query_synthesis", lambda: cfg.gateway.chat(messages)
                )
                add_usage(call_usage)
                candidate = _strip_fences(content)
                if _is_out_of_scope(candidate):
                    attempts.append(
                        {"attempt": attempt_no, "sql": None, "outcome": "out_of_scope"}
                    )
                    return result(
                        OUT_OF_SCOPE_ANSWER,
                        {"sql": None, "columns": [], "rows": [], "row_count": 0},
                    )

                def run_guard():
                    return validate_and_execute(
                        conn, candidate, cfg.row_cap, cfg.opcode_budget
                    )

                try:
                    columns, rows = self._timed_stage(stages, "sql_execution", run_guard)
                except (SqlRejected, RowCapExceeded, QueryTimeout) as exc:
                    attempts.append(
                        {
                            "attempt": attempt_no,
                            "sql": candidate,
                            "outcome": "rejected",
                            "error": str(exc),
                        }
                    )
                    feedback = str(exc)
                    continue
                attempts.append(
                    {"attempt": attempt_no, "sql": candidate, "outcome": "ok"}
                )
                sql = candidate
                break
        finally:
            conn.close()

        if sql is None:
            last_error = attempts[-1]["error"] if attempts else "no SQL produced"
            return result(
                None,
                {"sql": None, "columns": [], "rows": [], "row_count": 0},
                error={
                    "type": "sql_rejected",
                    "message": (
                        f"could not produce a valid read-only query in "
                        f"{cfg.max_sql_attempts} attempts; last error: {last_error}"
                    ),
                },
            )

        answer_messages = [
            {"role": "system", "content": "You are a careful data analyst."},
            {
                "role": "user",
                "content": ANSWER_PROMPT.format(
                    question=question, sql=sql, rows=json.dumps(rows, indent=2)
                ),
            },
        ]
        final, call_usage = self._timed_stage(
            stages, "answer_generation", lambda: cfg.gateway.chat(answer_messages)
        )
        add_usage(call_usage)
        return result(
            final.strip(),
            {"sql": sql, "columns": columns, "rows": rows, "row_count": len(rows)},
        )
