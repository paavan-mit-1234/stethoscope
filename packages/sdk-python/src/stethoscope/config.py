"""Stethoscope SDK configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class StethoscopeConfig:
    """Resolved SDK configuration.

    Endpoint and project can be overridden via env:
      STETHOSCOPE_ENDPOINT   default 127.0.0.1:4317
      STETHOSCOPE_PROJECT    default "default"
    """

    endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "STETHOSCOPE_ENDPOINT", "127.0.0.1:4317"
        )
    )
    project: str = field(
        default_factory=lambda: os.environ.get("STETHOSCOPE_PROJECT", "default")
    )
    # Transport: "grpc" (local ingestion, default) or "http" (Stethoscope
    # Cloud — OTLP/HTTP to https://.../v1/traces with an API key).
    transport: str = field(
        default_factory=lambda: os.environ.get("STETHOSCOPE_TRANSPORT", "grpc")
    )
    api_key: str | None = field(
        default_factory=lambda: os.environ.get("STETHOSCOPE_API_KEY")
    )
    framework: str = "langgraph"
    framework_version: str | None = None
    # Regex patterns whose matches are replaced with "[REDACTED]" before export.
    redact_patterns: list[str] = field(default_factory=list)
    # When the endpoint is unreachable, spans are dropped (never block the
    # agent). Disk-buffer + retry is a documented follow-up.
    enabled: bool = True
