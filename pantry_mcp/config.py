from functools import lru_cache

import boto3
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    keycloak_url: str
    keycloak_realm: str
    keycloak_connector_client_id: str
    keycloak_exchange_client_id: str
    keycloak_exchange_client_secret: str | None = None
    keycloak_exchange_client_secret_name: str | None = None
    restrackit_backend_client_id: str
    restrackit_base_url: str

    @model_validator(mode="after")
    def _resolve_exchange_client_secret(self) -> "Settings":
        """Fetch the exchange client secret from Secrets Manager if only its name is set.

        The installed aws-cdk-lib version has no direct Lambda-env-from-Secrets-Manager
        binding, so the Lambda gets the secret's NAME as a plain env var and this
        resolves the actual value once at process startup (get_settings is
        lru_cache'd, so this runs at most once per process).
        """
        if self.keycloak_exchange_client_secret is None:
            if not self.keycloak_exchange_client_secret_name:
                raise ValueError(
                    "Set KEYCLOAK_EXCHANGE_CLIENT_SECRET or "
                    "KEYCLOAK_EXCHANGE_CLIENT_SECRET_NAME"
                )
            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=self.keycloak_exchange_client_secret_name)
            self.keycloak_exchange_client_secret = response["SecretString"]
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
