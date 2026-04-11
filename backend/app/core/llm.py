"""Centralized LLM factory — swap the backing model in one place.

All agents MUST import and call get_llm() from here rather than
instantiating their own LLM clients.

Configuration via environment variables (see config.py):
  OPENAI_API_KEY  — API key for the OpenAI-compatible endpoint
  LLM_MODEL       — model name, default "gpt-4o"
  USE_MOCK_LLM    — set True in tests to skip real API calls
"""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def get_llm(temperature: float = 0) -> ChatOpenAI | None:
    """Return a configured ChatOpenAI instance.

    Returns None when USE_MOCK_LLM is True so callers can inject mocks.

    Args:
        temperature: Sampling temperature passed to the model.

    Raises:
        ValueError: If OPENAI_API_KEY is not configured.
    """
    if settings.USE_MOCK_LLM:
        return None

    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set in environment variables")

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        temperature=temperature,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.LLM_BASE_URL or None,
    )
