"""Stethoscope SDK — one-line instrumentation for LLM agents.

    import stethoscope
    stethoscope.attach(graph)

If the API needs explanation, the API is wrong (PRD section 13.4).
"""

from __future__ import annotations

from ._otel import shutdown
from .config import StethoscopeConfig
from .instrument import (
    configure,
    llm_span,
    node_span,
    tool_span,
    trace_run,
)

__version__ = "0.1.0"

__all__ = [
    "attach",
    "configure",
    "trace_run",
    "node_span",
    "llm_span",
    "tool_span",
    "shutdown",
    "StethoscopeConfig",
]


def attach(graph: object | None = None, **config_kwargs):
    """Attach Stethoscope to an agent.

    Pass a LangGraph ``StateGraph``/``CompiledStateGraph`` to auto-instrument
    it. Any keyword (``project``, ``endpoint``, ``redact_patterns``, ...) is
    forwarded to :class:`StethoscopeConfig`. Returns ``graph`` for chaining.
    """
    configure(**config_kwargs)
    if graph is not None:
        from ._langgraph import attach_graph

        return attach_graph(graph)
    return graph
