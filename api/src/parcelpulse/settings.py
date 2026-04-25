from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://parcelpulse:parcelpulse@localhost:55432/parcelpulse"
    )
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
