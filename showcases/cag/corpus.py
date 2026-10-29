"""Deterministic static-prefix prompt builder for the CAG showcase.

The entire operations-handbook corpus is a stable prompt prefix: every
request sends the same system message, and only the user question changes.
That stability is the whole point — it is what lets vLLM automatic prefix
caching reuse the KV blocks of the corpus across requests.

Contracts enforced here:
- manifest-pinned corpus: every file's sha256 must match manifest.json,
  so a stale edit fails loud at startup instead of silently changing the
  prefix (and with it, cache behavior and answers).
- byte-identical system content across requests: no timestamps, request
  IDs, or any per-request data in the prefix; the question is always the
  suffix; document order is the manifest order, never filesystem order.
- budget check before any model call: corpus tokens (real-tokenizer count
  recorded in the manifest) + question tokens + a chat-template reserve +
  the configured max output must fit maxModelLen, else BudgetExceeded is
  raised without touching the gateway.
"""

import hashlib
import json
import os
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = MODULE_DIR / "corpus"
MANIFEST_NAME = "manifest.json"

TOKENIZER_ID = "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
CORPUS_TOKEN_BUDGET = 12000
MAX_CONTEXT_TOKENS = 32768
CHAT_TEMPLATE_RESERVE = 512
DEFAULT_MAX_OUTPUT_TOKENS = 1024

SYSTEM_INSTRUCTIONS = """You are the operations handbook assistant for a self-hosted vLLM-on-GKE stack.
Answer strictly from the handbook extracts below.
Rules:
- Ground every claim in the extracts; outside knowledge is forbidden.
- Quote exact identifiers (model names, error codes, commands, numbers) verbatim.
- Quote durations and numbers in the exact form the extract uses (do not convert units).
- Every answer MUST end with a final line exactly of the form: Sources: <filename>[, <filename>...]
- If the extracts do not cover the question, say exactly: the operations handbook corpus does not cover this question.
"""

FALLBACK_ANSWER = "The operations handbook corpus does not cover this question."


class CorpusError(Exception):
    """The corpus on disk does not match its manifest."""


class BudgetExceeded(Exception):
    """The request cannot fit the model context window."""


def load_manifest(corpus_dir=CORPUS_DIR):
    path = Path(corpus_dir) / MANIFEST_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(
            f"corpus manifest missing at {path}; run build_manifest.py"
        ) from exc


def load_corpus(corpus_dir=CORPUS_DIR):
    corpus_dir = Path(corpus_dir)
    manifest = load_manifest(corpus_dir)
    docs = []
    for entry in manifest["files"]:
        path = corpus_dir / entry["file"]
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise CorpusError(
                f"corpus file {entry['file']} listed in the manifest is missing; "
                "re-run build_manifest.py"
            ) from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry["sha256"]:
            raise CorpusError(
                f"corpus file {entry['file']} changed since the manifest was "
                "built; re-run build_manifest.py to refresh manifest.json"
            )
        docs.append((entry["file"], data.decode("utf-8")))
    return manifest, docs


_tokenizer_cache = {}


def default_token_counter():
    if "counter" in _tokenizer_cache:
        return _tokenizer_cache["counter"]
    if os.environ.get("CAG_TOKENIZER", "").lower() in ("estimated", "offline"):
        counter = (lambda text: len(text) // 2), "estimated (chars//2, forced by CAG_TOKENIZER)"
        _tokenizer_cache["counter"] = counter
        return counter
    try:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_pretrained(TOKENIZER_ID)
        counter = (lambda text: len(tokenizer.encode(text).ids)), TOKENIZER_ID
    except Exception:
        counter = (lambda text: len(text) // 2), "estimated (chars//2, tokenizers unavailable)"
    _tokenizer_cache["counter"] = counter
    return counter


def build_messages(
    question,
    token_counter,
    corpus_dir=CORPUS_DIR,
    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
):
    manifest, docs = load_corpus(corpus_dir)
    count, counter_label = token_counter
    corpus_tokens = manifest["total_tokens"]
    if corpus_tokens > CORPUS_TOKEN_BUDGET:
        raise BudgetExceeded(
            f"corpus is {corpus_tokens} tokens, over the {CORPUS_TOKEN_BUDGET}-token "
            "budget; shrink the extracts and re-run build_manifest.py"
        )
    question_tokens = count(question)
    required = corpus_tokens + question_tokens + CHAT_TEMPLATE_RESERVE + max_output_tokens
    if required > MAX_CONTEXT_TOKENS:
        raise BudgetExceeded(
            f"request needs ~{required} tokens "
            f"(corpus {corpus_tokens} + question {question_tokens} + "
            f"template reserve {CHAT_TEMPLATE_RESERVE} + output {max_output_tokens}) "
            f"which exceeds the {MAX_CONTEXT_TOKENS}-token context window; "
            "shorten the question"
        )
    sections = "\n\n".join(f"## Source: {name}\n\n{text.strip()}" for name, text in docs)
    system = SYSTEM_INSTRUCTIONS + "\n" + sections
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    info = {
        "corpus_version": manifest["corpus_sha256_short"],
        "corpus_tokens": corpus_tokens,
        "question_tokens": question_tokens,
        "required_tokens": required,
        "context_limit": MAX_CONTEXT_TOKENS,
        "tokenizer": counter_label,
        "sources": [name for name, _ in docs],
    }
    return messages, info
