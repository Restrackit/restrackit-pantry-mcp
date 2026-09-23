from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_username: str
    keycloak_password: str
    restrackit_base_url: str
    tenants_table_name: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
