"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"  # override via Railway Variables or .env
    DB_NAME: str = "signal_to_action"
    # LLM settings
    GEMINI_API_KEY: str = ""
    USE_MOCK_LLM: bool = False  # Set true to bypass Gemini in tests

    # Search settings
    TAVILY_API_KEY: str = ""  # required for research tools

    # Email deployment
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "outreach@yourdomain.com"
    RESEND_WEBHOOK_SECRET: str = ""  # svix signing secret (whsec_...) — optional but recommended

    # LinkedIn deployment
    UNIPILE_API_KEY: str = ""
    UNIPILE_LINKEDIN_ACCOUNT_ID: str = ""

    # Dev flags
    USE_MOCK_SEND: bool = True  # Set false to use real Resend/Unipile

    # LLM — use get_llm() from app.core.llm to instantiate the client
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = ""  # leave empty to use the default OpenAI endpoint

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
