"""Providers de LLM. `get_provider(config)` devolve o cliente certo para uma ModelConfig."""

from .base import LLMResult, Provider, ProviderError, parse_json


def get_provider(config) -> Provider:
    if config.provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(config)
    if config.provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(config)
    if config.provider == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(config)
    raise ProviderError(f"provider sem cliente: {config.provider}")


__all__ = ["LLMResult", "Provider", "ProviderError", "get_provider", "parse_json"]
