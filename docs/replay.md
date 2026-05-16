# Deterministic Replay of Non-Deterministic LLMs

> The novel technical contribution (PRD sections 2, 13.6). This document is
> the design; the runtime lands in Phase 5. Keep it accurate as the
> implementation evolves — it is intended to become the launch blog post.

## The problem

Re-running an agent is not reproducible: LLM sampling is stochastic, tool
calls hit live systems, and IDs/timestamps differ every run. You cannot
"step back and try again" if every run is a new universe.

## The trick: pin the non-determinism, not the code

Replay re-executes the **real agent code** but intercepts its two sources of
non-determinism:

1. **LLM calls** — keyed by a *structural* prompt hash
   `sha256(model + system + messages + params)` (see
   `stethoscope_store::llm_cache`, PRD 7.3). On replay:
   - cache hit  → return the captured response (deterministic)
   - cache miss → make a real call, store the result for next time
   The hash is structural, not byte-level, so semantically identical
   contexts collide intentionally (PRD section 11, replay risk row).
2. **Tool calls** — snapshotted request→response pairs. Replayed tools
   return the recorded response unless the user explicitly mutated it.

## Branching

A branch = replay from a chosen span with one mutation
(`stethoscope_replay::Mutation`): edited user message, system prompt, tool
response, state value, or model param. Spans before the branch point are
**referenced, not copied** (PRD section 4.4); the new trace records
`parent_trace_id` + `branch_point_span_id`.

## Known limits (be honest — PRD section 11)

- Non-LLM, non-tool nondeterminism (random seeds, wall-clock,
  auto-generated IDs) is only partially controlled. We pin seeds where the
  framework exposes them and document the rest.
- Structural-hash collisions are a *feature* for replay but mean the cache
  is not a perfect audit log; the raw trace is the source of truth.

## Sandbox

Replay runs in Docker (primary) or a reused venv (fast path), with no
network by default (PRD section 5.3). Cold start budget < 8s, warm < 2s
(PRD section 5.1).
