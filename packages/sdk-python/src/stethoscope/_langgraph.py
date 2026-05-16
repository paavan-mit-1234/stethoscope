"""Best-effort LangGraph instrumentation.

LangGraph internals shift between versions, so this wraps the stable public
surface (``invoke`` / ``stream`` and the node table) and degrades gracefully:
a patch failure warns but never breaks the user's agent (PRD section 4.1,
"graceful degradation").
"""

from __future__ import annotations

import functools
import logging

from .instrument import node_span, trace_run

_log = logging.getLogger("stethoscope")


def _graph_name(graph: object) -> str:
    for attr in ("name", "__name__"):
        val = getattr(graph, attr, None)
        if isinstance(val, str) and val:
            return val
    return type(graph).__name__


def _wrap_invoke(graph: object, method: str) -> None:
    fn = getattr(graph, method, None)
    if not callable(fn) or getattr(fn, "_stethoscope_wrapped", False):
        return
    name = _graph_name(graph)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with trace_run(name):
            return fn(*args, **kwargs)

    wrapper._stethoscope_wrapped = True  # type: ignore[attr-defined]
    try:
        setattr(graph, method, wrapper)
    except (AttributeError, TypeError):
        _log.warning("stethoscope: could not wrap %s.%s", name, method)


def _wrap_nodes(graph: object) -> None:
    nodes = getattr(graph, "nodes", None)
    if not isinstance(nodes, dict):
        return
    for node_name, spec in list(nodes.items()):
        target = getattr(spec, "runnable", None) or getattr(spec, "func", None)
        runner = getattr(target, "invoke", None) if target is not None else None
        if not callable(runner) or getattr(runner, "_stethoscope_wrapped", False):
            continue

        @functools.wraps(runner)
        def wrapper(*args, _n=node_name, _r=runner, **kwargs):
            with node_span(_n):
                return _r(*args, **kwargs)

        wrapper._stethoscope_wrapped = True  # type: ignore[attr-defined]
        try:
            target.invoke = wrapper  # type: ignore[attr-defined]
        except (AttributeError, TypeError):
            _log.debug("stethoscope: skipped node %s", node_name)


def attach_graph(graph: object) -> object:
    """Instrument a LangGraph ``StateGraph`` or ``CompiledStateGraph``."""
    try:
        _wrap_nodes(graph)
        for method in ("invoke", "ainvoke", "stream", "astream"):
            _wrap_invoke(graph, method)
    except Exception as exc:  # never break the user's agent
        _log.warning("stethoscope: instrumentation degraded: %s", exc)
    return graph
