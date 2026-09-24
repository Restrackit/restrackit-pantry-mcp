from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    keycloak_url: str
    keycloak_realm: str
    keycloak_connector_client_id: str
    keycloak_exchange_client_id: str
    keycloak_exchange_client_secret: str
    restrackit_base_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
