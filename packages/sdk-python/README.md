# stethoscope-py

One-line instrumentation for LLM agents. Captures OpenTelemetry GenAI spans
plus Stethoscope extensions and ships them over OTLP/gRPC to a local
Stethoscope ingestion endpoint (default `localhost:4317`).

```python
import stethoscope

stethoscope.attach(graph)          # LangGraph StateGraph or CompiledStateGraph
graph.invoke({"messages": [...]})  # traces now appear in Stethoscope
```

Framework-agnostic manual API (no LangGraph required):

```python
import stethoscope

stethoscope.configure(project="agent_v3")

with stethoscope.trace_run("support-bot"):
    with stethoscope.node_span("planner"):
        with stethoscope.llm_span(model="claude-opus-4-7", provider="anthropic",
                                  tokens_in=824, tokens_out=92,
                                  messages=[("system", "You are..."),
                                            ("user", "What...")]):
            ...
        with stethoscope.tool_span("web_search", arguments='{"q":"..."}',
                                   result="[...]"):
            ...
```

Design rules (PRD section 13.4): one line to attach; if the API needs
explanation, the API is wrong. Never blocks the agent — if the ingestion
endpoint is down, spans are dropped with a warning, never hung.
