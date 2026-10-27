#!/usr/bin/env python3
"""Run the CAG showcase question set against a running demo and score it.

Question types:
- corpus: the answer must mention every required_mentions item and cite
  the expected_source extract file (the system prompt instructs source
  citations; the corpus is fixed, so failures here are deterministic and
  exit non-zero).
- out_of_corpus: the answer must fall back to the not-covered response
  instead of inventing content.

This is a quality report only: no latency claims are made from it. Cache
reuse evidence comes from showcase/cag benchmark counter deltas, not from
answer timing.

Usage: python eval/run_cag_eval.py [--url http://localhost:8092] \
           [--questions eval/showcases/cag_questions.yaml] \
           [--report eval/reports/<date>.md] [--note "context line"]
"""

import argparse
import datetime
import os

import requests
import yaml

FALLBACK_MARKERS = ("does not cover", "not covered")


def load_questions(path):
    with open(path) as f:
        return yaml.safe_load(f)["questions"]


def ask(url, question):
    resp = requests.post(f"{url}/chat", json={"question": question}, timeout=180)
    resp.raise_for_status()
    return resp.json()


def score(question, result):
    answer = (result.get("answer") or "").lower()
    if question["type"] == "corpus":
        missing = [m for m in question["required_mentions"] if m.lower() not in answer]
        source_ok = question["expected_source"].lower() in answer
        return not missing and source_ok, {
            "missing_mentions": missing,
            "source_cited": source_ok,
        }
    if question["type"] == "out_of_corpus":
        fell_back = any(marker in answer for marker in FALLBACK_MARKERS)
        return fell_back, {"fallback": fell_back}
    raise ValueError(f"unknown question type: {question['type']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8092")
    parser.add_argument("--questions", default="eval/showcases/cag_questions.yaml")
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

    corpus_failed = [
        r for r in results if r["question"]["type"] == "corpus" and not r["passed"]
    ]

    lines = [
        f"# CAG eval — {datetime.date.today().isoformat()}",
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
        "Quality report only: no latency claims. `corpus` failures fail the "
        "run because the corpus is fixed and the expected mentions are "
        "deterministic.",
        "",
        "## Per-question results",
        "",
    ]
    for r in results:
        q = r["question"]
        verdict = "PASS" if r["passed"] else "FAIL"
        lines.append(f"- [{verdict}] ({q['type']}) `{q['id']}`: {q['question']}")
        if q["type"] == "corpus":
            mark = "x" if r["detail"].get("source_cited") else " "
            lines.append(f"  - [{mark}] source: {q['expected_source']}")
            for mention in q["required_mentions"]:
                present = mention not in r["detail"].get("missing_mentions", [])
                lines.append(f"  - [{'x' if present else ' '}] mention: {mention}")
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

    raise SystemExit(1 if corpus_failed else 0)


if __name__ == "__main__":
    main()
