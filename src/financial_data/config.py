"""Application settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Represent Settings."""

    database_url: str = "postgresql+asyncpg://rates:rates@localhost:5433/rates"
    rate_provider_timeout_seconds: int = 10
    mindicador_base_url: str = "https://mindicador.cl/api"
    sii_base_url: str = "https://www.sii.cl"
    bcch_api_base_url: str = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
    bcch_api_user: str | None = None
    bcch_api_password: str | None = None
    bcch_series_uf: str | None = None
    bcch_series_usd: str | None = None
    bcch_series_eur: str | None = None
    bcch_series_utm: str | None = None
    bcch_series_ipc_cl: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FINANCIAL_DATA_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
