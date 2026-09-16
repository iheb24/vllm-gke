# Synthetic Routing Test Suite

Labeled prompts used to validate and tune the routing decisions. Send each via the
gateway with `model: "auto"` and record which tier answered (gateway / semantic
router logs, or `router_replay` records).

Expectations under escalation bias:

- `code-agentic` MUST reach the GPU tier (100%).
- `chat-casual` SHOULD reach the CPU tier.
- `code-simple` MAY reach either; GPU is an accepted false positive.

## code-agentic (expect GPU)

1. Refactor the authentication module across all files in this repo to use JWT refresh tokens.
2. My pytest suite fails with a race condition in the async worker pool. Debug it and propose a fix.
3. Implement a retry-with-backoff wrapper for every HTTP call in this codebase.
4. Review this diff for memory leaks and rewrite the affected functions: <paste>.
5. Migrate this Express app to Fastify, updating routes, middleware, and tests.
6. The Kubernetes liveness probe keeps killing my pod under load. Analyze the deployment and fix the probe tuning.
7. Add optimistic locking to the order service and update all call sites.
8. Profile this Python ETL script, find the bottleneck, and rewrite it to run under 2 minutes.
9. Design the schema and write the migrations for a multi-tenant billing system.
10. Our CI pipeline intermittently fails on the Docker build step. Diagnose the layer caching issue and fix the Dockerfile.

## code-simple (either tier acceptable, CPU preferred)

1. Write a hello world script in Python.
2. Write a bash one-liner to count lines in all .go files.
3. Write a Python function that reverses a string.
4. Show me a curl command to POST JSON to an endpoint.
5. Write a regex that matches an email address.
6. Write a SQL query to get the top 10 customers by revenue.
7. Write a JavaScript debounce function.
8. How do I list all open ports on macOS?
9. Write a Python dict comprehension that filters out None values.
10. Give me a minimal docker-compose for Redis.

## chat-casual (expect CPU)

1. What's a good recipe for vegetarian lasagna?
2. Explain the plot of Inception to me like I'm ten.
3. What are the main causes of the French Revolution?
4. Recommend some science fiction books similar to Dune.
5. What's the difference between a stock and a bond?
6. How do I improve my sleep quality?
7. Tell me a fun fact about octopuses.
8. What should I see on a three-day trip to Lisbon?
9. Explain what inflation is in simple terms.
10. Help me write a birthday message for a colleague.
