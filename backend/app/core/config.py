"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"  # override via Railway Variables or .env
    DB_NAME: str = "signal_to_action"
    TAVILY_API_KEY: str = ""  # required for research tools

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
