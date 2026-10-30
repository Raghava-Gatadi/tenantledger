from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://ledger_app:local-app-password@localhost:5433/ledger"
    app_url: str = "http://localhost:8000"
    oidc_issuer: str = "http://localhost:8080/realms/tenantledger"
    oidc_internal_url: str = "http://localhost:8080/realms/tenantledger"
    oidc_client_id: str = "tenantledger-web"
    oidc_client_secret: str = "local-web-client-secret"
    oidc_audience: str = "tenantledger-api"
    oidc_api_client_secret: str = "local-api-client-secret"
    session_secret: str
    token_encryption_key: str
    cookie_secure: bool = False
    environment: str = "development"
    session_max_seconds: int = 1800
    max_receipt_bytes: int = 2_000_000

    @model_validator(mode="after")
    def safe_settings(self):
        if len(self.session_secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        if self.environment != "development":
            if not self.cookie_secure or not self.app_url.startswith("https://"):
                raise ValueError("Non-development deployments require HTTPS and secure cookies")
            if not self.oidc_issuer.startswith("https://"):
                raise ValueError("Non-development OIDC issuer must use HTTPS")
            if self.oidc_client_secret == "local-web-client-secret":
                raise ValueError("Replace the development OIDC client secret")
            if self.oidc_api_client_secret == "local-api-client-secret":
                raise ValueError("Replace the development API introspection secret")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
