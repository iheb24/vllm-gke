# Experimenting with Routing: Plan/Act, Classifier Limits, and the Test UI

This document collects the answers to three questions that came up while testing
the tiered stack: whether splitting Cline's Plan and Act modes across tiers is a
good idea, how smart the router's classifier really is, and how to see with your
own eyes where each request went. It is written to be read top to bottom.

## 1. The Plan/Act idea, challenged

The proposal on the table was: put `auto` on Cline's **Plan** mode and
`qwen3-4b-cpu` on **Act** mode, so "a small model always executes".

I want to push back on this, because it is the risky way around.

**What Act mode actually does.** Act is not "cheap mechanical work". It is where
tool calls are emitted, files are edited, shell commands are formed, and
multi-step instructions are followed precisely. That is exactly the workload a
4B quantized model on three shared CPU cores is *worst* at. When the small model
fails there, it does not fail loudly — it produces an edit that looks plausible
and is subtly wrong, or a malformed tool call that breaks the agent loop
mid-task. You pay for the saved GPU wake with debugging time and broken code.

**Why `auto` on Plan mode has its own problem.** The router classifies each
message in isolation; it has no idea that message six belongs to the same
planning session as message one. A planning conversation contains long complex
messages (which will correctly route to the GPU) and short follow-ups like "yes,
go with option two" (which may classify as casual and drop to the CPU model).
The moment that happens, a different, weaker model is continuing a plan it never
saw the reasoning for. The tier decision for an agentic session needs to be made
*per session*, and the router can only see *per message*.

**The defensible version.** If you want to experiment with a split, the sane
direction is the one Cline's own checkbox hint describes: a strong model for
Plan (architecture quality matters, and planning prompts are the most complex
ones) and a *capable but cheaper* model for Act. Our 4B CPU tier does not
currently clear the "capable builder" bar — it is a chat-tier model. So the
practical recommendation for real work stays: **both modes on the 14B**. Use the
Plan/Act split only for throwaway experiments where a broken agent loop costs
you nothing, and expect Act-on-4B to be where experiments go to die.

If offloading Cline work to the CPU tier ever becomes a real goal, the clean
path is client-side subtasks (commit messages, summaries, file explanations)
rather than splitting the agent loop — because only the client knows where the
safe boundaries are.

## 2. What the classifier actually understands (and what it cannot)

The router's brain is a ModernBERT model doing **topic classification**, plus a
keyword list. It answers the question "what is this prompt *about*?" — computer
science, history, business, math, and so on. It does **not** estimate how hard
the task is. There is no mechanism in the current setup that reads a request and
scores "this is a simple plan" versus "this is a complicated plan". Complexity
is only approximated, indirectly, through topic and surface words.

Concrete examples from our own testing on this cluster:

| Prompt | Classifier saw | Routed to | Verdict |
|---|---|---|---|
| Tell me a fun fact about octopuses | topic: other | CPU | Correct |
| What should I see on a three-day trip to Lisbon? | topic: other | CPU | Correct |
| Write a Python function that reverses a string | topic: computer science | GPU | False positive — simple task, woke the GPU. Accepted cost. |
| Design the schema and write the migrations for a multi-tenant billing system | topic: *business* (fooled by "billing") | CPU at first | **False negative — the dangerous direction.** Fixed by adding code keywords (schema, migrations, sql…) to the agentic signal; routes to GPU now. |
| My pytest suite fails with a race condition in the async worker pool | CS + keyword "debug" | GPU | Correct |
| Plan a birthday party | topic: other | CPU | Correct |

Two lessons fall out of this:

1. **The classifier will never reliably sort "simple plan" from "complex plan"**
   within the same topic. "Plan a static one-page site" and "plan the
   event-driven rewrite of our billing pipeline" look similar to a topic
   classifier. That is why the whole configuration leans on *escalation bias*:
   when the router is unsure, it spends money (GPU) rather than risking quality
   (CPU). False positives are the price of never having false negatives.

2. **Tuning is a loop, not a one-time setup.** The billing-schema miss was found
   by throwing labeled prompts at the router and watching decisions
   (`k8s/semantic-router/test-prompts.md` is the suite). As you use the stack,
   the router logs every decision (`router_replay` keeps them 30 days), so
   future tuning can be driven by your real traffic instead of synthetic
   prompts.

## 3. Seeing where each request actually went

You have four lenses, from most convenient to most detailed.

**The chat UI badge.** Every answer in the test UI (section 4) gets a badge
under it: green "CPU tier" or orange "GPU tier", plus the exact model name and
how long the answer took. This is the everyday view.

**Response headers.** Every routed answer carries headers that tell the whole
story of the decision:

```bash
curl -s -i -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <key>" \
  -d '{"model":"auto","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
  | grep x-vsr
```

```
x-vsr-selected-model: qwen3-4b-cpu
x-vsr-selected-decision: chat_casual
x-vsr-selected-confidence: 0.6228
x-vsr-routing-latency-ms: 91.499
```

You can see which model was picked, which decision rule fired, how confident the
classifier was, and how long classification took.

**Router logs.** The raw stream of decisions:

```bash
kubectl logs -n vllm-semantic-router-system deploy/semantic-router -f | grep routing_decision
```

**Envoy access logs.** Show which upstream actually served the request
(`slm-service…` vs the KEDA interceptor):

```bash
kubectl logs -n envoy-gateway-system deploy/<envoy-deployment> -c envoy -f
```

## 4. The test chat UI

A small self-contained web UI now lives in `chat-ui/`. It exists precisely to
test routing behavior: a settings bar with the three modes, streaming answers,
and the per-answer routing badge.

Start it in two terminals:

```bash
# terminal 1: open the door to the cluster
kubectl port-forward -n envoy-gateway-system \
  svc/$(kubectl get svc -n envoy-gateway-system \
    --selector=gateway.envoyproxy.io/owning-gateway-name=semantic-router \
    -o jsonpath='{.items[0].metadata.name}') 8081:80

# terminal 2: serve the UI
python3 chat-ui/serve.py
```

Then open <http://localhost:8000>, paste the API key, and chat.

Notes:

- **Settings** (URL, key, model) are saved in the browser's localStorage. You
  can also inject them via the URL, e.g.
  `http://localhost:8000/?key=YOUR_KEY&model=auto` — handy for sharing a
  preconfigured link with yourself.
- **Why `serve.py` exists at all:** the UI is served from the same origin it
  calls, so the browser never sends a CORS preflight. We tried gateway-level
  CORS first; the preflight dies in the router's ext_proc filter before CORS
  handling, so same-origin serving is the robust answer.
- **What to expect with `auto`:** casual questions come back in a second or two
  with a green badge. Anything code-flavored will route to the GPU — if it is
  asleep, the answer takes 3-4 minutes (the request is held during the wake,
  not failed) and arrives with an orange badge.
- The model dropdown has the same three modes as every other client: `auto`,
  `qwen3-4b-cpu`, and the full 14B name.
