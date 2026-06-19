"""Provider adapters for upstream LLM APIs."""

from wai.proxy.providers.azure import AzureAdapter
from wai.proxy.providers.base import Adapter, PassthroughAdapter
from wai.proxy.providers.ollama import OllamaAdapter
from wai.proxy.providers.openai import OpenAIAdapter


def get_adapter(provider: str) -> Adapter | None:
    if provider == "azure":
        return AzureAdapter()
    if provider == "ollama":
        return OllamaAdapter()
    if provider in ("openai", "vllm", "custom"):
        return OpenAIAdapter()
    return None
