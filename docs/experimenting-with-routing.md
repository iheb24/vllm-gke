# Routing Behavior and Limits

Technical assessment of what the classifier does, where it fails, how the
Plan/Act tier split evaluates, and how routing decisions are observed and tuned.

## Classifier capabilities

The semantic router uses a ModernBERT topic classifier plus keyword signals.
It categorizes prompt topics (computer science, math, history, business, …).
It does not estimate task complexity. Two prompts in the same topic with
different difficulty ("plan a static site" vs "plan a distributed rewrite")
are indistinguishable to it.

Observed behavior on this cluster:

| Prompt | Classification | Tier | Assessment |
|---|---|---|---|
| Tell me a fun fact about octopuses | other | CPU | correct |
| Three-day trip to Lisbon | other | CPU | correct |
| Write a Python function that reverses a string | computer science | GPU | false positive, accepted |
| Schema + migrations for a billing system | business (misled by "billing") | CPU → fixed to GPU | false negative, corrected via keywords |
| Pytest race condition debug | CS + keyword "debug" | GPU | correct |
| Plan a birthday party | other | CPU | correct |

Because complexity cannot be measured reliably, the configuration relies on
escalation bias: ambiguous or unmatched prompts default to the GPU tier. False
positives (simple prompt wakes the GPU) are accepted; false negatives (complex
task served by the small model) are the failure mode the rules are tuned to
prevent.

## Plan/Act tier split assessment

Proposal evaluated: Plan mode on `auto`, Act mode on `qwen3-4b-cpu`.

Rejected for two structural reasons:

1. **Act mode is precision-critical.** Act emits tool calls, file edits, and
   shell commands. A 4B quantized model on shared CPU is least reliable exactly
   there. Failures are silent: plausible-looking wrong edits or malformed tool
   calls that break the agent loop.

2. **Routing is per-message; agentic sessions are per-conversation.** The
   router classifies each message in isolation. Short follow-ups inside a
   planning session ("yes, option two") can classify as casual and switch the
   model mid-session. The continuation model then lacks the capability the
   earlier steps assumed.

The split Cline documents (strong model for Plan, cheaper for Act) assumes the
Act model is still a reliable coder. The CPU tier does not meet that bar; it is
a chat-tier model. Current policy: Cline uses the 14B for both modes.

If CPU offloading for agentic clients is ever needed, the viable scope is
client-side subtasks (commit messages, summaries), where the client defines
the safe boundaries, not mid-loop model swaps.

## Observing routing decisions

Four methods, ordered by convenience:

1. **Chat UI badge** — each answer shows the tier, backend model name, and
   response time.
2. **Response headers** — `x-vsr-selected-model`, `x-vsr-selected-decision`,
   `x-vsr-selected-confidence`, `x-vsr-routing-latency-ms`.
3. **Router logs** —
   `kubectl logs -n vllm-semantic-router-system deploy/semantic-router -f | grep routing_decision`
4. **Envoy access logs** — show the upstream (`slm-service` vs KEDA
   interceptor).

## Tuning loop

1. Fire the labeled suite (`k8s/semantic-router/test-prompts.md`) through the
   gateway with `model: auto`.
2. Record the tier for each prompt (UI badge or router logs).
3. Requirements: `code-agentic` must reach the GPU 100%; `chat-casual` should
   reach the CPU; misrouted-simple→GPU is accepted.
4. Adjust `signals` and `decisions` in `k8s/semantic-router/values.yaml`,
   then `helm upgrade semantic-router ... && kubectl rollout restart
   deploy/semantic-router -n vllm-semantic-router-system`.
5. `router_replay` retains decisions for 30 days; use real traffic for tuning
   once the stack sees regular use.

## Test chat UI

Location: `chat-ui/`. Start with `python3 chat-ui/serve.py` after the gateway
port-forward is up (see `implementation-guide.md`). The UI serves the three
modes, streams responses, and badges each answer with the serving tier.

Design note: the UI and API are served from one origin by `serve.py`. Gateway
CORS was evaluated and rejected: OPTIONS preflights enter the ext_proc filter
before CORS handling and are rejected by the router.
