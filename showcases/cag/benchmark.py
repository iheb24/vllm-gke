"""Live-session prefix-cache benchmark harness for the CAG showcase.

Measures whether vLLM automatic prefix caching actually reuses the corpus
prefix across requests, using the model server's own Prometheus counters as
the only source of truth. Latency numbers are recorded as raw samples for
context but are NEVER used to infer cache reuse: the verdict comes from
counter deltas alone.

Phases: (a) poll the demo app /healthz until ready (recorded separately),
(b) one cold-prefix prime request measured alone (this is cache-priming
prefill, not pod startup), (c) a warm loop of streaming requests with
rotating distinct questions recording TTFT and end-to-end latency,
(d) re-scrape counters and compute deltas, (e) emit a report dict.

Every network touch is injectable (fetch, chat_stream) so tests run fully
offline. The optional pod-restart test is guarded behind the
AG_ALLOW_POD_RESTART=1 environment variable so it can never run by accident.
"""

import argparse
import json
import os
import subprocess
import time
import urllib.request

DEFAULT_COUNTERS = ("vllm:prefix_cache_queries_total", "vllm:prefix_cache_hits_total")
RESTART_ENV_VAR = "AG_ALLOW_POD_RESTART"
PRIME_NOTE = (
    "first request after readiness: cache-priming prefill, not pod startup; "
    "pod startup time belongs to the readiness phase; cache_state is cold "
    "only when the prefix counters show real misses during this request "
    "(restart the vLLM pod first for a true cold measurement)"
)


def parse_prometheus(text):
    metrics = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name_part, separator, value_part = line.rpartition(" ")
        if not separator:
            continue
        try:
            value = float(value_part)
        except ValueError:
            continue
        name = name_part.split("{", 1)[0].strip()
        if not name:
            continue
        metrics[name] = metrics.get(name, 0.0) + value
    return metrics


def extract_counters(metrics, names=DEFAULT_COUNTERS):
    return {name: metrics.get(name, 0.0) for name in names}


def _default_fetch(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        return response.read().decode("utf-8")


def _env_chat_stream_factory():
    base_url = os.environ.get("GATEWAY_URL", "http://localhost:8081").rstrip("/")
    api_key = os.environ.get("GATEWAY_API_KEY")
    model = os.environ.get("GATEWAY_MODEL", "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ")

    def chat_stream(messages, max_output_tokens):
        import requests

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        start = time.perf_counter()
        ttft = None
        chunks = []
        usage = {}
        with requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            stream=True,
            timeout=600,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                data = line[len(b"data:"):].strip()
                if data == b"[DONE]":
                    break
                if ttft is None:
                    ttft = time.perf_counter() - start
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("usage"):
                    usage = event["usage"]
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {}).get("content")
                    if delta:
                        chunks.append(delta)
        return {
            "ttft_s": ttft,
            "latency_s": round(time.perf_counter() - start, 6),
            "content": "".join(chunks),
            "usage": usage,
        }

    return chat_stream


