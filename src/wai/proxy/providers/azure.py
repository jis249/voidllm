"""Azure OpenAI adapter."""

from __future__ import annotations

import json

from wai.proxy.providers.base import Adapter
from wai.proxy.registry import Model


class AzureAdapter:
    def transform_request(self, body: bytes, model: Model) -> bytes:
        if not _requires_max_completion_tokens(model):
            return body
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return body
        if "max_tokens" in doc and "max_completion_tokens" not in doc:
            doc["max_completion_tokens"] = doc.pop("max_tokens")
        return json.dumps(doc).encode()

    def transform_url(self, base_url: str, upstream_path: str, model: Model) -> str:
        version = model.azure_api_version or "2024-10-21"
        deployment = model.azure_deployment or model.name
        return (
            f"{base_url.rstrip('/')}/openai/deployments/{deployment}/"
            f"{upstream_path.lstrip('/')}?api-version={version}"
        )

    def set_headers(self, headers: dict[str, str], model: Model) -> dict[str, str]:
        out = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        if model.api_key:
            out["api-key"] = model.api_key
        return out

    def transform_response(self, body: bytes) -> bytes:
        return body

    def transform_stream_line(self, line: bytes) -> bytes | None:
        return line


def _requires_max_completion_tokens(model: Model) -> bool:
    name = model.name.lower()
    deployment = (model.azure_deployment or "").lower()
    return name.startswith("gpt-5") or deployment.startswith("gpt-5")
