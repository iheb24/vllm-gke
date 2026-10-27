import ast
from pathlib import Path

CAG_DIR = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORT_ROOTS = {
    "qdrant",
    "qdrant_client",
    "fastembed",
    "sentence_transformers",
    "tei",
    "rerank",
}


def _import_roots(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_retrieval_stack_imports_anywhere():
    offenders = {}
    for path in sorted(CAG_DIR.glob("*.py")):
        bad = _import_roots(path) & FORBIDDEN_IMPORT_ROOTS
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, f"retrieval-stack imports found: {offenders}"
