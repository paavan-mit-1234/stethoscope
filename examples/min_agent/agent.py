"""Minimal instrumented agent for the Phase 1 vertical-slice smoke test.

Emits one representative trace (planner node -> LLM call -> tool call ->
error) using the framework-agnostic SDK API, so it runs with no LLM key and
no LangGraph install. With Stethoscope's ingestion service listening on
:4317, the trace lands in DuckDB and `stethoscope list-traces` shows it.

    python examples/min_agent/agent.py
"""

from __future__ import annotations

import stethoscope


def main() -> None:
    stethoscope.attach(
        project="agent_v3",
        framework="langgraph",
        framework_version="0.2.0",
        redact_patterns=[r"sk-[A-Za-z0-9]{8,}"],
    )

    with stethoscope.trace_run("support-bot"):
        with stethoscope.node_span("planner"):
            with stethoscope.llm_span(
                model="claude-opus-4-7",
                provider="anthropic",
                tokens_in=824,
                tokens_out=92,
                temperature=0.0,
                cost_usd=0.0124,
                cacheable=True,
                prompt_hash="demo-hash-1",
                messages=[
                    ("system", "You are a helpful support agent. key=sk-SHOULDREDACT123"),
                    ("user", "Find me a refund policy."),
                ],
                completion="I'll search the policy database.",
            ):
                pass

        with stethoscope.node_span("tools"):
            with stethoscope.tool_span(
                "policy_search",
                arguments='{"query": "refund policy"}',
                result='{"hits": 3}',
            ):
                pass

        with stethoscope.node_span("responder"):
            try:
                with stethoscope.tool_span(
                    "send_email",
                    arguments='{"to": "user@example.com"}',
                    error="SMTP timeout after 5000ms",
                ):
                    raise RuntimeError("SMTP timeout after 5000ms")
            except RuntimeError:
                pass  # error captured on the span; trace marked failed

    stethoscope.shutdown()  # flush the exporter before exit
    print("agent run complete — trace exported")


if __name__ == "__main__":
    main()
