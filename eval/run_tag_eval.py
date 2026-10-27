#!/usr/bin/env python3
"""Run the TAG showcase question set against a running demo and score it.

Question types:
- exact: every expected substring must appear in the answer (deterministic
  data, so any failure here is a real regression and exits non-zero).
- semantic: rubric items that a correct answer should mention; reported
  per rubric item, no gate yet while the baseline is established.
- invalid: questions tempting writes; passes when the request is rejected
  (error present), no SQL ran, or the answer refuses.
- out_of_scope: passes when no SQL was executed (evidence.sql empty).

Usage: python eval/run_tag_eval.py [--url http://localhost:8091] \
           [--questions eval/showcases/tag_questions.yaml] \
           [--report eval/reports/<date>.md] [--note "context line"]
"""

import argparse
import datetime
import os

import requests
import yaml

REFUSAL_MARKERS = (
    "cannot",
    "not allowed",
    "read-only",
    "rejected",
    "refuse",
    "not answerable",
)


def load_questions(path):
    with open(path) as f:
        return yaml.safe_load(f)["questions"]


def ask(url, question):
    resp = requests.post(f"{url}/chat", json={"question": question}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def score(question, result):
    qtype = question["type"]
    answer = (result.get("answer") or "").lower()
    sql = (result.get("evidence") or {}).get("sql")
    if qtype == "exact":
        missing = [s for s in question["expect_in_answer"] if s.lower() not in answer]
        return result.get("answer") is not None and not missing, {"missing": missing}
    if qtype == "semantic":
        rubric = [
            {"item": item, "mentioned": item.lower() in answer}
            for item in question["rubric"]
        ]
        return all(r["mentioned"] for r in rubric), {"rubric": rubric}
    if qtype == "invalid":
        refused = any(marker in answer for marker in REFUSAL_MARKERS)
        return bool(result.get("error")) or not sql or refused, {
            "error": result.get("error", {}).get("type"),
            "sql_executed": bool(sql),
        }
    if qtype == "out_of_scope":
        return not sql, {"sql_executed": bool(sql)}
    raise ValueError(f"unknown question type: {qtype}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8091")
    parser.add_argument("--questions", default="eval/showcases/tag_questions.yaml")
    parser.add_argument("--report")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    results = []
    for q in questions:
        try:
            response = ask(args.url, q["question"])
            passed, detail = score(q, response)
        except Exception as exc:
            response, passed, detail = None, False, {"transport_error": str(exc)}
        results.append({"question": q, "response": response, "passed": passed, "detail": detail})

    by_type = {}
    for r in results:
        bucket = by_type.setdefault(r["question"]["type"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += r["passed"]

    exact_failed = [
        r for r in results if r["question"]["type"] == "exact" and not r["passed"]
    ]

    lines = [
        f"# TAG eval — {datetime.date.today().isoformat()}",
        "",
    ]
    if args.note:
        lines += [f"> {args.note}", ""]
    lines += [
        f"url: {args.url}  ",
        f"questions: {len(results)} ({', '.join(f'{t} {b['passed']}/{b['total']}' for t, b in sorted(by_type.items()))})",
        "",
        "| type | passed | total |",
        "| --- | --- | --- |",
    ]
    for qtype, bucket in sorted(by_type.items()):
        lines.append(f"| {qtype} | {bucket['passed']} | {bucket['total']} |")
    lines += [
        "",
        "No pass threshold is set yet: this run establishes the baseline. "
        "Only `exact` failures fail the run, since their expected values are "
        "deterministic.",
        "",
        "## Per-question results",
        "",
    ]
    for r in results:
        q = r["question"]
        verdict = "PASS" if r["passed"] else "FAIL"
        lines.append(f"- [{verdict}] ({q['type']}) `{q['id']}`: {q['question']}")
        if r["question"]["type"] == "semantic":
            for item in r["detail"].get("rubric", []):
                mark = "x" if item["mentioned"] else " "
                lines.append(f"  - [{mark}] rubric: {item['item']}")
        if not r["passed"]:
            lines.append(f"  - detail: {r['detail']}")
            if r["response"] is not None:
                lines.append(f"  - answer: {(r['response'].get('answer') or '')[:300]}")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.report:
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, "w") as f:
            f.write(report)

    raise SystemExit(1 if exact_failed else 0)


if __name__ == "__main__":
    main()
