"""
EHR LLM provider factory for Browser-Use.

Reads EHR_LLM_PROVIDER env var and returns the correct LangChain BaseChatModel:
  ollama        — local Ollama (dev; no data leaves machine)
  azure_openai  — Azure OpenAI (production; HIPAA BAA covers text inputs)

Usage:
    from Clinic_app.services.ehr_llm_provider import get_ehr_llm
    llm = get_ehr_llm()  # cached singleton
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_cached_llm: Optional[Any] = None


def get_ehr_llm() -> Any:
    """
    Return a cached LangChain BaseChatModel for Browser-Use EHR navigation.
    Reads EHR_LLM_PROVIDER on first call; raises RuntimeError if misconfigured.
    """
    global _cached_llm
    if _cached_llm is not None:
        return _cached_llm

    # Ensure .env is loaded even if this module is imported before database.py
    from Clinic_app.common.env import load_project_dotenv

    load_project_dotenv()

    provider = os.environ.get("EHR_LLM_PROVIDER", "").strip().lower()
    if not provider:
        raise RuntimeError(
            "EHR_LLM_PROVIDER environment variable is required. "
            "Set to 'ollama' (local dev) or 'azure_openai' (production)."
        )

    if provider == "ollama":
        _cached_llm = _build_ollama()
    elif provider == "azure_openai":
        _cached_llm = _build_azure_openai()
    else:
        raise RuntimeError(
            f"Unknown EHR_LLM_PROVIDER={provider!r}. Must be 'ollama' or 'azure_openai'."
        )

    return _cached_llm


def _build_ollama() -> Any:
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:32b")
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise RuntimeError(
            "langchain-ollama is not installed. "
            "Run: pip install langchain-ollama"
        ) from exc
    llm = ChatOllama(model=model, base_url=base_url, temperature=0.0)
    logger.info("EHR LLM: Ollama (model=%s, base_url=%s)", model, base_url)
    return llm


def _build_azure_openai() -> Any:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-07-18")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "")

    missing = [
        k for k, v in [
            ("AZURE_OPENAI_ENDPOINT", endpoint),
            ("AZURE_OPENAI_API_KEY", api_key),
            ("AZURE_OPENAI_DEPLOYMENT_NAME", deployment),
        ]
        if not v
    ]
    if missing:
        raise RuntimeError(
            f"Azure OpenAI env vars missing when EHR_LLM_PROVIDER=azure_openai: "
            f"{', '.join(missing)}"
        )

    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "langchain-openai is not installed. "
            "Run: pip install langchain-openai"
        ) from exc

    llm = AzureChatOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        azure_deployment=deployment,
        temperature=0.0,
    )
    logger.info("EHR LLM: Azure OpenAI (deployment=%s)", deployment)
    return llm
