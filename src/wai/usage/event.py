"""Usage event types and OpenAI response parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class UsageEvent:
    key_id: str
    key_type: str
    org_id: str
    team_id: str
    user_id: str
    service_account_id: str
    model_name: str
    requested_model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_estimate: float | None
    request_duration_ms: int
    ttft_ms: int | None
    tokens_per_second: float | None
    status_code: int
    request_id: str


def extract_usage(body: bytes) -> UsageInfo:
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        return UsageInfo()
    usage = doc.get("usage")
    if not isinstance(usage, dict):
        return UsageInfo()
    return UsageInfo(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )


def observe_stream_usage_line(line: bytes, current: UsageInfo) -> UsageInfo:
    if not line.startswith(b"data: {"):
        return current
    try:
        doc = json.loads(line[6:])
    except json.JSONDecodeError:
        return current
    usage = doc.get("usage")
    if not isinstance(usage, dict):
        return current
    return UsageInfo(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
    )
