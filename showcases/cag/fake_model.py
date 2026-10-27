"""Deterministic scripted model transport for local demos and tests.

The fake answers extractively: it splits the system prompt (which always
carries the whole corpus under '## Source: <file>' headers) into sections,
scores sections and paragraph units by keyword overlap with the question,
and quotes the best unit verbatim with a source citation. When nothing
overlaps, it returns the same not-covered fallback the system prompt
instructs. Usage is synthetic but consistent: prompt tokens are the
manifest corpus count plus an estimate for the question and the chat
template reserve, mirroring what a real prefix-cached request reports.
"""

import json
import re
from pathlib import Path

_STOPWORDS = {
    "the", "and", "for", "with", "what", "which", "how", "does", "do", "you",
    "are", "was", "were", "when", "where", "why", "that", "this", "these",
    "those", "from", "into", "your", "their", "its", "his", "her", "our",
    "out", "about", "can", "could", "should", "would", "will", "have", "has",
    "had", "not", "but", "all", "any", "each", "per", "who", "whom", "much",
    "many", "than", "then", "them", "they", "say", "said", "mean", "means",
}

NOT_COVERED = "The operations handbook corpus does not cover this question."


def _question_words(question):
    words = re.findall(r"[a-z0-9][a-z0-9_.:/-]*", question.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


def _split_sections(system_content):
    parts = re.split(r"^## Source: (\S+)\s*$", system_content, flags=re.MULTILINE)
    sections = []
    for i in range(1, len(parts), 2):
        sections.append((parts[i], parts[i + 1]))
    return sections


def _split_units(section_text):
    units = []
    for block in re.split(r"\n\s*\n", section_text):
        lines = [
            line for line in block.splitlines()
            if line.strip()
            and not line.strip().startswith("<!--")
            and not line.strip().startswith("#")
        ]
        text = " ".join(line.strip() for line in lines).strip()
        if text:
            units.append(text)
    return units


def _score(text, words):
    lowered = text.lower()
    return sum(1 for w in words if w in lowered)


def answer_from_system(system_content, question):
    words = _question_words(question)
    if not words:
        return NOT_COVERED
    scored = []
    order = 0
    for name, section_text in _split_sections(system_content):
        for unit in _split_units(section_text):
            unit_score = _score(unit, words)
            if unit_score > 0:
                scored.append((unit_score, order, name, unit))
            order += 1
    if not scored:
        return NOT_COVERED
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    top_score = scored[0][0]
    chosen = [entry for entry in scored if entry[0] >= max(1, top_score * 0.5)][:3]
    chosen.sort(key=lambda entry: entry[1])
    sources = ", ".join(dict.fromkeys(entry[2] for entry in chosen))
    quotes = [f'"{entry[3]}"\n(source: {entry[2]})' for entry in chosen]
    return f"From {sources}:\n\n" + "\n\n".join(quotes)


def make_fake_transport(corpus_dir=None):
    corpus_tokens = 0
    if corpus_dir:
        try:
            manifest = json.loads(
                (Path(corpus_dir) / "manifest.json").read_text(encoding="utf-8")
            )
            corpus_tokens = manifest["total_tokens"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            corpus_tokens = 0

    def transport(base_url, api_key, payload):
        transport.calls += 1
        messages = payload["messages"]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        question = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        content = answer_from_system(system, question)
        if corpus_tokens:
            prompt_tokens = corpus_tokens + len(question) // 2 + 512
        else:
            prompt_tokens = sum(len(m["content"]) for m in messages) // 4
        completion_tokens = len(content) // 4
        return {
            "id": "fake-cag-0",
            "object": "chat.completion",
            "model": payload.get("model", "fake"),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    transport.calls = 0
    return transport
