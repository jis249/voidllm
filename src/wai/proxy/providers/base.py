"""Base adapter protocol for provider-specific request/response transforms."""

from __future__ import annotations

from typing import Protocol

from wai.proxy.registry import Model


class Adapter(Protocol):
    def transform_request(self, body: bytes, model: Model) -> bytes: ...

    def transform_url(self, base_url: str, upstream_path: str, model: Model) -> str: ...

    def set_headers(self, headers: dict[str, str], model: Model) -> dict[str, str]: ...

    def transform_response(self, body: bytes) -> bytes: ...

    def transform_stream_line(self, line: bytes) -> bytes | None: ...


class PassthroughAdapter:
    """OpenAI-compatible passthrough — no body/response rewriting."""

    def transform_request(self, body: bytes, model: Model) -> bytes:
        return body

    def transform_url(self, base_url: str, upstream_path: str, model: Model) -> str:
        return base_url.rstrip("/") + "/" + upstream_path.lstrip("/")

    def set_headers(self, headers: dict[str, str], model: Model) -> dict[str, str]:
        out = dict(headers)
        if model.api_key:
            out["Authorization"] = f"Bearer {model.api_key}"
        return out

    def transform_response(self, body: bytes) -> bytes:
        return body

    def transform_stream_line(self, line: bytes) -> bytes | None:
        return line
