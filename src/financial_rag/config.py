from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str
    groq_api_key: str
    database_url: str | None = None  # postgresql+psycopg://user:password@localhost:5432/financial_rag

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()