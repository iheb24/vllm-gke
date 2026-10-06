#!/usr/bin/env python3
"""Run the golden question set against the retrieval API and score retrieval.

Metrics: hit@1, hit@5 (fraction of questions whose expected source appears in
the top-1/top-5 results) and MRR (mean reciprocal rank of the first correct
chunk). Out-of-scope questions (expected_source: none) are reported separately.

Usage: python eval/run_eval.py [--url http://localhost:8090] \
           [--questions eval/golden_questions.yaml] [--report eval/reports/<date>.md]

Gate: hit@5 >= 0.90 and MRR >= 0.75 on the in-scope questions.
"""

import argparse
import datetime
import os

import requests
import yaml

HIT_AT_5_GATE = 0.90
MRR_GATE = 0.75


def load_questions(path):
    with open(path) as f:
        return yaml.safe_load(f)["questions"]


def search(url, query, k=5):
    resp = requests.post(f"{url}/search", json={"query": query, "k": k}, timeout=60)
    resp.raise_for_status()
    return resp.json()["results"]


def first_rank(results, expected_source):
    for i, r in enumerate(results, start=1):
        if expected_source in r["source"]:
            return i
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8090")
    parser.add_argument("--questions", default="eval/golden_questions.yaml")
    parser.add_argument("--report")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    in_scope = [q for q in questions if q["expected_source"] != "none"]
    out_of_scope = [q for q in questions if q["expected_source"] == "none"]

    rows = []
    hits1 = hits5 = 0
    rr_total = 0.0
    for q in in_scope:
        results = search(args.url, q["question"])
        rank = first_rank(results, q["expected_source"])
        hits1 += rank == 1
        hits5 += rank is not None
        rr_total += 1.0 / rank if rank else 0.0
        rows.append((q["question"], q["expected_source"], rank))

    n = len(in_scope)
    hit1 = hits1 / n
    hit5 = hits5 / n
    mrr = rr_total / n

    oos_rows = []
    for q in out_of_scope:
        results = search(args.url, q["question"])
        top = results[0]["score"] if results else 0.0
        oos_rows.append((q["question"], top))

    passed = hit5 >= HIT_AT_5_GATE and mrr >= MRR_GATE

    lines = [
        f"# Retrieval eval — {datetime.date.today().isoformat()}",
        "",
        f"questions: {n} in-scope, {len(out_of_scope)} out-of-scope",
        "",
        f"| metric | value | gate |",
        f"| --- | --- | --- |",
        f"| hit@1 | {hit1:.2f} | — |",
        f"| hit@5 | {hit5:.2f} | >= {HIT_AT_5_GATE} |",
        f"| MRR | {mrr:.2f} | >= {MRR_GATE} |",
        "",
        f"GATE: {'PASS' if passed else 'FAIL'}",
        "",
        "## Misses",
        "",
    ]
    for question, expected, rank in rows:
        if rank is None or rank > 1:
            lines.append(f"- rank={rank or 'absent'} expected `{expected}`: {question}")
    lines += ["", "## Out-of-scope top scores (should be low)", ""]
    for question, score in oos_rows:
        lines.append(f"- {score:.3f}: {question}")

    report = "\n".join(lines) + "\n"
    print(report)
    if args.report:
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, "w") as f:
            f.write(report)

    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
