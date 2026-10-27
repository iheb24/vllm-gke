import json
import re

import pytest

import build_manifest
import corpus


def stub_counter(divisor=2):
    return (lambda text: max(1, len(text) // divisor)), f"stub-chars//{divisor}"


@pytest.fixture()
def tiny_corpus(tmp_path):
    files = {
        "alpha.md": "# Alpha\n\nThe CPU tier model is qwen3-4b-cpu and stays always warm.\n",
        "beta.md": "# Beta\n\nThe GPU tier wakes on demand and scales to zero after 300 s idle.\n",
        "gamma.md": "# Gamma\n\nIdle cost is about $100 per month for the system pool.\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    manifest = build_manifest.build_manifest(
        tmp_path, files=["gamma.md", "alpha.md", "beta.md"], token_counter=stub_counter()[0]
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return tmp_path


def test_prefix_byte_identical_across_questions(tiny_corpus):
    messages_a, _ = corpus.build_messages("What model serves the CPU tier?", stub_counter(), corpus_dir=tiny_corpus)
    messages_b, _ = corpus.build_messages("How much does idle cost?", stub_counter(), corpus_dir=tiny_corpus)
    assert messages_a[0]["role"] == "system"
    assert messages_a[0]["content"] == messages_b[0]["content"]
    assert messages_a[1]["content"] == "What model serves the CPU tier?"
    assert messages_b[1]["content"] == "How much does idle cost?"
    assert messages_a[1]["content"] not in messages_a[0]["content"]


def test_document_order_follows_manifest_not_filesystem(tiny_corpus):
    messages, info = corpus.build_messages("anything", stub_counter(), corpus_dir=tiny_corpus)
    system = messages[0]["content"]
    positions = [system.index(f"## Source: {name}") for name in ("gamma.md", "alpha.md", "beta.md")]
    assert positions == sorted(positions)
    assert info["sources"] == ["gamma.md", "alpha.md", "beta.md"]


def test_prefix_has_no_injected_timestamps_or_ids(tiny_corpus):
    messages, _ = corpus.build_messages("anything", stub_counter(), corpus_dir=tiny_corpus)
    system = messages[0]["content"]
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", system)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", system)
    assert "request_id" not in system
    assert "nonce" not in system


def test_manifest_sha_changes_when_file_changes(tiny_corpus):
    before = corpus.load_manifest(tiny_corpus)["corpus_sha256"]
    (tiny_corpus / "alpha.md").write_text("# Alpha\n\nChanged content entirely.\n", encoding="utf-8")
    manifest = build_manifest.build_manifest(
        tiny_corpus, files=["gamma.md", "alpha.md", "beta.md"], token_counter=stub_counter()[0]
    )
    assert manifest["corpus_sha256"] != before


def test_stale_corpus_fails_loud(tiny_corpus):
    (tiny_corpus / "beta.md").write_text("# Beta\n\nEdited after the manifest was built.\n", encoding="utf-8")
    with pytest.raises(corpus.CorpusError, match="re-run build_manifest"):
        corpus.load_corpus(tiny_corpus)
    with pytest.raises(corpus.CorpusError):
        corpus.build_messages("anything", stub_counter(), corpus_dir=tiny_corpus)


def test_missing_file_fails_loud(tiny_corpus):
    (tiny_corpus / "beta.md").unlink()
    with pytest.raises(corpus.CorpusError, match="missing"):
        corpus.load_corpus(tiny_corpus)


def test_over_budget_corpus_rejected_at_build(tmp_path):
    (tmp_path / "big.md").write_text("word " * 5000, encoding="utf-8")
    with pytest.raises(ValueError, match="budget"):
        build_manifest.build_manifest(
            tmp_path, files=["big.md"], token_counter=(lambda text: 50000)
        )


def test_over_budget_manifest_rejected_before_model_call(tmp_path):
    (tmp_path / "doc.md").write_text("# Doc\n\nSmall but mislabelled.\n", encoding="utf-8")
    manifest = build_manifest.build_manifest(
        tmp_path, files=["doc.md"], token_counter=stub_counter()[0]
    )
    manifest["total_tokens"] = 13000
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(corpus.BudgetExceeded, match="13000"):
        corpus.build_messages("anything", stub_counter(), corpus_dir=tmp_path)


def test_over_long_question_rejected_by_budget(tiny_corpus):
    huge_counter = (lambda text: 40000 if text.startswith("x") else 1), "stub-huge"
    with pytest.raises(corpus.BudgetExceeded, match="context window"):
        corpus.build_messages("x" * 1000, huge_counter, corpus_dir=tiny_corpus)


def test_budget_math_in_info(tiny_corpus):
    counter = (lambda text: 100), "stub-fixed"
    manifest, _ = corpus.load_corpus(tiny_corpus)
    _, info = corpus.build_messages("anything", counter, corpus_dir=tiny_corpus, max_output_tokens=1024)
    assert info["question_tokens"] == 100
    assert info["required_tokens"] == manifest["total_tokens"] + 100 + 512 + 1024
    assert info["context_limit"] == 32768
    assert info["tokenizer"] == "stub-fixed"
    assert len(info["corpus_version"]) == 12


def test_real_corpus_loads_and_scores():
    manifest, docs = corpus.load_corpus()
    assert len(docs) == 6
    assert manifest["total_tokens"] <= 12000
    assert manifest["tokenizer"] == "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
