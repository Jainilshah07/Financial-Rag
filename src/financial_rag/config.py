from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    groq_api_key: str
    database_url: str | None = None  # postgresql+psycopg://user:password@localhost:5432/financial_rag
    reference_date: date | None = None  # REFERENCE_DATE=2026-10-31: "today" for answers; unset = the real date

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()


def today() -> date:
    """The date relative questions ("last month", "overdue", "so far") are answered against."""
    return settings.reference_date or date.today()