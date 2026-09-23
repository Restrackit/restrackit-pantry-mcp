import json

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from pantry_mcp.credentials import CredentialStore, TenantCredentials, secret_name


@pytest.fixture(autouse=True)
def _aws_region(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")


def test_secret_name_is_namespaced_by_store_id():
    assert secret_name(7) == "pantry-mcp/tenants/7"


async def test_get_returns_credentials_for_known_store():
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="eu-west-1")
        client.create_secret(
            Name=secret_name(7),
            SecretString=json.dumps({"username": "marco", "password": "hunter2"}),
        )
        store = CredentialStore()

        credentials = await store.get(7)

    assert credentials == TenantCredentials(username="marco", password="hunter2")


async def test_get_raises_for_unknown_store():
    with mock_aws():
        store = CredentialStore()

        with pytest.raises(ClientError):
            await store.get(999)