def run_benchmark(
    app_url,
    vllm_metrics_url,
    questions,
    n_warm,
    *,
    counter_names=DEFAULT_COUNTERS,
    max_output_tokens=1024,
    corpus_dir=None,
    token_counter=None,
    fetch=None,
    chat_stream=None,
    readiness_timeout_s=900.0,
    poll_interval_s=5.0,
    sleep=time.sleep,
    clock=time.perf_counter,
):
    if not questions:
        raise ValueError("questions must not be empty")
    fetch = fetch or _default_fetch
    chat_stream = chat_stream or _env_chat_stream_factory()

    import corpus as corpus_module

    token_counter = token_counter or corpus_module.default_token_counter()
    corpus_dir = corpus_dir or corpus_module.CORPUS_DIR

    def build(question):
        messages, info = corpus_module.build_messages(
            question, token_counter, corpus_dir=corpus_dir,
            max_output_tokens=max_output_tokens,
        )
        return messages, info

    readiness_start = clock()
    polls = 0
    waited = 0.0
    while True:
        polls += 1
        try:
            body = fetch(f"{app_url}/healthz")
            if "ok" in body:
                break
        except Exception:
            pass
        waited = clock() - readiness_start
        if waited > readiness_timeout_s:
            raise TimeoutError(
                f"app at {app_url} not ready after {readiness_timeout_s}s "
                f"({polls} polls)"
            )
        sleep(poll_interval_s)
    waited = clock() - readiness_start
    readiness = {"waited_s": round(waited, 3), "polls": polls}

    _, prime_info = build(questions[0])
    before = extract_counters(parse_prometheus(fetch(vllm_metrics_url)), counter_names)
    prime_start = clock()
    prime_result = chat_stream(build(questions[0])[0], max_output_tokens)
    after_prime = extract_counters(parse_prometheus(fetch(vllm_metrics_url)), counter_names)
    prime_misses = 0.0
    for name in counter_names:
        if "queries" in name:
            hits_name = name.replace("queries", "hits")
            if hits_name in after_prime:
                prime_misses += (after_prime[name] - before[name]) - (
                    after_prime[hits_name] - before[hits_name]
                )
    prime = {
        "question": questions[0],
        "ttft_s": prime_result["ttft_s"],
        "latency_s": prime_result["latency_s"],
        "usage": prime_result["usage"],
        "cache_state": "cold" if prime_misses >= 100 else "warm",
        "counter_misses_during_prime": round(prime_misses, 6),
        "note": PRIME_NOTE,
    }

    samples = []
    for i in range(n_warm):
        question = questions[(i + 1) % len(questions)]
        result = chat_stream(build(question)[0], max_output_tokens)
        samples.append(
            {
                "iteration": i + 1,
                "question": question,
                "ttft_s": result["ttft_s"],
                "latency_s": result["latency_s"],
                "usage": result["usage"],
            }
        )

    after = extract_counters(parse_prometheus(fetch(vllm_metrics_url)), counter_names)
    deltas = {name: round(after[name] - before[name], 6) for name in counter_names}
    hit_deltas = [delta for name, delta in deltas.items() if "hit" in name]
    verdict = "VERIFIED" if any(delta > 0 for delta in hit_deltas) else "NOT VERIFIED"

    return {
        "app_url": app_url,
        "vllm_metrics_url": vllm_metrics_url,
        "corpus": {
            "corpus_version": prime_info["corpus_version"],
            "corpus_tokens": prime_info["corpus_tokens"],
            "tokenizer": prime_info["tokenizer"],
            "sources": prime_info["sources"],
        },
        "config": {
            "n_warm": n_warm,
            "max_output_tokens": max_output_tokens,
            "counter_names": list(counter_names),
        },
        "readiness": readiness,
        "prime": prime,
        "warm": {"samples": samples},
        "cache_reuse_evidence": {
            "before": before,
            "after": after,
            "counter_deltas": deltas,
            "verdict": verdict,
        },
        "restart_test": None,
    }


def _default_kubectl_run():
    subprocess.run(
        [
            "kubectl", "delete", "pod", "-n", "vllm",
            "-l", "app=vllm-server", "--wait=false",
        ],
        check=True,
        capture_output=True,
    )


def restart_test(app_url, vllm_metrics_url, questions, *, kubectl_run=None, **kwargs):
    if os.environ.get(RESTART_ENV_VAR) != "1":
        raise RuntimeError(
            f"pod restart test refused: set {RESTART_ENV_VAR}=1 explicitly to "
            "allow deleting the vLLM pod"
        )
    kubectl_run = kubectl_run or _default_kubectl_run
    kubectl_run()
    report = run_benchmark(app_url, vllm_metrics_url, questions, 1, **kwargs)
    return {
        "note": (
            "after pod deletion the prefix cache is gone; the first request "
            "must re-prime it (prime latency comparable to the original cold "
            "prime, hit counters start from zero)"
        ),
        "re_prime": report["prime"],
        "cache_reuse_evidence": report["cache_reuse_evidence"],
    }


def load_questions(path):
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)
    return [q["question"] for q in data["questions"] if q.get("type", "corpus") == "corpus"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://localhost:8092")
    parser.add_argument("--vllm-metrics-url", default="http://localhost:8000/metrics")
    parser.add_argument("--questions", default="eval/showcases/cag_questions.yaml")
    parser.add_argument("--n-warm", type=int, default=10)
    parser.add_argument("--max-output-tokens", type=int, default=1024)
    parser.add_argument("--counters", default=",".join(DEFAULT_COUNTERS))
    parser.add_argument("--report")
    parser.add_argument("--restart-test", action="store_true")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    counter_names = tuple(name.strip() for name in args.counters.split(",") if name.strip())
    report = run_benchmark(
        args.app_url,
        args.vllm_metrics_url,
        questions,
        args.n_warm,
        counter_names=counter_names,
        max_output_tokens=args.max_output_tokens,
    )
    if args.restart_test:
        report["restart_test"] = restart_test(
            args.app_url, args.vllm_metrics_url, questions,
            counter_names=counter_names, max_output_tokens=args.max_output_tokens,
        )

    evidence = report["cache_reuse_evidence"]
    print(f"readiness: {report['readiness']}")
    print(
        f"prime ttft={report['prime']['ttft_s']}s latency={report['prime']['latency_s']}s "
        f"cache_state={report['prime']['cache_state']} "
        f"(misses during prime={report['prime']['counter_misses_during_prime']})"
    )
    for sample in report["warm"]["samples"]:
        print(f"warm #{sample['iteration']}: ttft={sample['ttft_s']}s latency={sample['latency_s']}s")
    print(f"counter deltas: {evidence['counter_deltas']}")
    print(f"cache reuse verdict: {evidence['verdict']}")
    if args.report:
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"report written to {args.report}")


if __name__ == "__main__":
    main()
