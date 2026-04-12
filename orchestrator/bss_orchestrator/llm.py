"""LLM factory — OpenRouter via the OpenAI-compatible API.

We use ``langchain_openai.ChatOpenAI`` directly (not LiteLLM) per the Phase 9
plan. OpenRouter exposes a drop-in OpenAI endpoint at ``/api/v1``, so pointing
``base_url`` at it is enough — no adapter needed.

The attribution headers (``HTTP-Referer`` and ``X-Title``) are optional but
recommended by OpenRouter for leaderboard / rate-limit tier routing.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from .config import settings


def build_chat_model(*, temperature: float = 0.0) -> ChatOpenAI:
    """Return a ``ChatOpenAI`` bound to OpenRouter and the configured model.

    Temperature defaults to ``0.0`` — BSS operations are deterministic in
    nature and the LLM should not invent values. Tool calls rely on schema
    conformance, which higher temperatures routinely break for small models
    like MiMo v2 Flash.
    """
    if not settings.llm_api_key:
        raise RuntimeError(
            "BSS_LLM_API_KEY is empty. Set it in the repo-root .env before "
            "running `bss ask` or the REPL."
        )

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
        default_headers={
            "HTTP-Referer": settings.llm_http_referer,
            "X-Title": settings.llm_app_name,
        },
    )
