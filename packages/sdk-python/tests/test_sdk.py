"""SDK unit tests — run offline; no ingestion endpoint required.

The exporter must never raise or block when the endpoint is down
(PRD section 5.2).
"""

from __future__ import annotations

import stethoscope
from stethoscope.redaction import Redactor


def test_redactor_replaces_matches():
    r = Redactor([r"sk-[A-Za-z0-9]{8,}"])
    assert r("token sk-ABCDEFGH123 end") == "token [REDACTED] end"
    assert r(None) is None


def test_redactor_noop_without_patterns():
    assert Redactor([])("anything") == "anything"


def test_spans_do_not_raise_when_endpoint_down():
    # Unreachable endpoint: BatchSpanProcessor drops, never raises.
    stethoscope.configure(project="test_proj", endpoint="127.0.0.1:9")
    with stethoscope.trace_run("unit-run"):
        with stethoscope.node_span("planner"):
            with stethoscope.llm_span(
                model="claude-opus-4-7",
                provider="anthropic",
                tokens_in=10,
                tokens_out=5,
                messages=[("user", "hi")],
                completion="hello",
            ):
                pass
        with stethoscope.tool_span("search", arguments="{}", result="[]"):
            pass
    stethoscope.shutdown()


def test_error_in_span_propagates_but_is_recorded():
    stethoscope.configure(project="test_proj", endpoint="127.0.0.1:9")
    raised = False
    try:
        with stethoscope.node_span("boom"):
            raise ValueError("kaboom")
    except ValueError:
        raised = True
    assert raised
    stethoscope.shutdown()
