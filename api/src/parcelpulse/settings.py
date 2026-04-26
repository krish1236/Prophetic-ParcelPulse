from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://parcelpulse:parcelpulse@localhost:55432/parcelpulse"
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    anthropic_api_key: str = ""
    # Hard daily ceiling on Tier 1+2 LLM spend (USD). Worker short-circuits above.
    daily_llm_cost_cap_usd: float = 5.0


settings = Settings()
