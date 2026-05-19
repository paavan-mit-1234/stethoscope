"""Build a replay manifest and re-run the agent (Phase 5).

Deadlock note: the store lock is held ONLY while reading the source trace to
build the manifest. It is released before the replay subprocess starts —
that subprocess exports back into the same serve process over gRPC, which
needs the same lock. Holding it across the subprocess would deadlock.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from typing import Any

from tools.ref_ingest.store import Store

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _entrypoint(spans: list[dict[str, Any]]) -> str | None:
    root = next((s for s in spans if not s.get("parent_span_id")), None)
    if not root or not root.get("attributes_json"):
        return None
    try:
        return json.loads(root["attributes_json"]).get("stethoscope.entrypoint")
    except (ValueError, TypeError):
        return None


def _build_manifest(
    store: Store,
    source_trace_id: str,
    branch_point_span_id: str,
    mutation: dict[str, Any],
) -> dict[str, Any]:
    spans = store.get_spans(source_trace_id)
    if not spans:
        raise ValueError(f"unknown trace {source_trace_id}")
    entrypoint = _entrypoint(spans)
    if not entrypoint:
        raise ValueError("source trace has no stethoscope.entrypoint")

    llm: dict[str, str] = {}
    tools: dict[str, str] = {}
    for s in spans:
        if s["kind"] == "llm_call" and s.get("prompt_hash"):
            hit = store.get_llm_cache(s["prompt_hash"])
            if hit:
                llm[s["prompt_hash"]] = hit["response_ref"]
            else:  # fallback: the captured assistant message
                msgs = store.get_messages(s["id"])
                asst = [m for m in msgs if m["role"] == "assistant"]
                if asst:
                    llm[s["prompt_hash"]] = asst[-1]["content_inline"] or ""
        if s["kind"] == "tool_call":
            tc = store.get_tool_call(s["id"])
            if tc and tc.get("result_inline") is not None:
                tools[tc["tool_name"]] = tc["result_inline"]

    # Apply the mutation. Phase 5 implements tool_response; other types are
    # spec'd in crates/replay::Mutation and surfaced (disabled) in the UI.
    if mutation.get("type") != "tool_response":
        raise ValueError(f"unsupported mutation type: {mutation.get('type')}")
    tc = store.get_tool_call(mutation["span_id"])
    if not tc:
        raise ValueError(f"span {mutation['span_id']} is not a tool call")
    tools[tc["tool_name"]] = mutation["value"]

    return {
        "parent_trace_id": source_trace_id,
        "branch_point_span_id": branch_point_span_id,
        "entrypoint": entrypoint,
        "llm": llm,
        "tools": tools,
    }


def branch(
    store: Store,
    lock: threading.Lock,
    source_trace_id: str,
    branch_point_span_id: str,
    mutation: dict[str, Any],
    otlp_endpoint: str = "127.0.0.1:4317",
) -> dict[str, Any]:
    """Reconstruct, mutate, replay. Returns a summary; the new branch trace
    arrives asynchronously over OTLP and shows up via the UI's polling."""
    with lock:  # read-only: build the manifest, then release
        manifest = _build_manifest(
            store, source_trace_id, branch_point_span_id, mutation
        )

    fd, path = tempfile.mkstemp(prefix="steth-replay-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    try:
        env = {
            **os.environ,
            "STETHOSCOPE_REPLAY": path,
            "STETHOSCOPE_ENDPOINT": otlp_endpoint,
        }
        # Lock released here on purpose — the subprocess exports via gRPC and
        # needs the same store lock to land the new trace.
        proc = subprocess.run(
            [sys.executable, manifest["entrypoint"]],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "ok": proc.returncode == 0,
            "source_trace_id": source_trace_id,
            "branch_point_span_id": branch_point_span_id,
            "entrypoint": manifest["entrypoint"],
            "stdout": (proc.stdout or "").strip().splitlines()[-3:],
            "stderr": (proc.stderr or "").strip().splitlines()[-3:],
        }
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
