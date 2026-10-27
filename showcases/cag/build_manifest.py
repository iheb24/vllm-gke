"""Regenerate corpus/manifest.json for the CAG showcase.

The manifest pins the corpus: an explicit ordered file list (never
filesystem order), a per-file sha256, an overall corpus sha256 over the
ordered concatenation of filename + NUL + bytes, and a real-tokenizer token
count with a hard budget check. corpus.py refuses to serve a corpus whose
bytes no longer match this manifest, so any extract edit must be followed
by re-running this script:

    .venv-showcases/bin/python showcases/cag/build_manifest.py
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
CORPUS_DIR = MODULE_DIR / "corpus"
MANIFEST_NAME = "manifest.json"

CORPUS_FILES = [
    "routing-architecture.md",
    "gateway-integration.md",
    "operator-guide.md",
    "cost-model.md",
    "routing-behavior.md",
    "rag-design.md",
]

TOKENIZER_ID = "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ"
TOKEN_BUDGET = 12000


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def corpus_digest(named_bytes):
    digest = hashlib.sha256()
    for name, data in named_bytes:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
    return digest.hexdigest()


def default_token_counter():
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_pretrained(TOKENIZER_ID)
    return lambda text: len(tokenizer.encode(text).ids), TOKENIZER_ID


def build_manifest(corpus_dir=CORPUS_DIR, files=None, token_counter=None):
    corpus_dir = Path(corpus_dir)
    names = list(files) if files else list(CORPUS_FILES)
    if token_counter is None:
        token_counter, tokenizer_label = default_token_counter()
    else:
        tokenizer_label = "injected"
    named_bytes = []
    for name in names:
        path = corpus_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"corpus file missing: {path}")
        named_bytes.append((name, path.read_bytes()))
    entries = [
        {
            "file": name,
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "tokens": token_counter(data.decode("utf-8")),
        }
        for name, data in named_bytes
    ]
    total_tokens = sum(entry["tokens"] for entry in entries)
    digest = corpus_digest(named_bytes)
    manifest = {
        "corpus_sha256": digest,
        "corpus_sha256_short": digest[:12],
        "tokenizer": tokenizer_label,
        "tokenizer_id": TOKENIZER_ID if tokenizer_label != "injected" else None,
        "token_budget": TOKEN_BUDGET,
        "total_tokens": total_tokens,
        "files": entries,
    }
    if total_tokens > TOKEN_BUDGET:
        raise ValueError(
            f"corpus is {total_tokens} tokens, over the {TOKEN_BUDGET}-token "
            "budget; shrink the extracts and re-run build_manifest.py"
        )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir", default=str(CORPUS_DIR))
    args = parser.parse_args()
    try:
        manifest = build_manifest(Path(args.corpus_dir))
    except (FileNotFoundError, ValueError) as exc:
        print(f"manifest build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    out_path = Path(args.corpus_dir) / MANIFEST_NAME
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"corpus_sha256: {manifest['corpus_sha256_short']}  tokenizer: {manifest['tokenizer']}")
    for entry in manifest["files"]:
        print(f"  {entry['file']}: {entry['tokens']} tokens, {entry['bytes']} bytes")
    print(f"  total: {manifest['total_tokens']} / {manifest['token_budget']} tokens")


if __name__ == "__main__":
    main()
