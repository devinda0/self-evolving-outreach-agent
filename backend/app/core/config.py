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

    # CAN-SPAM compliance
    UNSUBSCRIBE_URL: str = ""  # e.g. https://yourdomain.com/unsubscribe
    PHYSICAL_ADDRESS: str = ""  # required by CAN-SPAM, e.g. "123 Main St, Suite 100, City, ST 00000"

    # Send-rate throttling
    SEND_RATE_LIMIT: int = 10  # max emails per interval
    SEND_RATE_INTERVAL_SECONDS: int = 1  # interval in seconds for rate limit window

    # Dead-letter queue
    WEBHOOK_DLQ_MAX_RETRIES: int = 3  # max retry attempts for failed webhook processing

    # LinkedIn deployment
    UNIPILE_DSN: str = ""
    UNIPILE_API_KEY: str = ""
    UNIPILE_LINKEDIN_ACCOUNT_ID: str = ""

    # Dev flags
    USE_MOCK_SEND: bool = True  # Set false to use real Resend/Unipile

    # LLM — use get_llm() from app.core.llm to instantiate the client
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o"
    LLM_BASE_URL: str = ""  # leave empty to use the default OpenAI endpoint

    # Outbound email signature (shown at the bottom of every sent email)
    EMAIL_SIGNATURE: str = "Signal to Action Team"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
