"""OpenAI-compatible /v1/* proxy handler."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from wai.api.admin.common import KEY_INFO_CTX, KeyInfo, api_error
from wai.proxy.access import AliasCache, ModelAccessCache
from wai.proxy.providers import get_adapter
from wai.proxy.registry import ERR_MODEL_NOT_FOUND, Model, Registry
from wai.usage.event import UsageEvent, UsageInfo, extract_usage, observe_stream_usage_line

ALLOWED_PATHS = {
    "chat/completions",
    "completions",
    "embeddings",
    "models",
}

ALLOWED_REQUEST_HEADERS = {
    "content-type",
    "accept",
    "accept-language",
    "x-request-id",
}


def is_allowed_path(path: str) -> bool:
    p = path.lstrip("/")
    if p in ALLOWED_PATHS:
        return True
    return p.startswith("images/") or p.startswith("audio/") or p.startswith("models/")


def mutate_request_body(body: bytes, canonical_model: str, inject_usage: bool) -> bytes:
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        return body
    doc["model"] = canonical_model
    if inject_usage:
        doc["stream_options"] = {"include_usage": True}
    return json.dumps(doc).encode()


class ProxyHandler:
    def __init__(
        self,
        registry: Registry,
        *,
        access_cache: ModelAccessCache | None = None,
        alias_cache: AliasCache | None = None,
        usage_logger: Any = None,
        log: logging.Logger | None = None,
        max_request_body: int = 20 * 1024 * 1024,
        max_response_body: int = 50 * 1024 * 1024,
        max_stream_duration: float = 300.0,
    ) -> None:
        self.registry = registry
        self.access_cache = access_cache
        self.alias_cache = alias_cache
        self.usage_logger = usage_logger
        self.log = log or logging.getLogger("wai.proxy")
        self.max_request_body = max_request_body
        self.max_response_body = max_response_body
        self.max_stream_duration = max_stream_duration
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(600.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def handle(self, request: Request, path: str) -> Response:
        started = time.perf_counter()
        body = await request.body()
        if len(body) > self.max_request_body:
            raise api_error(413, "payload_too_large", "request body too large")

        try:
            envelope = json.loads(body) if body else {}
        except json.JSONDecodeError:
            envelope = {}

        model_name = envelope.get("model", "")
        stream = bool(envelope.get("stream", False))
        if not model_name:
            raise api_error(400, "bad_request", "model field is required")

        key_info: KeyInfo | None = getattr(request.state, KEY_INFO_CTX, None)
        requested_model_name = model_name
        model = self._resolve_model(key_info, model_name)

        upstream_path = path.lstrip("/")
        if not is_allowed_path(upstream_path):
            raise api_error(400, "bad_request", "unsupported API endpoint")

        adapter = get_adapter(model.provider)
        needs_model_replace = model_name != model.name
        needs_stream_opts = stream
        if needs_model_replace or needs_stream_opts:
            body = mutate_request_body(body, model.name, needs_stream_opts)

        if adapter is not None:
            body = adapter.transform_request(body, model)

        if adapter is not None:
            upstream_url = adapter.transform_url(model.base_url, upstream_path, model)
        else:
            upstream_url = model.base_url.rstrip("/") + "/" + upstream_path

        headers = self._build_upstream_headers(request, model, adapter)
        method = request.method.upper()
        request_id = getattr(request.state, "request_id", "") or ""

        if stream:
            return await self._stream_response(
                method,
                upstream_url,
                headers,
                body,
                adapter,
                key_info=key_info,
                model=model,
                requested_model_name=requested_model_name,
                request_id=request_id,
                started=started,
            )

        resp = await self._client.request(method, upstream_url, content=body, headers=headers)
        content = resp.content
        if len(content) > self.max_response_body:
            raise api_error(502, "bad_gateway", "upstream response too large")
        if adapter is not None:
            content = adapter.transform_response(content)

        if (
            self.usage_logger is not None
            and key_info is not None
            and upstream_path in {"chat/completions", "completions", "embeddings"}
            and 200 <= resp.status_code < 300
        ):
            duration_ms = int((time.perf_counter() - started) * 1000)
            usage = extract_usage(content)
            self._log_usage(
                key_info,
                model,
                usage,
                duration_ms=duration_ms,
                ttft_ms=duration_ms,
                status_code=resp.status_code,
                request_id=request_id,
                requested_model_name=requested_model_name,
            )

        return Response(
            content=content,
            status_code=resp.status_code,
            headers=self._filter_response_headers(resp.headers),
            media_type=resp.headers.get("content-type"),
        )

    def _resolve_model(self, key_info: KeyInfo | None, model_name: str) -> Model:
        if self.alias_cache and key_info:
            canonical, ok = self.alias_cache.resolve(key_info.org_id, key_info.team_id, model_name)
            if ok:
                model_name = canonical
        try:
            model = self.registry.resolve(model_name)
        except KeyError as exc:
            if str(exc) == ERR_MODEL_NOT_FOUND or ERR_MODEL_NOT_FOUND in str(exc):
                raise api_error(404, "model_not_found", "the requested model was not found") from exc
            raise
        if self.access_cache and key_info:
            if not self.access_cache.check(key_info.org_id, key_info.team_id, key_info.id, model.name):
                raise api_error(403, "model_access_denied", "model access denied")
        return model

    def _build_upstream_headers(
        self, request: Request, model: Model, adapter: Any
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if ct := request.headers.get("content-type"):
            headers["Content-Type"] = ct
        if accept := request.headers.get("accept"):
            headers["Accept"] = accept
        if lang := request.headers.get("accept-language"):
            headers["Accept-Language"] = lang
        if rid := request.headers.get("x-request-id"):
            headers["X-Request-ID"] = rid
        headers["User-Agent"] = "WAI/0.1"
        if adapter is not None:
            headers = adapter.set_headers(headers, model)
        elif model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"
        return headers

    async def _stream_response(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes,
        adapter: Any,
        *,
        key_info: KeyInfo | None,
        model: Model,
        requested_model_name: str,
        request_id: str,
        started: float,
    ) -> StreamingResponse:
        usage = UsageInfo()
        ttft_ms: int | None = None
        status_code = 200
        first_chunk = True

        async def event_generator():
            nonlocal usage, ttft_ms, status_code, first_chunk
            async with self._client.stream(method, url, content=body, headers=headers) as resp:
                status_code = resp.status_code
                async for line in resp.aiter_lines():
                    chunk = (line + "\n").encode()
                    if first_chunk and line.startswith("data: "):
                        ttft_ms = int((time.perf_counter() - started) * 1000)
                        first_chunk = False
                    if adapter is not None:
                        out = adapter.transform_stream_line(chunk)
                        if out is None:
                            continue
                        chunk = out
                    usage = observe_stream_usage_line(chunk, usage)
                    yield chunk

        async def wrapped_generator():
            async for chunk in event_generator():
                yield chunk
            if (
                self.usage_logger is not None
                and key_info is not None
                and 200 <= status_code < 300
            ):
                duration_ms = int((time.perf_counter() - started) * 1000)
                self._log_usage(
                    key_info,
                    model,
                    usage,
                    duration_ms=duration_ms,
                    ttft_ms=ttft_ms if ttft_ms is not None else duration_ms,
                    status_code=status_code,
                    request_id=request_id,
                    requested_model_name=requested_model_name,
                )

        return StreamingResponse(wrapped_generator(), media_type="text/event-stream")

    def _log_usage(
        self,
        key_info: KeyInfo,
        model: Model,
        usage: UsageInfo,
        *,
        duration_ms: int,
        ttft_ms: int,
        status_code: int,
        request_id: str,
        requested_model_name: str,
    ) -> None:
        if self.usage_logger is None:
            return

        cost: float | None = None
        if model.pricing.input_per_1m > 0 or model.pricing.output_per_1m > 0:
            cost = (
                usage.prompt_tokens / 1_000_000 * model.pricing.input_per_1m
                + usage.completion_tokens / 1_000_000 * model.pricing.output_per_1m
            )

        tps: float | None = None
        if duration_ms > 0 and usage.completion_tokens > 0:
            tps = usage.completion_tokens / (duration_ms / 1000.0)

        self.usage_logger.log(
            UsageEvent(
                key_id=key_info.id,
                key_type=key_info.key_type,
                org_id=key_info.org_id,
                team_id=key_info.team_id,
                user_id=key_info.user_id,
                service_account_id=key_info.service_account_id,
                model_name=model.name,
                requested_model_name=requested_model_name,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                cost_estimate=cost,
                request_duration_ms=duration_ms,
                ttft_ms=ttft_ms,
                tokens_per_second=tps,
                status_code=status_code,
                request_id=request_id,
            )
        )

    @staticmethod
    def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
        out: dict[str, str] = {}
        if ct := headers.get("content-type"):
            out["Content-Type"] = ct
        for key, value in headers.items():
            if key.lower().startswith("x-ratelimit"):
                out[key] = value
        return out
