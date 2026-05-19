"""Replayable agent for the Phase 5 branch/replay demo.

A tiny deterministic agent whose outcome depends on a tool response:

  planner --LLM--> "look up inventory"
  tools   --tool inventory_lookup--> {"in_stock": ...}
  decide  : in_stock ? confirm order (OK) : raise (trace FAILS)

Normal run  : inventory_lookup returns out-of-stock -> the run FAILS.
Branch+edit : the replay engine overrides that tool response with
              in-stock -> the replayed run SUCCEEDS. That divergence,
              caused by exactly one edited input, is the killer demo.

Determinism (PRD docs/replay.md): under replay every LLM call is pinned via
the manifest the engine builds from llm_cache (PRD 7.3) and every tool
returns its recorded response except the one the user mutated. The
reference uses stable step keys as the "structural prompt hash" (the PRD
permits structural, not byte-level, hashing).
"""

from __future__ import annotations

import json
import os

import stethoscope

ENTRYPOINT = "examples/replayable_agent/agent.py"

# Replay manifest (written by tools/ref_replay); absent on a normal run.
_RP = os.environ.get("STETHOSCOPE_REPLAY")
_R = json.load(open(_RP, encoding="utf-8")) if _RP else None


_LLM_DEFAULT = {
    "plan": "Look up inventory for SKU-42, then confirm the order.",
    "confirm": "Order confirmed for SKU-42.",
}


def llm(step: str, prompt: str) -> str:
    """Deterministic fake model. Under replay: pinned from the manifest on a
    cache hit; on a miss, compute (PRD docs/replay.md: miss => real call).
    The success path's `confirm` call is a miss when branching from a run
    that failed before reaching it — that's the expected behaviour."""
    if _R is not None:
        return _R["llm"].get(step, _LLM_DEFAULT[step])
    return _LLM_DEFAULT[step]


def call_tool(name: str, args: dict) -> dict:
    """Recorded tool response under replay (possibly the user's edit)."""
    if _R is not None and name in _R["tools"]:
        return json.loads(_R["tools"][name])
    # Normal run: SKU-42 is out of stock -> the agent will fail.
    return {"in_stock": False, "qty": 0, "sku": "SKU-42"}


def main() -> None:
    root_attrs = {"stethoscope.entrypoint": ENTRYPOINT}
    if _R is not None:
        root_attrs["stethoscope.parent_trace_id"] = _R["parent_trace_id"]
        root_attrs["stethoscope.branch_point_span_id"] = _R["branch_point_span_id"]

    stethoscope.attach(
        project="orders_agent",
        framework="langgraph",
        framework_version="0.2.0",
    )

    with stethoscope.trace_run("order-bot", **root_attrs):
        with stethoscope.node_span("planner"):
            with stethoscope.llm_span(
                model="claude-opus-4-7",
                provider="anthropic",
                tokens_in=210,
                tokens_out=24,
                cost_usd=0.0031,
                cacheable=True,
                prompt_hash="plan",  # stable structural key
                messages=[
                    ("system", "You are an order fulfillment agent."),
                    ("user", "Place an order for SKU-42."),
                ],
                completion=llm("plan", "place order SKU-42"),
            ):
                pass

        with stethoscope.node_span("tools"):
            with stethoscope.tool_span(
                "inventory_lookup",
                arguments='{"sku": "SKU-42"}',
            ) as tspan:
                inv = call_tool("inventory_lookup", {"sku": "SKU-42"})
                tspan.set_attribute("stethoscope.tool.result", json.dumps(inv))

        with stethoscope.node_span("decide"):
            if inv.get("in_stock"):
                with stethoscope.llm_span(
                    model="claude-opus-4-7",
                    provider="anthropic",
                    tokens_in=180,
                    tokens_out=18,
                    cost_usd=0.0026,
                    cacheable=True,
                    prompt_hash="confirm",
                    messages=[("user", "Confirm the order.")],
                    completion=llm("confirm", "confirm"),
                ):
                    pass
                print("order-bot: SUCCESS")
            else:
                try:
                    with stethoscope.tool_span(
                        "place_order",
                        arguments='{"sku": "SKU-42"}',
                        error="cannot fulfill: SKU-42 out of stock",
                    ):
                        raise RuntimeError("cannot fulfill: SKU-42 out of stock")
                except RuntimeError:
                    pass  # captured on the span; trace marked failed
                print("order-bot: FAILED (out of stock)")

    stethoscope.shutdown()


if __name__ == "__main__":
    main()
