"""Deterministic scripted model transport for local demos and tests.

The fake inspects the memory block the pipeline injected into the system
prompt: memories are parsed out of the delimited block, scored by keyword
overlap with the question, and a relevant memory is explicitly referenced
in the answer (mirroring how the system contract asks the model to cite
memory ids). Recommendation-style questions (should/which/best/cheap/use…)
reference the most recent injected memory even without keyword overlap,
the way a real model would apply a stored preference to a decision. Only
with no relevant memory at all is the answer generic. Usage is synthetic
but consistent. Everything is deterministic, which is what makes the
Alice/Bob demo and the scenario eval reproducible offline.
"""

import re

MEMORY_LINE = re.compile(r"^\[(\d+)\]\s+(.*)$")
BLOCK_RE = re.compile(
    r"<user-provided-memories>\n(.*?)\n</user-provided-memories>", re.DOTALL
)

_STOPWORDS = {
    "the", "and", "for", "with", "what", "which", "how", "does", "do", "you",
    "are", "was", "were", "when", "where", "why", "that", "this", "your",
    "yours", "from", "into", "about", "can", "could", "should", "would",
    "will", "have", "has", "had", "not", "but", "all", "any", "each", "who",
    "me", "my", "i", "a", "an", "of", "to", "in", "on", "is", "it", "be",
}


def _words(text):
    return {
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def _overlap(question_words, memory_words):
    count = 0
    for question_word in question_words:
        for memory_word in memory_words:
            if question_word == memory_word or (
                min(len(question_word), len(memory_word)) >= 4
                and (
                    question_word.startswith(memory_word)
                    or memory_word.startswith(question_word)
                )
            ):
                count += 1
                break
    return count


def parse_memory_block(system_content):
    match = BLOCK_RE.search(system_content)
    if not match:
        return []
    memories = []
    for line in match.group(1).splitlines():
        line_match = MEMORY_LINE.match(line.strip())
        if line_match:
            memories.append((int(line_match.group(1)), line_match.group(2)))
    return memories


_RECOMMENDATION_WORDS = {
    "should", "recommend", "which", "best", "cheap", "cheapest",
    "prefer", "use", "choose", "suggest",
}


def answer_for(system_content, question, prior_turns):
    question_words = _words(question)
    memories = parse_memory_block(system_content)
    best = (0, None, None)
    for memory_id, text in memories:
        overlap = _overlap(question_words, _words(text))
        if overlap > best[0]:
            best = (overlap, memory_id, text)
    raw_words = set(re.findall(r"[a-z0-9]+", question.lower()))
    if best[1] is None and memories and raw_words & _RECOMMENDATION_WORDS:
        memory_id, text = memories[-1]
        best = (1, memory_id, text)
    if best[1] is not None:
        return (
            f"Based on your stored memory [{best[1]}] \"{best[2]}\", "
            f"here is the answer to your question: {question.rstrip('?')} "
            f"(adjusted for that memory)."
        )
    if prior_turns:
        return (
            f"Following our conversation in this session ({len(prior_turns)} earlier "
            f"turns), here is a generic answer to: {question.rstrip('?')} "
            "(no stored memory was relevant)."
        )
    return (
        f"Generic answer to: {question.rstrip('?')} "
        "(no stored memories were relevant to this question)."
    )


def make_fake_transport():
    def transport(base_url, api_key, payload):
        transport.calls += 1
        messages = payload["messages"]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        question = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        prior_turns = [m for m in messages if m["role"] in ("user", "assistant")][:-1]
        content = answer_for(system, question, prior_turns)
        prompt_tokens = sum(len(m["content"]) for m in messages) // 4
        completion_tokens = len(content) // 4
        return {
            "id": "fake-mag-0",
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
