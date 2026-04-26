from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: treat empty env vars (e.g. `ANTHROPIC_API_KEY=`) as
    # missing so the .env value is used instead. Some shells / runtimes export
    # secret-shaped vars as empty strings for safety; without this flag,
    # pydantic-settings prefers the empty string over the populated .env value.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )

    database_url: str = (
        "postgresql+asyncpg://parcelpulse:parcelpulse@localhost:55432/parcelpulse"
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    anthropic_api_key: str = ""
    # Hard daily ceiling on Tier 1+2 LLM spend (USD). Worker short-circuits above.
    daily_llm_cost_cap_usd: float = 5.0


settings = Settings()
