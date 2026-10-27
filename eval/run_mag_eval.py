#!/usr/bin/env python3
"""Run the MAG scenario set against a running demo and score behavior.

Each scenario is an ordered list of steps executed against the HTTP API.
Actions: remember (chat `remember:` command, captures the memory id),
remember_api (direct POST /memories), chat (expect_mentions /
expect_absent on the answer), list (expect_count), correct, delete
(expect_status), delete_all (expect_deleted). Steps can reference ids
captured earlier via $name. Any failed expectation exits non-zero:
isolation and lifecycle semantics are deterministic.

Usage: python eval/run_mag_eval.py [--url http://localhost:8093] \
           [--scenarios eval/showcases/mag_scenarios.yaml] \
           [--report eval/reports/<date>.md] [--note "context line"]
"""

import argparse
import datetime
import os

import requests
import yaml


def load_scenarios(path):
    with open(path) as f:
        return yaml.safe_load(f)["scenarios"]


def resolve(value, variables):
    if isinstance(value, str) and value.startswith("$"):
        return variables[value[1:]]
    return value


def run_step(url, step, variables):
    action = step["action"]
    if action == "remember":
        resp = requests.post(
            f"{url}/chat",
            json={
                "user_id": step["user_id"],
                "session_id": step["session_id"],
                "question": f"remember: {step['text']}",
            },
            timeout=60,
        )
        body = resp.json()
        checks = [{"label": "status 200", "ok": resp.status_code == 200}]
        ids = body.get("evidence", {}).get("memory_ids", [])
        checks.append({"label": "memory id returned", "ok": len(ids) == 1})
        if "save_as" in step and ids:
            variables[step["save_as"]] = ids[0]
        return checks, body.get("answer", "")

    if action == "remember_api":
        resp = requests.post(
            f"{url}/memories",
            json={"user_id": step["user_id"], "text": step["text"]},
            timeout=60,
        )
        expected = step.get("expect_status", 200)
        checks = [{"label": f"status {expected}", "ok": resp.status_code == expected}]
        if "save_as" in step and resp.status_code == 200:
            variables[step["save_as"]] = resp.json()["id"]
        return checks, resp.text[:200]

    if action == "chat":
        resp = requests.post(
            f"{url}/chat",
            json={
                "user_id": step["user_id"],
                "session_id": step["session_id"],
                "question": step["question"],
            },
            timeout=60,
        )
        body = resp.json()
        answer = (body.get("answer") or "").lower()
        checks = [{"label": "status 200", "ok": resp.status_code == 200}]
        for mention in step.get("expect_mentions", []):
            checks.append({"label": f"mentions {mention!r}", "ok": mention.lower() in answer})
        for absent in step.get("expect_absent", []):
            checks.append({"label": f"absent {absent!r}", "ok": absent.lower() not in answer})
        return checks, body.get("answer", "")[:200]

    if action == "list":
        resp = requests.get(
            f"{url}/memories", params={"user_id": step["user_id"]}, timeout=60
        )
        body = resp.json()
        checks = [{"label": "status 200", "ok": resp.status_code == 200}]
        if "expect_count" in step:
            checks.append(
                {
                    "label": f"count == {step['expect_count']}",
                    "ok": body.get("count") == step["expect_count"],
                }
            )
        return checks, f"count={body.get('count')}"

    if action == "correct":
        memory_id = resolve(step["memory_id"], variables)
        resp = requests.post(
            f"{url}/memories/{memory_id}/correct",
            json={"user_id": step["user_id"], "text": step["text"]},
            timeout=60,
        )
        expected = step.get("expect_status", 200)
        checks = [{"label": f"status {expected}", "ok": resp.status_code == expected}]
        if "save_as" in step and resp.status_code == 200:
            variables[step["save_as"]] = resp.json()["id"]
        return checks, resp.text[:200]

    if action == "delete":
        memory_id = resolve(step["memory_id"], variables)
        resp = requests.delete(
            f"{url}/memories/{memory_id}",
            params={"user_id": step["user_id"]},
            timeout=60,
        )
        expected = step.get("expect_status", 200)
        return [{"label": f"status {expected}", "ok": resp.status_code == expected}], resp.text[:200]

    if action == "delete_all":
        resp = requests.delete(
            f"{url}/memories", params={"user_id": step["user_id"]}, timeout=60
        )
        body = resp.json()
        checks = [{"label": "status 200", "ok": resp.status_code == 200}]
        if "expect_deleted" in step:
            checks.append(
                {
                    "label": f"deleted == {step['expect_deleted']}",
                    "ok": body.get("deleted") == step["expect_deleted"],
                }
            )
        return checks, resp.text[:200]

    raise ValueError(f"unknown action: {action}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8093")
    parser.add_argument("--scenarios", default="eval/showcases/mag_scenarios.yaml")
    parser.add_argument("--report")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    scenarios = load_scenarios(args.scenarios)
    results = []
    for scenario in scenarios:
        variables = {}
        steps = []
        for step in scenario["steps"]:
            try:
                checks, output = run_step(args.url, step, variables)
            except Exception as exc:
                checks, output = [{"label": "transport", "ok": False}], str(exc)
            steps.append({"step": step, "checks": checks, "output": output})
        results.append({"scenario": scenario, "steps": steps})

    total = passed = 0
    for result in results:
        scenario_ok = all(
            check["ok"] for step in result["steps"] for check in step["checks"]
        )
        total += 1
        passed += scenario_ok

    lines = [f"# MAG eval — {datetime.date.today().isoformat()}", ""]
    if args.note:
        lines += [f"> {args.note}", ""]
    lines += [
        f"url: {args.url}  ",
        f"scenarios: {passed}/{total} passed",
        "",
    ]
    for result in results:
        scenario = result["scenario"]
        scenario_ok = all(
            check["ok"] for step in result["steps"] for check in step["checks"]
        )
        lines.append(f"## [{'PASS' if scenario_ok else 'FAIL'}] {scenario['id']}")
        lines.append("")
        lines.append(f"{scenario.get('description', '')}")
        lines.append("")
        for step in result["steps"]:
            action = step["step"]["action"]
            for check in step["checks"]:
                mark = "x" if check["ok"] else " "
                lines.append(f"- [{mark}] ({action}) {check['label']}")
            if not all(c["ok"] for c in step["checks"]):
                lines.append(f"  - output: {step['output']}")
        lines.append("")

    lines.append(
        "Memory semantics (isolation, lifecycle, recall) are deterministic; "
        "any FAILURE exits non-zero."
    )
    report = "\n".join(lines) + "\n"
    print(report)
    if args.report:
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
        with open(args.report, "w") as f:
            f.write(report)

    raise SystemExit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
