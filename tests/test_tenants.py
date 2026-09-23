import boto3
import pytest
from moto import mock_aws

from pantry_mcp.tenants import Tenant, TenantStore, hash_token

TABLE_NAME = "PantryMcpTenants"


@pytest.fixture(autouse=True)
def _aws_region(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")


@pytest.fixture
def dynamodb_table():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="eu-west-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "token_hash", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "token_hash", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


async def test_resolve_returns_tenant_for_known_token(dynamodb_table):
    dynamodb_table.put_item(
        TableName=TABLE_NAME,
        Item={
            "token_hash": {"S": hash_token("friend-token")},
            "store_id": {"N": "7"},
            "name": {"S": "Marco"},
        },
    )
    store = TenantStore(TABLE_NAME)

    tenant = await store.resolve("friend-token")

    assert tenant == Tenant(store_id=7, name="Marco")


async def test_resolve_returns_none_for_unknown_token(dynamodb_table):
    store = TenantStore(TABLE_NAME)

    tenant = await store.resolve("no-such-token")

    assert tenant is None


async def test_resolve_returns_none_when_table_is_missing():
    with mock_aws():
        store = TenantStore("table-that-does-not-exist")

        tenant = await store.resolve("any-token")

    assert tenant is None


def test_hash_token_is_deterministic_and_sha256():
    import hashlib

    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
