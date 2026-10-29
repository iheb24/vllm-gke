import json

import pytest

import benchmark
import build_manifest


def stub_counter():
    return (lambda text: max(1, len(text) // 2)), "stub"


@pytest.fixture()
def tiny_corpus(tmp_path):
    (tmp_path / "doc.md").write_text("# Doc\n\nTiny corpus for benchmark tests.\n", encoding="utf-8")
    manifest = build_manifest.build_manifest(
        tmp_path, files=["doc.md"], token_counter=stub_counter()[0]
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest) + "\n")
    return tmp_path


CANNED = """\
# HELP vllm:prefix_cache_queries_total Number of prefix cache queries
# TYPE vllm:prefix_cache_queries_total counter
vllm:prefix_cache_queries_total{model_name="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"} 40.0
vllm:prefix_cache_hits_total{model_name="Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"} 25.0
vllm:num_requests_running 2
vllm:gpu_cache_usage_perc{model_name="x"} 0.5
some_other_counter{label="a"} 3
some_other_counter{label="b"} 4.5
not a metric line
"""


def test_parse_prometheus_basic():
    metrics = benchmark.parse_prometheus(CANNED)
    assert metrics["vllm:prefix_cache_queries_total"] == 40.0
    assert metrics["vllm:prefix_cache_hits_total"] == 25.0
    assert metrics["vllm:num_requests_running"] == 2.0
    assert metrics["vllm:gpu_cache_usage_perc"] == 0.5
    assert metrics["some_other_counter"] == 7.5
    assert "not a metric line" not in metrics


def test_extract_counters_defaults_and_missing():
    metrics = benchmark.parse_prometheus(CANNED)
    counters = benchmark.extract_counters(metrics)
    assert counters == {
        "vllm:prefix_cache_queries_total": 40.0,
        "vllm:prefix_cache_hits_total": 25.0,
    }
    assert benchmark.extract_counters(metrics, ("vllm:nonexistent",)) == {"vllm:nonexistent": 0.0}


class FakeFetch:
    def __init__(self, metrics_snapshots, fail_polls=0):
        self.metrics_snapshots = list(metrics_snapshots)
        self.fail_polls = fail_polls
        self.health_polls = 0

    def __call__(self, url):
        if url.endswith("/healthz"):
            self.health_polls += 1
            if self.health_polls <= self.fail_polls:
                raise ConnectionError("not up yet")
            return '{"status": "ok"}'
        if not self.metrics_snapshots:
            raise AssertionError("unexpected extra metrics scrape")
        return self.metrics_snapshots.pop(0)


def fake_chat_stream(messages, max_output_tokens):
    fake_chat_stream.calls.append(messages[-1]["content"])
    n = len(fake_chat_stream.calls)
    return {
        "ttft_s": 0.5 / n,
        "latency_s": 1.0 / n,
        "content": f"answer {n}",
        "usage": {"prompt_tokens": 9000, "completion_tokens": 10, "total_tokens": 9010},
    }


METRICS_BEFORE = "vllm:prefix_cache_queries_total 10\nvllm:prefix_cache_hits_total 2\n"
METRICS_AFTER_HIT = "vllm:prefix_cache_queries_total 20\nvllm:prefix_cache_hits_total 7\n"
METRICS_AFTER_NO_HIT = "vllm:prefix_cache_queries_total 20\nvllm:prefix_cache_hits_total 2\n"


def run_fake_benchmark(tiny_corpus, after_metrics, after_prime_metrics=None):
    fake_chat_stream.calls = []
    snapshots = [METRICS_BEFORE, after_prime_metrics or after_metrics, after_metrics]
    fetch = FakeFetch(snapshots, fail_polls=2)
    questions = ["q one", "q two", "q three"]
    report = benchmark.run_benchmark(
        "http://fake-app",
        "http://fake-vllm/metrics",
        questions,
        3,
        corpus_dir=tiny_corpus,
        token_counter=stub_counter(),
        fetch=fetch,
        chat_stream=fake_chat_stream,
        sleep=lambda s: None,
    )
    return report, fetch


def test_benchmark_phases_and_verdict_verified(tiny_corpus):
    report, fetch = run_fake_benchmark(tiny_corpus, METRICS_AFTER_HIT)
    assert report["readiness"]["polls"] == 3
    assert report["prime"]["question"] == "q one"
    assert "not pod startup" in report["prime"]["note"]
    samples = report["warm"]["samples"]
    assert len(samples) == 3
    assert [s["question"] for s in samples] == ["q two", "q three", "q one"]
    assert all("ttft_s" in s and "latency_s" in s and "usage" in s for s in samples)
    evidence = report["cache_reuse_evidence"]
    assert evidence["before"] == {"vllm:prefix_cache_queries_total": 10.0, "vllm:prefix_cache_hits_total": 2.0}
    assert evidence["after"] == {"vllm:prefix_cache_queries_total": 20.0, "vllm:prefix_cache_hits_total": 7.0}
    assert evidence["counter_deltas"] == {"vllm:prefix_cache_queries_total": 10.0, "vllm:prefix_cache_hits_total": 5.0}
    assert evidence["verdict"] == "VERIFIED"
    assert fetch.health_polls == 3
    assert fetch.metrics_snapshots == []


def test_verdict_never_inferred_from_latency(tiny_corpus):
    report, _ = run_fake_benchmark(tiny_corpus, METRICS_AFTER_NO_HIT)
    warm = report["warm"]["samples"]
    assert warm[0]["ttft_s"] < report["prime"]["ttft_s"]
    assert report["cache_reuse_evidence"]["counter_deltas"]["vllm:prefix_cache_hits_total"] == 0.0
    assert report["cache_reuse_evidence"]["verdict"] == "NOT VERIFIED"


def test_readiness_timeout(tiny_corpus):
    fetch = FakeFetch([], fail_polls=10**9)
    with pytest.raises(TimeoutError):
        benchmark.run_benchmark(
            "http://fake-app",
            "http://fake-vllm/metrics",
            ["q"],
            1,
            corpus_dir=tiny_corpus,
            token_counter=stub_counter(),
            fetch=fetch,
            chat_stream=fake_chat_stream,
            sleep=lambda s: None,
            readiness_timeout_s=0.01,
        )


def test_restart_test_requires_explicit_env(tiny_corpus, monkeypatch):
    monkeypatch.delenv("AG_ALLOW_POD_RESTART", raising=False)
    with pytest.raises(RuntimeError, match="AG_ALLOW_POD_RESTART"):
        benchmark.restart_test(
            "http://fake-app", "http://fake-vllm/metrics", ["q"],
            corpus_dir=tiny_corpus, token_counter=stub_counter(),
        )


def test_prime_labeled_cold_on_real_misses(tiny_corpus):
    after_prime = "vllm:prefix_cache_queries_total 8500\nvllm:prefix_cache_hits_total 100\n"
    after = "vllm:prefix_cache_queries_total 8600\nvllm:prefix_cache_hits_total 8600\n"
    report, _ = run_fake_benchmark(tiny_corpus, after, after_prime)
    assert report["prime"]["cache_state"] == "cold"
    assert report["prime"]["counter_misses_during_prime"] == 8392.0


def test_prime_labeled_warm_when_already_cached(tiny_corpus):
    after_prime = "vllm:prefix_cache_queries_total 11.0\nvllm:prefix_cache_hits_total 3.0\n"
    report, _ = run_fake_benchmark(tiny_corpus, METRICS_AFTER_HIT, after_prime)
    assert report["prime"]["cache_state"] == "warm"
    assert report["prime"]["counter_misses_during_prime"] == 0.0
