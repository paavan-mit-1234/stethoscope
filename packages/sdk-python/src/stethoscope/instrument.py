"""Span context managers: the framework-agnostic capture API.

Every span carries `stethoscope.kind` so the ingestion mapper can classify it
without guessing. Content fields are redacted before they touch a span.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from opentelemetry.trace import Status, StatusCode

from .config import StethoscopeConfig
from .redaction import Redactor

_config: StethoscopeConfig | None = None
_tracer = None
_redact: Redactor = Redactor([])


def configure(**kwargs) -> StethoscopeConfig:
    """Set up (or reconfigure) the SDK. Safe to call multiple times."""
    global _config, _tracer, _redact
    from ._otel import init_tracer

    _config = StethoscopeConfig(**kwargs)
    _redact = Redactor(_config.redact_patterns)
    _tracer = init_tracer(_config)
    return _config


def _tracer_or_init():
    if _tracer is None:
        configure()
    return _tracer


def _attrs(**kv) -> dict:
    """Drop None values; OTel rejects them."""
    return {k: v for k, v in kv.items() if v is not None}


@contextmanager
def trace_run(name: str, **attributes) -> Iterator:
    """Root span for one agent run. Its name becomes the trace label."""
    tracer = _tracer_or_init()
    attrs = _attrs(**{"stethoscope.kind": "node_execution"}, **attributes)
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def node_span(name: str, **attributes) -> Iterator:
    tracer = _tracer_or_init()
    attrs = _attrs(**{"stethoscope.kind": "node_execution"}, **attributes)
    with tracer.start_as_current_span(f"node:{name}", attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def llm_span(
    *,
    model: str,
    provider: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    tokens_cached: int | None = None,
    temperature: float | None = None,
    messages: Sequence[tuple[str, str]] | None = None,
    completion: str | None = None,
    cost_usd: float | None = None,
    prompt_hash: str | None = None,
    cacheable: bool | None = None,
) -> Iterator:
    tracer = _tracer_or_init()
    attrs = _attrs(
        **{
            "stethoscope.kind": "llm_call",
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.request.temperature": temperature,
            "gen_ai.usage.input_tokens": tokens_in,
            "gen_ai.usage.output_tokens": tokens_out,
            "gen_ai.usage.cached_tokens": tokens_cached,
            "stethoscope.cost_usd": cost_usd,
            "stethoscope.prompt_hash": prompt_hash,
            "stethoscope.cacheable": cacheable,
        }
    )
    for i, (role, content) in enumerate(messages or []):
        attrs[f"gen_ai.prompt.{i}.role"] = role
        attrs[f"gen_ai.prompt.{i}.content"] = _redact(content)
    if completion is not None:
        attrs["gen_ai.completion.0.role"] = "assistant"
        attrs["gen_ai.completion.0.content"] = _redact(completion)

    with tracer.start_as_current_span(f"llm:{model}", attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def tool_span(
    name: str,
    *,
    arguments: str | None = None,
    result: str | None = None,
    error: str | None = None,
) -> Iterator:
    tracer = _tracer_or_init()
    attrs = _attrs(
        **{
            "stethoscope.kind": "tool_call",
            "gen_ai.tool.name": name,
            "stethoscope.tool_name": name,
            "stethoscope.tool.arguments": _redact(arguments),
            "stethoscope.tool.result": _redact(result),
            "stethoscope.tool.error": _redact(error),
        }
    )
    with tracer.start_as_current_span(f"tool:{name}", attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
